# Users Module

Accounts, student profiles, departments, academic years and domain-owner assignments, plus the admin endpoints that manage them.

## Tables
- `users` holds platform accounts. Roles live in `roles` / `user_roles` (auth module).
- `students` links a `user` to a `department` and `academic_year`, with register number, roll number and current semester. The year of study is derived from `curr_sem`.
- `departments` is the department lookup (`code` + `name`).
- `academic_years` holds academic year labels.
- `domain_incharge` records a domain owner's assignment (with `emp_id`) to the track of their role.

## Key Rules
- Only admins reach `/users`, `/roles` and `/audit-logs`. `GET /departments` is public (the registration form needs it).
- A student account can't become a staff account, and the reverse isn't possible either.
- A domain owner can only be assigned the track linked to their role (`400 TRACK_NOT_IN_ROLE`).
- Changing a user's roles logs them out everywhere and removes assignments that no longer fit.
- Users are deactivated, never deleted, because attempts and results still point at them.

## Endpoints (`/api/v1`)
| Method | Path | Description |
|--------|------|-------------|
| GET / POST | /users | List (filter by role, department, semester, search) / create staff account |
| GET / PATCH | /users/{id} | View / change name, email, phone, roles |
| PATCH | /users/{id}/student-profile | Change department, academic year, reg/roll number, semester |
| POST | /users/{id}/deactivate, /activate, /reset-password, /unlock | Account actions |
| POST / DELETE | /users/{id}/tracks[/{track_id}] | Assign / unassign a domain owner's track |
| GET / PATCH | /roles[/{id}] | List roles / link a domain-owner role to its track |
| GET | /audit-logs | Audit log, newest first |
| GET / POST | /departments | List (public) / create (admin) |
