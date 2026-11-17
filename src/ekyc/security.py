"""Authentication helpers and PII masking (Phase 7).

- Passwords: argon2id via argon2-cffi (the maintained reference implementation; passlib is unmaintained).
- Login tokens: JWT (HS256, PyJWT) with the user id (sub), role (CUSTOMER | OFFICER) and an expiry (exp).
- Logs never contain personal data: mask_name / mask_dob / mask_document_number, and RedactTokens removes
  ?token=... from access-log lines (the SSE endpoint accepts the token in the URL, since browsers' EventSource
  cannot send headers).
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

ROLES = ("CUSTOMER", "OFFICER")
_hasher = PasswordHasher()  # argon2id with the library's recommended cost parameters


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def create_token(user_id: str, role: str, secret: str, minutes: float = 30.0, now: datetime | None = None) -> str:
    issued = now or datetime.now(timezone.utc)
    claims = {"sub": user_id, "role": role, "iat": issued, "exp": issued + timedelta(minutes=minutes)}
    return jwt.encode(claims, secret, algorithm="HS256")


def decode_token(token: str, secret: str) -> dict:
    """The token's claims; raises jwt.InvalidTokenError (expired, bad signature, malformed)."""
    claims = jwt.decode(token, secret, algorithms=["HS256"], options={"require": ["sub", "role", "exp"]})
    if claims["role"] not in ROLES:
        raise jwt.InvalidTokenError("unknown role")
    return claims


# ---------------------------------------------------------------- PII masking

def mask_name(name: str | None) -> str:
    """'Krsto Velimirović' -> 'K*** V***'."""
    return " ".join(f"{part[0]}***" for part in (name or "").split()) or "***"


def mask_dob(_: object = None) -> str:
    return "****-**-**"


def mask_document_number(number: str | None) -> str:
    """'AK6995574' -> '*******74' (the last two characters only)."""
    number = number or ""
    return "*" * max(0, len(number) - 2) + number[-2:]


class RedactTokens(logging.Filter):
    """Removes token=... from log messages (uvicorn's access log prints the full URL)."""
    pattern = re.compile(r"(token=)[^&\s\"]+")

    def filter(self, record: logging.LogRecord) -> bool:
        if record.args:
            record.args = tuple(self.pattern.sub(r"\1***", a) if isinstance(a, str) else a for a in record.args)
        record.msg = self.pattern.sub(r"\1***", str(record.msg))
        return True
