import dataclasses
import json
import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException
from starlette.requests import Request

from app import auth

ISS, AUD = "https://idp.example/realms/noc", "telecom-ops"


@pytest.fixture(scope="module")
def keys():
    priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(priv.public_key()))
    jwk.update(kid="k1", alg="RS256", use="sig")
    return priv, other, json.dumps({"keys": [jwk]})


@pytest.fixture(autouse=True)
def oidc(monkeypatch, keys):
    monkeypatch.setattr(auth, "settings", dataclasses.replace(
        auth.settings, oidc_issuer=ISS, oidc_audience=AUD, oidc_jwks_json=keys[2],
        auth_required=True, rate_limit_per_min=0))


def token(key, kid="k1", alg="RS256", **over):
    claims = {"iss": ISS, "aud": AUD, "sub": "u-1", "preferred_username": "amira",
              "roles": ["approver"], "exp": int(time.time()) + 300, **over}
    claims = {k: v for k, v in claims.items() if v is not None}
    return jwt.encode(claims, key, algorithm=alg, headers={"kid": kid})


def test_valid_token_maps_to_highest_known_role(keys):
    p = auth.authenticate_bearer(token(keys[0], roles=["viewer", "operator", "approver"]))
    assert p == auth.Principal("sso:amira", "approver")


@pytest.mark.parametrize("over", [
    {"exp": int(time.time()) - 10},        # expired
    {"aud": "someone-else"},               # wrong audience
    {"iss": "https://evil.example"},       # wrong issuer
    {"roles": ["viewer"]},                 # no recognised role
    {"roles": None},                       # no role claim at all
    {"exp": None},                         # no expiry
])
def test_bad_claims_are_rejected(keys, over):
    assert auth.authenticate_bearer(token(keys[0], **over)) is None


def test_wrong_signature_and_alg_none_are_rejected(keys):
    assert auth.authenticate_bearer(token(keys[1])) is None            # signed by another key
    forged = jwt.encode({"iss": ISS, "aud": AUD, "sub": "x", "roles": ["admin"],
                         "exp": int(time.time()) + 99}, None, algorithm="none")
    assert auth.authenticate_bearer(forged) is None
    assert auth.authenticate_bearer("not-a-jwt") is None


def test_hs256_with_public_key_confusion_is_rejected(keys):
    """Classic downgrade attack: sign with HMAC using the PEM public key as the secret. PyJWT
    refuses to build this, so assemble it by hand; our decoder must still refuse it."""
    import base64
    import hashlib
    import hmac

    from cryptography.hazmat.primitives import serialization

    def b64(b):
        return base64.urlsafe_b64encode(b).rstrip(b"=")
    pem = keys[0].public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    head = b64(json.dumps({"alg": "HS256", "typ": "JWT", "kid": "k1"}).encode())
    body = b64(json.dumps({"iss": ISS, "aud": AUD, "sub": "x", "roles": ["admin"],
                           "exp": int(time.time()) + 99}).encode())
    sig = b64(hmac.new(pem, head + b"." + body, hashlib.sha256).digest())
    assert auth.authenticate_bearer((head + b"." + body + b"." + sig).decode()) is None


def test_nested_role_claim(monkeypatch, keys):
    monkeypatch.setattr(auth, "settings", dataclasses.replace(
        auth.settings, oidc_role_claim="realm_access.roles"))
    t = token(keys[0], roles=None, realm_access={"roles": ["admin"]})
    assert auth.authenticate_bearer(t).role == "admin"


def _req():
    return Request({"type": "http", "headers": [], "client": ("1.2.3.4", 1), "method": "GET",
                    "path": "/"})


def test_dependency_accepts_bearer_enforces_role_and_401s_bad_tokens(keys):
    dep = auth.require("approver")
    ok = dep(_req(), x_api_key=None, authorization="Bearer " + token(keys[0]))
    assert ok.name == "sso:amira" and ok.role == "approver"
    with pytest.raises(HTTPException) as e:
        auth.require("admin")(_req(), x_api_key=None, authorization="Bearer " + token(keys[0]))
    assert e.value.status_code == 403
    with pytest.raises(HTTPException) as e:
        dep(_req(), x_api_key=None, authorization="Bearer " + token(keys[1]))
    assert e.value.status_code == 401
    with pytest.raises(HTTPException) as e:
        dep(_req(), x_api_key=None, authorization=None)
    assert e.value.status_code == 401


def test_non_iterable_role_claim_is_a_401_not_a_500(keys):
    assert auth.authenticate_bearer(token(keys[0], roles=7)) is None
    assert auth.authenticate_bearer(token(keys[0], roles={"approver": True})) is None
