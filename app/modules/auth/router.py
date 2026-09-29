"""
app/modules/auth/router.py
--------------------------
/auth: register, login, refresh, logout, own profile and password.
"""

from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, Response, status
from fastapi.security import OAuth2PasswordRequestForm

from app.core.config import settings
from app.core.dependencies import AuthenticatedUser, Client, CurrentUser, DbSession, verify_request_origin
from app.modules.auth import service as auth_service
from app.modules.auth.schemas import ChangePasswordRequest, RegisterRequest, TokenResponse, UpdateMeRequest
from app.modules.auth.service import IssuedTokens
from app.modules.users.schemas import UserDetailOut, UserOut

router = APIRouter(prefix="/auth", tags=["Auth"])

# The browser sends this cookie by itself; it's hidden from the docs because Swagger UI can't set it.
RefreshCookie = Annotated[str | None, Cookie(alias=settings.refresh_cookie_name, include_in_schema=False)]


def _send_tokens(response: Response, tokens: IssuedTokens) -> TokenResponse:
    """Access token in the JSON body (the frontend keeps it in memory);
    refresh token in an httpOnly cookie (JavaScript can't read it, so XSS can't steal it)."""
    response.set_cookie(
        key=settings.refresh_cookie_name,
        value=tokens.refresh_token,
        max_age=settings.refresh_token_expire_days * 24 * 60 * 60,
        path=settings.refresh_cookie_path,
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
    )
    return TokenResponse(
        access_token=tokens.access_token,
        expires_in=tokens.expires_in,
        user=UserOut.model_validate(tokens.user),
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(
        key=settings.refresh_cookie_name,
        path=settings.refresh_cookie_path,
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
    )


@router.post("/register", response_model=UserDetailOut, status_code=status.HTTP_201_CREATED)
async def register(data: RegisterRequest, db: DbSession, client: Client) -> UserDetailOut:
    """Student self-registration (always gets the `student` role). Staff accounts are created by an admin."""
    user = await auth_service.register_student(db, data, client)
    return UserDetailOut.model_validate(user)


@router.post("/login", response_model=TokenResponse)
async def login(
    form: Annotated[OAuth2PasswordRequestForm, Depends()],
    response: Response,
    db: DbSession,
    client: Client,
) -> TokenResponse:
    """OAuth2 password login: form fields `username` (username or email) and `password`.

    Returns a short-lived access token and sets the refresh token cookie.
    If `user.must_change_password` is true, send the user to the change-password screen.
    """
    tokens = await auth_service.authenticate(db, form.username, form.password, client)
    return _send_tokens(response, tokens)


@router.post("/refresh", response_model=TokenResponse, dependencies=[Depends(verify_request_origin)])
async def refresh(
    response: Response, db: DbSession, client: Client, refresh_token: RefreshCookie = None
) -> TokenResponse:
    """Get a new access token using the refresh cookie (the cookie is replaced each time).
    Call it when an API call returns 401, and when the app starts to restore the session."""
    tokens = await auth_service.rotate_refresh_token(db, refresh_token, client)
    return _send_tokens(response, tokens)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(verify_request_origin)])
async def logout(response: Response, db: DbSession, refresh_token: RefreshCookie = None) -> None:
    """Log out this browser. Works even when the access token has already expired."""
    await auth_service.logout(db, refresh_token)
    _clear_refresh_cookie(response)


@router.post("/logout-all", status_code=status.HTTP_204_NO_CONTENT)
async def logout_all(user: AuthenticatedUser, response: Response, db: DbSession, client: Client) -> None:
    """Log out on every device; all existing access tokens stop working immediately."""
    await auth_service.logout_everywhere(db, user, client)
    _clear_refresh_cookie(response)


@router.get("/me", response_model=UserDetailOut)
async def read_me(user: AuthenticatedUser, db: DbSession) -> UserDetailOut:
    """The logged-in user with their roles, plus student details or assigned tracks."""
    return UserDetailOut.model_validate(await auth_service.get_user_with_details(db, user.id))


@router.patch("/me", response_model=UserDetailOut)
async def update_me(data: UpdateMeRequest, user: CurrentUser, db: DbSession, client: Client) -> UserDetailOut:
    """Update your own contact details. Other fields are changed by an admin."""
    return UserDetailOut.model_validate(await auth_service.update_own_profile(db, user, data, client))


@router.post("/change-password", response_model=TokenResponse)
async def change_password(
    data: ChangePasswordRequest,
    user: AuthenticatedUser,
    response: Response,
    db: DbSession,
    client: Client,
) -> TokenResponse:
    """Change your password. Ends every other session and returns new tokens for this one."""
    tokens = await auth_service.change_password(db, user, data.current_password, data.new_password, client)
    return _send_tokens(response, tokens)
