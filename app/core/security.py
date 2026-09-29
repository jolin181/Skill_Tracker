"""
app/core/security.py
--------------------
Security utilities for the platform:
- Password hashing and verification (Argon2id via pwdlib), run in a small thread pool.
- JWT access token creation and decoding (PyJWT).
- Opaque refresh tokens (only their SHA-256 hash is stored).
- Fernet symmetric encryption for secret codes.

Password hashing is CPU-heavy (Argon2 takes tens of milliseconds and ~64 MB of RAM), so it runs
in a dedicated thread pool. Running it directly in an `async def` would freeze every other
request on the event loop while a hash is computed.

TODO: Add key rotation support for Fernet encryption.
"""

import asyncio
import hashlib
import secrets
import uuid
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from typing import Any, TypeVar

import jwt
from cryptography.fernet import Fernet
from pwdlib import PasswordHash

from app.core.config import settings
from app.utils.time_utils import utcnow

T = TypeVar("T")

# ── Password Hashing ──────────────────────────────────────────────────────────
# Argon2id with pwdlib's recommended parameters.
_password_hash = PasswordHash.recommended()

# Checked against when a login names an account that doesn't exist, so "no such user" and
# "wrong password" take the same time and can't be told apart by timing.
_DUMMY_HASH = _password_hash.hash("dummy-password-used-only-for-timing")

_hash_executor = ThreadPoolExecutor(max_workers=settings.password_hash_workers, thread_name_prefix="password-hash")


async def _in_hash_pool(func: Callable[..., T], *args: Any) -> T:
    return await asyncio.get_running_loop().run_in_executor(_hash_executor, func, *args)


async def hash_password(password: str) -> str:
    """Return an Argon2id hash of the given plain-text password."""
    return await _in_hash_pool(_password_hash.hash, password)


async def verify_password(password: str, password_hash: str) -> tuple[bool, str | None]:
    """Returns (is_valid, new_hash). new_hash is set when the stored hash uses outdated
    parameters and should be saved in its place."""
    return await _in_hash_pool(_password_hash.verify_and_update, password, password_hash)


async def burn_password_check(password: str) -> None:
    """Spend the same time as a real password check (see _DUMMY_HASH)."""
    await _in_hash_pool(_password_hash.verify, password, _DUMMY_HASH)


def generate_temporary_password() -> str:
    return secrets.token_urlsafe(12)  # 16 characters


# ── JWT (access tokens) ───────────────────────────────────────────────────────
ACCESS_TOKEN_TYPE = "access"


def create_access_token(*, user_id: int, roles: Iterable[str], token_version: int) -> tuple[str, int]:
    """Returns (token, lifetime in seconds).

    Claims: sub = user id, roles (for the frontend's routing only; the backend always checks the
    roles stored in the database), ver = the user's token_version (bumping it in the database
    revokes every token issued before), type, iat, exp, jti.
    """
    now = utcnow()
    lifetime = timedelta(minutes=settings.access_token_expire_minutes)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "roles": sorted(str(role) for role in roles),
        "ver": token_version,
        "type": ACCESS_TOKEN_TYPE,
        "iat": now,
        "exp": now + lifetime,
        "jti": uuid.uuid4().hex,
    }
    token = jwt.encode(payload, settings.secret_key.get_secret_value(), algorithm=settings.jwt_algorithm)
    return token, int(lifetime.total_seconds())


def decode_access_token(token: str) -> dict[str, Any]:
    """Checks the signature, expiry and token type.
    Raises jwt.ExpiredSignatureError or jwt.InvalidTokenError."""
    payload = jwt.decode(
        token,
        settings.secret_key.get_secret_value(),
        algorithms=[settings.jwt_algorithm],  # never trust the algorithm named inside the token
        options={"require": ["exp", "iat", "sub"]},
    )
    if payload.get("type") != ACCESS_TOKEN_TYPE:
        raise jwt.InvalidTokenError("Not an access token")
    return payload


# ── Refresh tokens (opaque) ───────────────────────────────────────────────────
def generate_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def hash_token(token: str) -> str:
    """The database stores only this hash, so a leaked table can't be used to log in.
    A fast hash is fine here (unlike passwords) because the token is a long random value."""
    return hashlib.sha256(token.encode()).hexdigest()


# ── Secret Code Encryption ────────────────────────────────────────────────────
_fernet = Fernet(settings.code_encryption_key.encode())


def encrypt_code(plain_code: str) -> str:
    """Encrypt a plain-text secret code. Returns base64-encoded ciphertext."""
    return _fernet.encrypt(plain_code.encode()).decode()


def decrypt_code(encrypted_code: str) -> str:
    """
    Decrypt a Fernet-encrypted secret code.
    Only callable in admin context — never expose to student endpoints.
    """
    return _fernet.decrypt(encrypted_code.encode()).decode()
