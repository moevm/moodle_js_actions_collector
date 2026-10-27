"""Short-lived UI access tokens and a separate, write-only collection key."""

from __future__ import annotations

import hashlib
import hmac
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from itsdangerous import BadData, URLSafeTimedSerializer


@dataclass(frozen=True, slots=True)
class SecuritySettings:
    signing_secret: str
    ingestion_key: str
    token_ttl_seconds: int = 43200

    def __post_init__(self) -> None:
        for name, value in [("COLLECTOR_AUTH_SECRET", self.signing_secret),
                            ("COLLECTOR_INGEST_KEY", self.ingestion_key)]:
            if len(value) < 32:
                raise ValueError(f"{name} must contain at least 32 characters; run scripts/init-auth-secrets.py")
        if self.signing_secret == self.ingestion_key:
            raise ValueError("COLLECTOR_AUTH_SECRET and COLLECTOR_INGEST_KEY must be different")
        if re.fullmatch(r"[A-Za-z0-9_-]{32,256}", self.ingestion_key) is None:
            raise ValueError("COLLECTOR_INGEST_KEY must be a URL-safe ASCII key; run scripts/init-auth-secrets.py")
        if self.token_ttl_seconds <= 0:
            raise ValueError("COLLECTOR_ACCESS_TOKEN_TTL_SECONDS must be positive")

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> SecuritySettings:
        values = os.environ if environ is None else environ
        try:
            ttl = int(values.get("COLLECTOR_ACCESS_TOKEN_TTL_SECONDS", "43200"))
        except ValueError as error:
            raise ValueError("COLLECTOR_ACCESS_TOKEN_TTL_SECONDS must be an integer") from error
        return cls(values.get("COLLECTOR_AUTH_SECRET", ""), values.get("COLLECTOR_INGEST_KEY", ""), ttl)


@dataclass(frozen=True, slots=True)
class TokenClaims:
    subject: str
    password_version: str


class AccessTokens:
    def __init__(self, settings: SecuritySettings) -> None:
        self.settings = settings
        self.serializer = URLSafeTimedSerializer(
            settings.signing_secret, salt="collector-ui-access-v1",
            signer_kwargs={"digest_method": hashlib.sha256},
        )

    def _password_version(self, user: Mapping[str, Any]) -> str:
        # A keyed digest cannot be used to guess the password offline from the
        # readable token payload. Changing the stored password revokes tokens.
        value = f"{user['_id']}\0{user['password']}".encode("utf-8")
        return hmac.new(self.settings.signing_secret.encode("utf-8"), value, hashlib.sha256).hexdigest()

    def issue(self, user: Mapping[str, Any]) -> str:
        payload = {"sub": str(user["_id"]), "v": self._password_version(user)}
        return "ui." + self.serializer.dumps(payload)

    def decode(self, token: str) -> TokenClaims:
        if not token.startswith("ui.") or len(token) > 4096:
            raise ValueError("Invalid access token")
        try:
            payload = self.serializer.loads(token[3:], max_age=self.settings.token_ttl_seconds)
        except BadData as error:
            raise ValueError("Invalid or expired access token") from error
        if not isinstance(payload, dict):
            raise ValueError("Invalid access token")
        subject, version = payload.get("sub"), payload.get("v")
        if not isinstance(subject, str) or re.fullmatch(r"[a-fA-F0-9]{24}", subject) is None:
            raise ValueError("Invalid access token subject")
        if not isinstance(version, str) or re.fullmatch(r"[a-f0-9]{64}", version) is None:
            raise ValueError("Invalid access token version")
        return TokenClaims(subject, version)

    def matches_user(self, claims: TokenClaims, user: Mapping[str, Any]) -> bool:
        return hmac.compare_digest(claims.password_version, self._password_version(user))

    def accepts_ingestion_key(self, value: str) -> bool:
        return hmac.compare_digest(value.encode("utf-8"), self.settings.ingestion_key.encode("utf-8"))
