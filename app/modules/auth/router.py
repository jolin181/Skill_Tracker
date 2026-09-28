"""
app/modules/auth/router.py
--------------------------
Auth module router — public and protected auth endpoints.

Placeholder returns {"module": "auth", "status": "ok"}.

TODO: POST /register  — call service.register()
TODO: POST /login     — call service.login(), return TokenResponse
TODO: POST /refresh   — call service.rotate_refresh_token()
TODO: POST /logout    — revoke refresh token
"""

from fastapi import APIRouter

router = APIRouter()



