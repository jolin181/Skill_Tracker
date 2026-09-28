"""
app/modules/secret_code/schemas.py
------------------------------------
Pydantic v2 schemas for the secret_code module.

SECURITY RULES ENFORCED BY SCHEMA DESIGN:
  - `SecretCodeStatusResponse`  — safe for any admin view; contains NO plaintext code.
  - `SecretCodeRevealResponse`  — contains plaintext code; used ONLY by the admin
    reveal endpoint and hall_sheets print endpoint.  Never reused for student paths.

Student-facing routes must NEVER use either schema — this module has no student routes.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class SecretCodeStatusResponse(BaseModel):
    """
    Code metadata without the plaintext — safe to return or log.
    Used by GET /secret-code/{secret_code_id}/status.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    allocation_id: uuid.UUID
    is_used: bool
    created_at: datetime
    expires_at: datetime
    used_at: datetime | None


class SecretCodeRevealResponse(BaseModel):
    """
    Includes the decrypted plaintext code.
    ONLY for admin reveal endpoint.  Every access is written to audit_log.
    Must NEVER be returned from a student-facing route.
    """

   
