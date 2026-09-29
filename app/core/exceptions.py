"""
app/core/exceptions.py
-----------------------
Custom exception classes and global FastAPI exception handlers.

Two families live here:
- SkillLevelingException and its subclasses (NotFoundError, ConflictError, ...), used by the
  domain modules. Responses: {"detail": ..., "status_code": ...}.
- AppError and its subclasses (BadRequest, Unauthorized, ...), used by auth and users. Each carries
  a machine-readable `code`; responses: {"detail": ..., "code": ...}. The frontend should branch
  on `code` (e.g. TOKEN_EXPIRED, PASSWORD_CHANGE_REQUIRED), never on the message text.

register_exception_handlers(app) installs the handlers for both (called from main.py).

TODO: Add Sentry / observability integration in the handler callbacks.
"""

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


# ── Base Domain Exceptions ────────────────────────────────────────────────────

class SkillLevelingException(Exception):
    """Base exception for all application-specific errors."""

    def __init__(self, detail: str, status_code: int = status.HTTP_400_BAD_REQUEST) -> None:
        self.detail = detail
        self.status_code = status_code
        super().__init__(detail)


class NotFoundError(SkillLevelingException):
    """Raised when a requested resource does not exist."""

    def __init__(self, detail: str = "Resource not found.") -> None:
        super().__init__(detail, status_code=status.HTTP_404_NOT_FOUND)


class ForbiddenError(SkillLevelingException):
    """Raised when the current user lacks permission for an action."""

    def __init__(self, detail: str = "Forbidden.") -> None:
        super().__init__(detail, status_code=status.HTTP_403_FORBIDDEN)


class ConflictError(SkillLevelingException):
    """Raised on duplicate or conflicting state (e.g. double booking)."""

    def __init__(self, detail: str = "Conflict.") -> None:
        super().__init__(detail, status_code=status.HTTP_409_CONFLICT)


class ValidationError(SkillLevelingException):
    """Raised on business-rule validation failures."""

    def __init__(self, detail: str = "Validation error.") -> None:
        super().__init__(detail, status_code=status.HTTP_422_UNPROCESSABLE_ENTITY)


# ── Coded errors (auth / users) ───────────────────────────────────────────────

class AppError(Exception):
    status_code: int = 400

    def __init__(self, code: str, message: str, *, headers: dict[str, str] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.headers = headers


class BadRequest(AppError):
    status_code = 400


class Unauthorized(AppError):
    """401: not logged in, or the token is missing, expired or invalid."""

    status_code = 401

    def __init__(self, code: str, message: str) -> None:
        super().__init__(code, message, headers={"WWW-Authenticate": "Bearer"})


class Forbidden(AppError):
    """403: logged in, but not allowed to do this."""

    status_code = 403


class NotFound(AppError):
    status_code = 404


class Conflict(AppError):
    status_code = 409


class TooManyRequests(AppError):
    status_code = 429


# ── Exception Handlers ────────────────────────────────────────────────────────

async def skill_leveling_exception_handler(
    request: Request, exc: SkillLevelingException
) -> JSONResponse:
    """Convert SkillLevelingException to a structured JSON error response."""
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail, "status_code": exc.status_code},
    )


async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """Wrap FastAPI's HTTPException in the standard error envelope."""
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail, "status_code": exc.status_code, "code": f"HTTP_{exc.status_code}"},
        headers=getattr(exc, "headers", None),
    )


async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.message, "code": exc.code},
        headers=exc.headers,
    )


async def request_validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={"detail": jsonable_encoder(exc.errors()), "code": "VALIDATION_ERROR"},
    )


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(SkillLevelingException, skill_leveling_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(AppError, app_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, request_validation_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)  # type: ignore[arg-type]
