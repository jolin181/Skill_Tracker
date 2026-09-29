# Business Rules — Skill Leveling Platform

College students level up their skills by booking exams themselves.

- Students belong to a department and academic year, and enroll in tracks
  (domains). Each track has levels; each level has topics; each topic has
  subtopics. There are no PDFs anywhere — only topic/subtopic text.
- Each level's page shows only what's needed to attempt it; topics and
  subtopics carry sequence_no for ordering.
- A student has a maximum of 3 attempts per level (attempt.attempt_no).
  After 3 failed attempts the student is locked out of that track
  (enrollment.is_blocked = true).
- Roles come from the roles/user_roles tables: "admin", "student",
  "fullstack_domain_owner", "cyber_domain_owner", "cloud_devops_domain_owner"
  and "ml_domain_owner". Each domain-owner role is limited to one track
  (roles.track_id); domain_incharge records the owner's assignment to it.
- Admin creates an assessment (exam definition) for a level, with duration
  and status.
- Admin creates slots for an assessment (date, start_time, end_time,
  booking_cutoff). A slot is NOT tied to a hall at creation time.
- Admin creates halls (name, location, capacity) and links them to a slot.
- A student books a slot only (slot_booking), and gets an attempt_number.
  The student never picks or sees a hall.
- After booking_cutoff, an allocation process randomly assigns each booked
  student a hall and seat_no (allocation table), balanced by capacity.
- One secret_code is generated per student after allocation: one-time use,
  expires_at the end of the slot window, stored encrypted
  (code_encrypted). It is NEVER shown to the student — only admin can view
  or print it, and every reveal is written to audit_log.
- Admin can view hall-wise data (students + seats, codes hidden) and
  generate a printable per-hall sheet (with codes) to hand physically to a
  hall incharge — a real person, not a system user.
- The student enters the code in the hall to start an exam_session, which
  tracks started_at, expires_at, ended_at, last_heartbeat_at. Tab-switches
  and other integrity signals go into proctoring_event.
- An attempt records one try at a level (linked to slot_booking). Its
  answers go into attempt_answer, referencing question and
  question_option (question bank includes marks, difficulty, explanation).
- After submission, a result is computed (marks, percentage, verdict), with
  a topic_result breakdown per topic for skill-gap purposes.
- A progression_decision records whether the student advances, retries, or
  is blocked, based on the attempt and result.
- An AI engine generates questions for the question bank using only topic
  and subtopic text (name, description) plus a target difficulty chosen
  from the student's past per-topic accuracy in topic_result/difficulty_
  performance_summary (>80% => hard, 50-80% => medium, <50% => easy, first
  attempt => medium). Generated questions pass a validator before being
  stored in question/question_option.
- Nightly/periodic jobs (analytics_refresh_job) recompute summary tables:
  student_performance_summary, domain_performance_summary,
  semester_progress_summary, topic_gap_summary,
  difficulty_performance_summary, and cache dashboard widgets in
  dashboard_widget_cache.
- A student decides for themselves when to book the next slot; no fixed
  pace.
