"""
app/modules/users/models.py
---------------------------
users, departments, academic_years, students and domain_incharge.

Columns that the initial migration created as nullable stay nullable in the database; the app
always fills them for new rows. Columns added for authentication are marked below.

Loading rules (important in async code, where a lazy load raises MissingGreenlet):
- user_roles is always loaded with the user (one extra indexed query, roles joined in).
- student and track_assignments are only loaded on request: use USER_DETAIL_OPTIONS.
  Reading them without it raises an error straight away instead of hiding a query.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Integer, SmallInteger, String, UniqueConstraint, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship, selectinload

from app.core.database import Base, UTCDateTime
from app.modules.auth.models import DOMAIN_OWNER_ROLES, RoleName, UserRole
from app.modules.domains.models import Track
from app.utils.time_utils import utcnow


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String, nullable=True, unique=True, index=True)  # stored lowercase
    username: Mapped[str | None] = mapped_column(String(50), unique=True, index=True)  # stored lowercase
    full_name: Mapped[str | None] = mapped_column(String(100))
    phone: Mapped[str | None] = mapped_column(String(15))
    password_hash: Mapped[str] = mapped_column(String, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    failed_login_count: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utcnow, onupdate=utcnow, server_default=func.now()
    )

    # ---- added for authentication ----
    # Every access token carries this number; incrementing it revokes all earlier tokens at once
    # (password change, deactivation, role change, "log out everywhere").
    token_version: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    # Set for accounts created by an admin with a temporary password.
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    locked_until: Mapped[datetime | None] = mapped_column(UTCDateTime())
    last_login_at: Mapped[datetime | None] = mapped_column(UTCDateTime())

    user_roles: Mapped[list[UserRole]] = relationship(cascade="all, delete-orphan", lazy="selectin")
    student: Mapped[Optional["Student"]] = relationship(back_populates="user", lazy="raise")
    track_assignments: Mapped[list["DomainIncharge"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        order_by="DomainIncharge.track_id",
        lazy="raise",
    )

    @property
    def role_names(self) -> list[str]:
        """Sorted role names, from user_roles joined to roles."""
        return sorted(link.role.name for link in self.user_roles)

    @property
    def role_set(self) -> frozenset[str]:
        return frozenset(link.role.name for link in self.user_roles)

    def has_any_role(self, *roles: RoleName) -> bool:
        return not self.role_set.isdisjoint(roles)

    @property
    def is_admin(self) -> bool:
        return RoleName.ADMIN in self.role_set

    @property
    def is_domain_owner(self) -> bool:
        return self.has_any_role(*DOMAIN_OWNER_ROLES)

    @property
    def owned_track_ids(self) -> list[int]:
        """Tracks this user may manage through their domain-owner roles (roles.track_id)."""
        return sorted(
            link.role.track_id
            for link in self.user_roles
            if link.role.track_id is not None and link.role.name in DOMAIN_OWNER_ROLES
        )

    def __repr__(self) -> str:
        return f"<User id={self.id} email={self.email!r}>"


class Department(Base):
    __tablename__ = "departments"
    __table_args__ = (UniqueConstraint("code", name="uq_departments_code"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=True)
    code: Mapped[str | None] = mapped_column(String(20))  # added: short code such as CSE


class AcademicYear(Base):
    __tablename__ = "academic_years"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    label: Mapped[str | None] = mapped_column(String)


class Student(Base):
    """Student-only details, one row per student user.

    `id` stays the primary key because other modules' tables (slot_bookings, attempts,
    enrollments, analytics) point at students.id.
    """

    __tablename__ = "students"
    __table_args__ = (
        UniqueConstraint("user_id", name="uq_students_user_id"),
        UniqueConstraint("reg_num", name="uq_students_reg_num"),
        UniqueConstraint("roll_number", name="uq_students_roll_number"),
        CheckConstraint("curr_sem BETWEEN 1 AND 10", name="ck_students_curr_sem_range"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=True)
    department_id: Mapped[int | None] = mapped_column(ForeignKey("departments.id"))
    academic_year_id: Mapped[int | None] = mapped_column(ForeignKey("academic_years.id"))
    roll_number: Mapped[str | None] = mapped_column(String)
    # ---- added for registration ----
    reg_num: Mapped[str | None] = mapped_column(String(20))  # university register number
    curr_sem: Mapped[int | None] = mapped_column(SmallInteger)  # 1-10; the year of study is derived
    foundation_year_completed: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false")
    )

    user: Mapped[User] = relationship(back_populates="student", lazy="raise")
    department: Mapped[Department | None] = relationship(lazy="joined")

    @property
    def year(self) -> int | None:
        """Year of study, derived from the semester (semesters 1-2 → year 1, 3-4 → year 2, ...)."""
        return None if self.curr_sem is None else (self.curr_sem + 1) // 2


class DomainIncharge(Base):
    """A domain owner's assignment to their track, with their employee id.

    Which tracks someone may manage comes from their roles (roles.track_id). An assignment here
    must be for one of those tracks, and is removed when the user stops holding that role.
    """

    __tablename__ = "domain_incharge"
    __table_args__ = (UniqueConstraint("user_id", "track_id", name="uq_domain_incharge_user_id_track_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=True)
    track_id: Mapped[int] = mapped_column(ForeignKey("tracks.id"), nullable=True)
    emp_id: Mapped[str | None] = mapped_column(String(30))  # added

    user: Mapped[User] = relationship(back_populates="track_assignments", lazy="raise")
    track: Mapped[Track] = relationship(lazy="joined")

    @property
    def track_name(self) -> str | None:
        return self.track.name


# Add these to a query when the response needs the student profile or track assignments.
USER_DETAIL_OPTIONS = (selectinload(User.student), selectinload(User.track_assignments))
