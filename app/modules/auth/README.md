# Auth Module

Async registration, login, JWT access tokens, refresh-token rotation, logout, password changes and role checks.

## Tables
- `users` has **no role column**.
- `roles` is a lookup table with six rows: `admin`, `student`, `fullstack_domain_owner`, `cyber_domain_owner`, `cloud_devops_domain_owner`, `ml_domain_owner`.
  - `roles.track_id` links each domain-owner role to the one track its holders manage.
- `user_roles` is the many-to-many join, unique on (user_id, role_id). A user's roles = `user_roles` joined to `roles`.
- `refresh_tokens` stores only a SHA-256 hash of each token, with `family_id` = one login session.

See `docs/db_schema.md` for all columns.

## Key Rules
- **Roles come from the database on every request,** never from the JWT. The token's `roles` claim is only for frontend routing. So deactivating a user or changing their roles takes effect on their next request.
- **Who creates which accounts:** students register themselves and always get `student`. Staff accounts (admin and/or domain-owner roles) are created by an admin with a temporary password, which must be changed at first login.
- **Domain owners are limited to their role's track** (`roles.track_id`). Admins manage every track. Link a role to its track with `PATCH /api/v1/roles/{id}`; until then its holders manage no track.
- **Lockout:** 5 wrong passwords lock the account for 10 minutes (HTTP 429 with `Retry-After`). It's temporary, never permanent.
- **Refresh tokens rotate on every use.** Reusing an old one ends that whole session, except within a 10-second grace window for two tabs refreshing at once.
- **Audit log:** every change writes to `audit_log` in the same transaction.

## Using it from another module
The existing dict dependencies are unchanged:
```python
from app.core.dependencies import get_current_user, require_admin, require_student

async def route(current_admin: dict = Depends(require_admin)):
    current_admin["id"], current_admin["roles"], current_admin["user"]
```
Typed dependencies for new code:
```python
from app.core.dependencies import CurrentUser, AdminUser, TrackManager, managed_track_ids, require_roles
from app.modules.auth.models import RoleName

@router.post("/tracks/{track_id}/levels")
async def create_level(track_id: int, user: TrackManager): ...      # admin, or the role linked to this track

@router.get("/ml/reports", dependencies=[Depends(require_roles(RoleName.ML_DOMAIN_OWNER, RoleName.ADMIN))])
async def ml_reports(): ...

ids = managed_track_ids(user)   # None = all tracks (admin); otherwise filter queries with Track.id.in_(ids)
```
`DomainOwnerOrAdmin` only checks "is some domain owner". Any route that touches one track's data must use `TrackManager` or `managed_track_ids`.

## Endpoints (`/api/v1/auth`)
| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | /register | public | Student self-registration |
| POST | /login | public | OAuth2 form (`username` = username or email). Returns the access token and sets the refresh cookie. |
| POST | /refresh | refresh cookie | Rotate the refresh token, get a new access token |
| POST | /logout | refresh cookie | End this browser's session |
| POST | /logout-all | bearer | End every session |
| GET / PATCH | /me | bearer | Own profile (PATCH: phone only) |
| POST | /change-password | bearer | Change password, end other sessions |

Errors look like `{"detail": "...", "code": "TOKEN_EXPIRED"}`. The frontend should branch on `code`.

## Async notes
- **Password hashing** (Argon2id) runs in a small thread pool (`PASSWORD_HASH_WORKERS`), so it never blocks the event loop.
- **No lazy loading.** Async SQLAlchemy can't lazy-load: `User.student` and `User.track_assignments` use `lazy="raise"`. Load them with `USER_DETAIL_OPTIONS` or `get_user_with_details()`.
- **Timestamps** are TIMESTAMPTZ in UTC. Use `app.utils.time_utils.utcnow()`.

## Tests
```bash
pytest app/modules/auth app/modules/users
```
The tests use a fresh SQLite file per test. Set `TEST_DATABASE_URL` (a database name ending in `_test`) to run them on PostgreSQL.
