# Architecture Overview — Skill Leveling Platform

## System Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                          Client (Browser / Mobile)                  │
└──────────────────────────────┬──────────────────────────────────────┘
                               │ HTTPS
┌──────────────────────────────▼──────────────────────────────────────┐
│                         FastAPI Application                         │
│   ┌───────────┐  ┌─────────────┐  ┌──────────────┐  ┌──────────┐  │
│   │  auth/    │  │  domains/   │  │   exams/     │  │  slots/  │  │
│   │  users/   │  │  progress/  │  │   halls/     │  │  alloc/  │  │
│   │  attempts │  │  analytics/ │  │  ai_engine/  │  │  notif.  │  │
│   └───────────┘  └─────────────┘  └──────────────┘  └──────────┘  │
│                    app/core/  (config, db, security)                │
└──────────────────────────────┬──────────────────────────────────────┘
                               │ asyncpg
┌──────────────────────────────▼──────────────────────────────────────┐
│                    PostgreSQL 16                                     │
└─────────────────────────────────────────────────────────────────────┘
                               │ HTTPS (async)
┌──────────────────────────────▼──────────────────────────────────────┐
│               External LLM Provider (OpenAI / etc.)                 │
└─────────────────────────────────────────────────────────────────────┘
```

## Module Interaction Rules

- Modules communicate **only** through each other's `service.py` functions.
- No module may import another module's `models.py` or `router.py` directly.
- All cross-cutting concerns (auth, audit logging) live in `app/core/`.

## Key Flows

### Student Exam Flow
1. Student enrolls in a track → `progress/` creates `Enrollment`.
2. Student views level → `domains/` returns ordered topics.
3. Student books a slot → `slots/` checks eligibility via `progress/service`.
4. Admin runs allocation after cutoff → `allocation/service.run_allocation()`.
5. Hall incharge physically hands secret code to student.
6. Student enters code → `attempts/service.start_exam()` verifies + creates session.
7. Student answers questions → `attempts/service.submit_answer()`.
8. Student submits → `attempts/service.score_and_finish()` → result + progression.

### AI Question Generation Flow
1. Admin triggers generation for a topic.
2. `ai_engine/difficulty.py` calculates target difficulty from past `topic_result`.
3. `ai_engine/question_generator.py` calls `llm_client.py` with topic/subtopic text.
4. `ai_engine/question_validator.py` validates output structure.
5. Valid questions are persisted to `Question` / `QuestionOption`.

### Nightly Analytics Flow
- Scheduled job calls `analytics/service.refresh_all()`.
- Recomputes all summary tables and updates `dashboard_widget_cache`.

## Security Architecture

- JWT access tokens (short-lived) + refresh tokens (long-lived, stored in DB).
- Secret codes encrypted at rest with Fernet symmetric encryption.
- Every secret code reveal is written to `audit_log` via `core/audit.py`.
- Role-based access: `admin`, `student`, and four domain-owner roles (`fullstack_domain_owner`, `cyber_domain_owner`, `cloud_devops_domain_owner`, `ml_domain_owner`), read from `roles` / `user_roles` on every request. Each domain-owner role is limited to one track (`roles.track_id`).
- Access tokens are 15-minute JWTs; refresh tokens rotate on every use and live in an httpOnly cookie. Passwords are hashed with Argon2id.
