"""
app/modules/auth/schemas.py
---------------------------
Request/response bodies for /auth.
"""

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.modules.users.schemas import (
    Email,
    FullName,
    Password,
    Phone,
    RegNum,
    RollNumber,
    Semester,
    UserOut,
    Username,
)


class RegisterRequest(BaseModel):
    """Student self-registration. The account always gets the `student` role."""

    username: Username
    email: Email
    full_name: FullName
    phone: Phone | None = None
    password: Password
    reg_num: RegNum
    roll_number: RollNumber | None = None
    department_id: int = Field(gt=0)
    academic_year_id: int | None = Field(default=None, gt=0)
    curr_sem: Semester

    @model_validator(mode="after")
    def check_password(self) -> "RegisterRequest":
        if self.password.lower() in {self.username, self.email, self.reg_num.lower()}:
            raise ValueError("The password can't be your username, email or register number.")
        return self


class TokenResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int = Field(description="Access token lifetime in seconds")
    user: UserOut


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: Password

    @model_validator(mode="after")
    def check_different(self) -> "ChangePasswordRequest":
        if self.new_password == self.current_password:
            raise ValueError("The new password must be different from the current one.")
        return self


class UpdateMeRequest(BaseModel):
    """Fields users may change about themselves. Everything else is changed by an admin."""

    phone: Phone | None = None
