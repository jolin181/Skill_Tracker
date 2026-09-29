"""
app/core/integrity.py
---------------------
Turn database constraint violations into clear API errors.

The database is the final judge of uniqueness (two people registering the same email at the
same moment can't both succeed), so instead of "check, then insert" the services insert and
translate the violation into a 409 with a specific code.
"""

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError, BadRequest, Conflict

UNIQUE_VIOLATION = "23505"  # PostgreSQL SQLSTATE codes
FOREIGN_KEY_VIOLATION = "23503"

_EMAIL_TAKEN = ("EMAIL_TAKEN", "An account with this email already exists.")
_USERNAME_TAKEN = ("USERNAME_TAKEN", "This username is already taken.")

# PostgreSQL reports the constraint or unique index name; for SQLite the name is rebuilt as
# uq_<table>_<columns> from its error message, so both spellings are listed where they differ.
UNIQUE_CONSTRAINT_ERRORS: dict[str, tuple[str, str]] = {
    "ix_users_email": _EMAIL_TAKEN,
    "uq_users_email": _EMAIL_TAKEN,
    "ix_users_username": _USERNAME_TAKEN,
    "uq_users_username": _USERNAME_TAKEN,
    "uq_students_reg_num": ("REG_NUM_TAKEN", "This register number is already registered."),
    "uq_students_roll_number": ("ROLL_NUMBER_TAKEN", "This roll number is already registered."),
    "uq_students_user_id": ("STUDENT_PROFILE_EXISTS", "This user already has a student profile."),
    "uq_departments_code": ("DEPARTMENT_CODE_TAKEN", "A department with this code already exists."),
    "uq_domain_incharge_user_id_track_id": ("TRACK_ALREADY_ASSIGNED", "This user is already assigned to that track."),
    "uq_roles_track_id": ("TRACK_ALREADY_LINKED", "That track already belongs to another domain-owner role."),
}


def _violation(exc: IntegrityError) -> tuple[str | None, str | None]:
    """(SQLSTATE, constraint name) for PostgreSQL; the same, parsed from the message, for SQLite."""
    orig = exc.orig
    # asyncpg errors, as wrapped by SQLAlchemy, expose the SQLSTATE; the original asyncpg
    # exception (the __cause__) carries the constraint name.
    sqlstate = getattr(orig, "sqlstate", None) or getattr(orig, "pgcode", None)
    if sqlstate:
        constraint = getattr(orig.__cause__, "constraint_name", None) or getattr(
            getattr(orig, "diag", None), "constraint_name", None
        )
        return sqlstate, constraint

    # SQLite: "UNIQUE constraint failed: users.email, ..." or "FOREIGN KEY constraint failed"
    message = str(orig)
    marker = "UNIQUE constraint failed:"
    if marker in message:
        columns = [part.strip() for part in message.split(marker, 1)[1].split(",")]
        table = columns[0].split(".")[0]
        return UNIQUE_VIOLATION, f"uq_{table}_" + "_".join(column.split(".")[-1] for column in columns)
    if "FOREIGN KEY constraint failed" in message:
        return FOREIGN_KEY_VIOLATION, None
    return None, None


def error_from_integrity_error(exc: IntegrityError) -> AppError:
    sqlstate, constraint = _violation(exc)
    if sqlstate == UNIQUE_VIOLATION:
        code, message = UNIQUE_CONSTRAINT_ERRORS.get(
            constraint or "", ("ALREADY_EXISTS", "A record with these details already exists.")
        )
        return Conflict(code, message)
    if sqlstate == FOREIGN_KEY_VIOLATION:
        return BadRequest("RELATED_RECORD_NOT_FOUND", "A record this refers to does not exist.")
    return BadRequest("INVALID_DATA", "The data breaks a database rule.")


async def flush_or_conflict(db: AsyncSession) -> None:
    """Send pending changes to the database now, turning constraint violations into API errors."""
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise error_from_integrity_error(exc) from exc
