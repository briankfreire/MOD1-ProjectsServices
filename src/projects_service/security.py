import threading
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
            settings.jwks_url, timeout=5, cache_jwk_set=True, lifespan=300, cache_keys=False
        )
        self.lock = threading.RLock()

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
        with self.lock:
            try:
                keys = self.client.get_signing_keys()
                key = next((key for key in keys if key.key_id == header["kid"]), None)
                if key is None:
                    keys = self.client.get_signing_keys(refresh=True)
                    key = next((key for key in keys if key.key_id == header["kid"]), None)
            except (jwt.PyJWTError, ValueError, TypeError, OSError, TimeoutError):
                raise SigningKeysUnavailable("Trusted signing keys unavailable") from None
        if key is None or key.algorithm_name != "RS256" or key.key_type != "RSA":
            raise AuthenticationRejected("Token rejected")

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
