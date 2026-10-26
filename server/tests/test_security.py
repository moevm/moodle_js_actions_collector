import hashlib

import pytest
from itsdangerous import TimestampSigner

from src.core.passwords import hash_password, verify_password, verify_login_password
from src.core.security import AccessTokens, SecuritySettings


SIGNING = "test-signing-" + "a" * 40
INGEST = "test-ingestion-" + "b" * 40
USER = {"_id": "60d5ec49f1a4a21f6c8b4567", "password": "private-password"}


@pytest.mark.parametrize("settings", [
    {}, {"COLLECTOR_AUTH_SECRET": SIGNING},
    {"COLLECTOR_AUTH_SECRET": SIGNING, "COLLECTOR_INGEST_KEY": SIGNING},
    {"COLLECTOR_AUTH_SECRET": SIGNING, "COLLECTOR_INGEST_KEY": INGEST, "COLLECTOR_ACCESS_TOKEN_TTL_SECONDS": "0"},
])
def test_missing_or_invalid_security_configuration_fails_closed(settings: dict) -> None:
    with pytest.raises(ValueError):
        SecuritySettings.from_env(settings)


def test_access_token_contains_no_password_and_is_bound_to_current_password() -> None:
    tokens = AccessTokens(SecuritySettings(SIGNING, INGEST))
    token = tokens.issue(USER)
    claims = tokens.decode(token)
    assert claims.subject == USER["_id"]
    assert tokens.matches_user(claims, USER)
    assert not tokens.matches_user(claims, {**USER, "password": "changed"})
    payload = tokens.serializer.loads(token[3:])
    assert set(payload) == {"sub", "v"}
    assert payload["v"] != hashlib.sha256(USER["password"].encode()).hexdigest()


def test_expired_tampered_and_write_only_tokens_are_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    now = [1700000000]
    monkeypatch.setattr(TimestampSigner, "get_timestamp", lambda self: now[0])
    tokens = AccessTokens(SecuritySettings(SIGNING, INGEST, token_ttl_seconds=10))
    token = tokens.issue(USER)
    with pytest.raises(ValueError):
        tokens.decode(token + ".corrupt")
    with pytest.raises(ValueError):
        tokens.decode(INGEST)
    now[0] += 11
    with pytest.raises(ValueError):
        tokens.decode(token)


def test_credential_types_and_rotated_secrets_are_not_interchangeable() -> None:
    tokens = AccessTokens(SecuritySettings(SIGNING, INGEST))
    token = tokens.issue(USER)
    assert tokens.accepts_ingestion_key(INGEST)
    assert not tokens.accepts_ingestion_key(token)
    assert not tokens.accepts_ingestion_key(INGEST + "wrong")
    rotated = AccessTokens(SecuritySettings(SIGNING + "rotated", INGEST))
    with pytest.raises(ValueError):
        rotated.decode(token)


def test_password_hashes_are_salted_and_legacy_accounts_remain_verifiable() -> None:
    first, second = hash_password("пароль-example"), hash_password("пароль-example")
    assert first != second
    assert verify_password("пароль-example", first)
    assert not verify_password("wrong", first)
    assert not verify_password(first, first)
    assert verify_password("legacy", "legacy")
    assert not verify_password("wrong", "legacy")


@pytest.mark.parametrize("value", ["pbkdf2_sha256$bad", "pbkdf2_sha256$999999999$00$00", "pbkdf2_sha256$1$00$00"])
def test_malformed_password_hashes_do_not_fall_back_to_plaintext(value: str) -> None:
    assert not verify_password(value, value)


@pytest.mark.parametrize(("stored", "accepted"), [
    (None, False), ("legacy-password", True), ("different-password", False),
    ("pbkdf2_sha256$bad", False), ("pbkdf2_sha256$1$00$00", False),
])
def test_login_checks_pad_unknown_legacy_and_malformed_accounts(monkeypatch, stored, accepted):
    from src.core import passwords

    original = passwords.hashlib.pbkdf2_hmac
    iterations = []

    def calculate(*args, **kwargs):
        iterations.append(args[3])
        return original(*args, **kwargs)

    monkeypatch.setattr(passwords.hashlib, "pbkdf2_hmac", calculate)
    assert verify_login_password("legacy-password", stored) is accepted
    assert iterations == [600000]
