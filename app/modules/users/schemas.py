"""
app/modules/users/schemas.py
----------------------------
Validated field types, what the API returns about users, and the admin request bodies.
Password hashes and token data never leave the backend.

Note on field order: pydantic strips whitespace before checking length and pattern, but applies
to_lower/to_upper afterwards. That's why the patterns accept both cases.
"""

import re
from datetime import datetime
from typing import Annotated, Any, Generic, TypeVar

from pydantic import (
    AfterValidator,
    AliasChoices,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    EmailStr,
    Field,
    StringConstraints,
    model_validator,
)

from app.modules.auth.models import DOMAIN_OWNER_ROLES, STAFF_ROLES, RoleName

T = TypeVar("T")


# ------------------------------------------------------------------ field types


def _strip_phone_separators(value: object) -> object:
    return re.sub(r"[\s-]", "", value) if isinstance(value, str) else value


# Stored lowercase. No "@" allowed, so a login name containing "@" is always an email.
Username = Annotated[
    str,
    StringConstraints(strip_whitespace=True, to_lower=True, min_length=3, max_length=50, pattern=r"^[A-Za-z0-9_.-]+$"),
]
Email = Annotated[EmailStr, AfterValidator(str.lower)]
Password = Annotated[str, StringConstraints(min_length=8, max_length=128)]
FullName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
Phone = Annotated[str, BeforeValidator(_strip_phone_separators), StringConstraints(pattern=r"^\+?[0-9]{10,15}$")]
RegNum = Annotated[
    str,
    StringConstraints(strip_whitespace=True, to_upper=True, min_length=4, max_length=20, pattern=r"^[A-Za-z0-9]+$"),
]
RollNumber = Annotated[
    str,
    StringConstraints(strip_whitespace=True, to_upper=True, min_length=1, max_length=20, pattern=r"^[A-Za-z0-9/-]+$"),
]
Semester = Annotated[int, Field(ge=1, le=10, description="Current semester, 1-10 (the year of study is derived)")]
EmpId = Annotated[str, StringConstraints(strip_whitespace=True, to_upper=True, min_length=1, max_length=30)]


# ------------------------------------------------------------------ shared


class ORMModel(BaseModel):
    """Base for response models that are built from SQLAlchemy objects."""

    model_config = ConfigDict(from_attributes=True)


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int


# ------------------------------------------------------------------ responses


class DepartmentOut(ORMModel):
    id: int
    code: str | None
    name: str | None


class StudentProfileOut(ORMModel):
    id: int
    reg_num: str | None
    roll_number: str | None
    department: DepartmentOut | None
    academic_year_id: int | None
    curr_sem: int | None
    year: int | None = Field(description="Year of study, derived from curr_sem")
    foundation_year_completed: bool


class TrackAssignmentOut(ORMModel):
    track_id: int
    track_name: str | None
    emp_id: str | None


class UserOut(ORMModel):
    id: int
    username: str | None
    email: str | None
    full_name: str | None
    phone: str | None
    # Read from User.role_names (user_roles joined to roles); there is no role column on users.
    roles: list[str] = Field(validation_alias=AliasChoices("role_names", "roles"))
    owned_track_ids: list[int] = Field(description="Tracks this user may manage through their domain-owner roles")
    is_active: bool
    must_change_password: bool
    created_at: datetime
    last_login_at: datetime | None


class UserDetailOut(UserOut):
    """UserOut plus `student` for students and `track_assignments` for domain owners."""

    student: StudentProfileOut | None = None
    track_assignments: list[TrackAssignmentOut] = []


class AdminUserOut(UserDetailOut):
    failed_login_count: int
    locked_until: datetime | None


class RoleOut(ORMModel):
    id: int
    name: str
    track_id: int | None


class AuditLogOut(ORMModel):
    id: int
    action: str | None
    actor_user_id: int | None
    target_user_id: int | None
    details: dict[str, Any] | None
    ip_address: str | None
    created_at: datetime | None


# ------------------------------------------------------------------ admin requests


def _reject_explicit_nulls(model: BaseModel, *fields: str) -> None:
    """PATCH bodies: leaving a field out means "don't change it"; null is only allowed
    for fields that may really be empty."""
    for name in fields:
        if name in model.model_fields_set and getattr(model, name) is None:
            raise ValueError(f"{name} can't be null")


def _check_staff_roles(roles: list[RoleName]) -> list[RoleName]:
    if not roles:
        raise ValueError("Give at least one role.")
    if RoleName.STUDENT in roles:
        raise ValueError("Students register themselves at /auth/register; admins create staff accounts.")
    if not set(roles) <= STAFF_ROLES:
        raise ValueError("Unknown role.")
    return sorted(set(roles))


StaffRoles = Annotated[list[RoleName], AfterValidator(_check_staff_roles)]


class AdminCreateUserRequest(BaseModel):
    username: Username
    email: Email
    full_name: FullName
    phone: Phone | None = None
    roles: StaffRoles = Field(description="One or more of: admin and the four *_domain_owner roles")
    password: Password | None = Field(default=None, description="Leave out to generate a temporary password")
    emp_id: EmpId | None = None
    track_ids: list[int] = Field(default_factory=list, description="Tracks to assign (domain owners only)")

    @model_validator(mode="after")
    def check_tracks(self) -> "AdminCreateUserRequest":
        if self.track_ids and DOMAIN_OWNER_ROLES.isdisjoint(self.roles):
            raise ValueError("track_ids can only be given to domain owners.")
        return self


class AdminCreateUserResponse(BaseModel):
    user: AdminUserOut
    temporary_password: str | None = Field(
        default=None,
        description="Shown only once. Give it to the user; they must change it when they first log in.",
    )


class AdminUpdateUserRequest(BaseModel):
    full_name: FullName | None = None
    email: Email | None = None
    phone: Phone | None = None
    roles: StaffRoles | None = Field(default=None, description="Replaces the user's roles (staff accounts only)")

    @model_validator(mode="after")
    def check_nulls(self) -> "AdminUpdateUserRequest":
        _reject_explicit_nulls(self, "full_name", "email", "roles")
        return self


class StudentProfileUpdateRequest(BaseModel):
    reg_num: RegNum | None = None
    roll_number: RollNumber | None = None
    department_id: int | None = Field(default=None, gt=0)
    academic_year_id: int | None = Field(default=None, gt=0)
    curr_sem: Semester | None = None
    foundation_year_completed: bool | None = None

    @model_validator(mode="after")
    def check_nulls(self) -> "StudentProfileUpdateRequest":
        _reject_explicit_nulls(self, "reg_num", "department_id", "curr_sem", "foundation_year_completed")
        return self


class TrackAssignRequest(BaseModel):
    track_id: int = Field(gt=0)
    emp_id: EmpId | None = None


class TemporaryPasswordResponse(BaseModel):
    temporary_password: str


class RoleUpdateRequest(BaseModel):
    track_id: int | None = Field(gt=0, description="Track this domain-owner role manages; null unlinks it")


class DepartmentCreate(BaseModel):
    code: Annotated[str, StringConstraints(strip_whitespace=True, to_upper=True, min_length=1, max_length=20)]
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
