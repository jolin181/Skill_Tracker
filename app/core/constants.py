"""
app/core/constants.py
---------------------
Application-wide constants and enumerations.

Rules:
- Roles are the six names in the roles table (see app.modules.auth.models.RoleName): "admin",
  "student" and four domain-owner roles. Each domain-owner role is limited to one track
  (roles.track_id); domain_incharge records a domain owner's assignment to that track.
- MAX_ATTEMPTS = 3: a student may attempt a level at most 3 times before being
  locked out (enrollment.is_blocked = true).
- Difficulty levels mirror the VARCHAR values stored in the question table.
- Status enums match the VARCHAR status columns in each table exactly.

TODO: Replace plain strings with database-backed lookups where appropriate.
TODO: Move status enums to individual module constants if they diverge.
"""

# ── Roles ─────────────────────────────────────────────────────────────────────
ROLE_STUDENT = "student"
ROLE_ADMIN = "admin"
ROLE_FULLSTACK_DOMAIN_OWNER = "fullstack_domain_owner"
ROLE_CYBER_DOMAIN_OWNER = "cyber_domain_owner"
ROLE_CLOUD_DEVOPS_DOMAIN_OWNER = "cloud_devops_domain_owner"
ROLE_ML_DOMAIN_OWNER = "ml_domain_owner"

# ── Attempt Limits ────────────────────────────────────────────────────────────
MAX_ATTEMPTS = 3  # Maximum attempts per level before enrollment.is_blocked = true

# ── Difficulty Levels ─────────────────────────────────────────────────────────
DIFFICULTY_EASY = "easy"
DIFFICULTY_MEDIUM = "medium"
DIFFICULTY_HARD = "hard"
DIFFICULTY_CHOICES = (DIFFICULTY_EASY, DIFFICULTY_MEDIUM, DIFFICULTY_HARD)

# AI difficulty thresholds (accuracy from topic_result / difficulty_performance_summary):
# accuracy > 80%          => generate HARD questions
# 50% <= accuracy <= 80%  => generate MEDIUM questions
# accuracy < 50%          => generate EASY questions
# first attempt (no data) => default to MEDIUM
DIFFICULTY_THRESHOLD_HARD = 0.80
DIFFICULTY_THRESHOLD_MEDIUM = 0.50

# ── Assessment Status ─────────────────────────────────────────────────────────
ASSESSMENT_STATUS_DRAFT = "draft"
ASSESSMENT_STATUS_ACTIVE = "active"
ASSESSMENT_STATUS_ARCHIVED = "archived"

# ── Slot Status ───────────────────────────────────────────────────────────────
SLOT_STATUS_OPEN = "open"
SLOT_STATUS_CLOSED = "closed"
SLOT_STATUS_ALLOCATED = "allocated"
SLOT_STATUS_COMPLETED = "completed"

# ── Slot Booking Status ───────────────────────────────────────────────────────
BOOKING_STATUS_CONFIRMED = "confirmed"
BOOKING_STATUS_CANCELLED = "cancelled"
BOOKING_STATUS_ABSENT = "absent"

# ── Attempt Status ────────────────────────────────────────────────────────────
ATTEMPT_STATUS_IN_PROGRESS = "in_progress"
ATTEMPT_STATUS_SUBMITTED = "submitted"
ATTEMPT_STATUS_EXPIRED = "expired"

# ── Level Progress Status ─────────────────────────────────────────────────────
LEVEL_STATUS_LOCKED = "locked"
LEVEL_STATUS_UNLOCKED = "unlocked"
LEVEL_STATUS_PASSED = "passed"
LEVEL_STATUS_FAILED = "failed"

# ── Progression Decision Choices ──────────────────────────────────────────────
DECISION_ADVANCE = "advance"
DECISION_RETRY = "retry"
DECISION_BLOCKED = "blocked"

# ── Result Verdict ────────────────────────────────────────────────────────────
VERDICT_PASS = "pass"
VERDICT_FAIL = "fail"

# ── Analytics Job Status ──────────────────────────────────────────────────────
JOB_STATUS_RUNNING = "running"
JOB_STATUS_SUCCESS = "success"
JOB_STATUS_FAILED = "failed"
