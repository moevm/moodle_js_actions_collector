"""Password hashing with compatibility for existing plaintext accounts."""

import hashlib
import hmac
import secrets


PREFIX = "pbkdf2_sha256$"
ITERATIONS = 600_000


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
    try:
        _, count, salt_hex, expected_hex = stored.split("$")
        iterations = int(count)
        salt, expected = bytes.fromhex(salt_hex), bytes.fromhex(expected_hex)
        if not 100_000 <= iterations <= 2_000_000 or len(salt) != 16 or len(expected) != 32:
            return False
    except (TypeError, ValueError):
        return False
    actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(actual, expected)
