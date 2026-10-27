"""Password hashing with compatibility for existing plaintext accounts."""

import hashlib
import hmac
import secrets


PREFIX = "pbkdf2_sha256$"
ITERATIONS = 600_000
# A precomputed, non-account hash pads rejected legacy/missing account checks.
DUMMY_PASSWORD_HASH = (
    "pbkdf2_sha256$600000$72bd8c40f949ce4f515561393882ebd6$"
    "2340c32ce647679a23cfb5031eeb8223d8b1ddbbc3805d82fbcfca2c32c8aedb"
)


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, ITERATIONS)
    return f"{PREFIX}{ITERATIONS}${salt.hex()}${digest.hex()}"


def is_hashed_password(value: str) -> bool:
    return value.startswith(PREFIX)


def verify_password(password: str, stored: str) -> bool:
    if not isinstance(stored, str):
        return False
    if not is_hashed_password(stored):
        return hmac.compare_digest(password.encode("utf-8"), stored.encode("utf-8"))
    parameters = _hash_parameters(stored)
    if parameters is None:
        return False
    iterations, salt, expected = parameters
    actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(actual, expected)


def _hash_parameters(stored: str) -> tuple[int, bytes, bytes] | None:
    try:
        _, count, salt_hex, expected_hex = stored.split("$")
        iterations = int(count)
        salt, expected = bytes.fromhex(salt_hex), bytes.fromhex(expected_hex)
        if not 100_000 <= iterations <= 2_000_000 or len(salt) != 16 or len(expected) != 32:
            return None
    except (TypeError, ValueError):
        return None
    return iterations, salt, expected


def verify_login_password(password: str, stored: str | None) -> bool:
    # Unknown users, legacy plaintext and malformed hashes also pay for one KDF.
    # Existing valid hashes use their own work factor. There is no extra KDF
    # for an ordinary login against the project's standard PBKDF2 hash.
    if not isinstance(stored, str) or not is_hashed_password(stored) or _hash_parameters(stored) is None:
        verify_password(password, DUMMY_PASSWORD_HASH)
    return isinstance(stored, str) and verify_password(password, stored)
