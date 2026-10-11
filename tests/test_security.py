import json
import time
from uuid import uuid4

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from projects_service.security import AuthenticationRejected, SigningKeysUnavailable, TokenVerifier


def test_verifier_claims_and_signature(issuer):
    verifier = TokenVerifier(issuer["settings"])
    assert verifier.verify(issuer["token"]()) == issuer["owner"]
    bad_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    for token in (
        issuer["token"](signing_key=bad_key),
        "invalid-token",
        jwt.encode({"sub": str(uuid4())}, "x" * 32, algorithm="HS256"),
        jwt.encode({"sub": str(uuid4())}, None, algorithm="none"),
        issuer["token"](headers={"typ": "OTHER"}),
        issuer["token"](headers={"kid": ""}),
    ):
        with pytest.raises(AuthenticationRejected):
            verifier.verify(token)
    assert verifier.verify(issuer["token"](headers={"jku": "http://remote.invalid/jwks"}))


@pytest.mark.parametrize(
    "updates",
    [
        {"iss": "other"},
        {"aud": "other"},
        {"aud": ["engenharia-software-api"]},
        {"exp": 100},
        {"iat": int(time.time()) + 600},
        {"sub": "invalid"},
        {"jti": "invalid"},
        {"sub": 123},
        {"iat": True},
        {"exp": True},
        {"iat": "123"},
        {"exp": "123"},
        {"exp": int(time.time()), "iat": int(time.time())},
    ],
)
def test_rejects_invalid_claims(issuer, updates):
    with pytest.raises(AuthenticationRejected):
        TokenVerifier(issuer["settings"]).verify(issuer["token"](updates=updates))


@pytest.mark.parametrize("name", ["sub", "iss", "aud", "iat", "exp", "jti"])
def test_requires_claims(issuer, name):
    with pytest.raises(AuthenticationRejected):
        TokenVerifier(issuer["settings"]).verify(issuer["token"](omit=[name]))


def test_jwks_outage_cache_and_rotation(issuer):
    verifier = TokenVerifier(issuer["settings"])
    token = issuer["token"]()
    assert verifier.verify(token) == issuer["owner"]
    issuer["state"]["status"] = 503
    assert verifier.verify(token) == issuer["owner"]
    with pytest.raises(SigningKeysUnavailable):
        TokenVerifier(issuer["settings"]).verify(token)
    verifier.client.jwk_set_cache.lifespan = 0
    with pytest.raises(SigningKeysUnavailable):
        verifier.verify(token)
    issuer["state"]["status"] = 200
    verifier = TokenVerifier(issuer["settings"])
    verifier.verify(token)
    with pytest.raises(AuthenticationRejected):
        verifier.verify(issuer["token"](headers={"kid": "unknown"}))
    new_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(new_key.public_key()))
    public.update(kid="rotated", alg="RS256", use="sig")
    issuer["state"]["payload"] = {"keys": [public]}
    assert verifier.verify(issuer["token"](signing_key=new_key, headers={"kid": "rotated"}))


@pytest.mark.parametrize("payload", [[], {}, {"keys": []}, {"keys": [{"kty": "RSA"}]}])
def test_malformed_trusted_key_source_is_unavailable(issuer, payload):
    issuer["state"]["payload"] = payload
    with pytest.raises(SigningKeysUnavailable):
        TokenVerifier(issuer["settings"]).verify(issuer["token"]())


def test_jwks_timeout_is_unavailable(issuer, monkeypatch):
    verifier = TokenVerifier(issuer["settings"])

    def timeout():
        raise TimeoutError("synthetic private URL must not leak")

    monkeypatch.setattr(verifier.client, "fetch_data", timeout)
    with pytest.raises(SigningKeysUnavailable) as error:
        verifier.verify(issuer["token"]())
    assert "private" not in str(error.value)
