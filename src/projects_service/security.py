import threading
import time
from uuid import UUID

import jwt

from projects_service.config import Settings


class AuthenticationRejected(Exception):
    pass


class SigningKeysUnavailable(Exception):
    pass


class TokenVerifier:
    def __init__(self, settings: Settings) -> None:
        self.issuer = settings.jwt_issuer
        self.audience = settings.jwt_audience
        self.client = jwt.PyJWKClient(
            settings.jwks_url, timeout=5, cache_jwk_set=False, cache_keys=False
        )
        self.lock = threading.Lock()
        self.keys: tuple[jwt.PyJWK, ...] = ()
        self.expires_at = 0.0
        self.next_refresh_at = 0.0
        self.refreshing = False

    def signing_key(self, kid: str) -> jwt.PyJWK:
        # The lock protects snapshots only; cached verification never waits for network I/O.
        with self.lock:
            now = time.monotonic()
            keys = self.keys if now < self.expires_at else ()
            key = next((key for key in keys if key.key_id == kid), None)
            if key is not None:
                return key
            if self.refreshing or now < self.next_refresh_at:
                if keys:
                    raise AuthenticationRejected("Token rejected")
                raise SigningKeysUnavailable("Trusted signing keys unavailable")
            self.refreshing = True
            # Failed attempts also consume the interval, preventing retry storms.
            self.next_refresh_at = now + 30

        try:
            fresh = tuple(
                key for key in self.client.get_signing_keys(refresh=True)
                if key.algorithm_name == "RS256" and key.key_type == "RSA"
            )
            if not fresh:
                raise SigningKeysUnavailable("Trusted signing keys unavailable")
            with self.lock:
                self.keys = fresh
                self.expires_at = time.monotonic() + 300
        except (jwt.PyJWTError, ValueError, TypeError, OSError, TimeoutError):
            raise SigningKeysUnavailable("Trusted signing keys unavailable") from None
        finally:
            with self.lock:
                self.refreshing = False
        key = next((key for key in fresh if key.key_id == kid), None)
        if key is None:
            raise AuthenticationRejected("Token rejected")
        return key

    def verify(self, token: str) -> UUID:
        try:
            header = jwt.get_unverified_header(token)
            if (
                header.get("alg") != "RS256"
                or header.get("typ") != "JWT"
                or not isinstance(header.get("kid"), str)
                or not header["kid"]
            ):
                raise ValueError("Invalid header")
        except (jwt.PyJWTError, ValueError, TypeError):
            raise AuthenticationRejected("Token rejected") from None

        # Fetch only from configuration. Separate trusted-source failure from a bad token.
        key = self.signing_key(header["kid"])

        try:
            claims = jwt.decode(
                token,
                key.key,
                algorithms=["RS256"],
                issuer=self.issuer,
                audience=self.audience,
                leeway=5,
                options={"require": ["sub", "iss", "aud", "iat", "exp", "jti"], "strict_aud": True},
            )
            if (
                type(claims["iat"]) is not int
                or type(claims["exp"]) is not int
                or claims["exp"] <= claims["iat"]
                or not isinstance(claims["sub"], str)
                or not isinstance(claims["jti"], str)
            ):
                raise ValueError("Invalid claims")
            UUID(claims["jti"])
            return UUID(claims["sub"])
        except (jwt.PyJWTError, ValueError, TypeError, KeyError):
            raise AuthenticationRejected("Token rejected") from None
