"""
Simple script to create Skill Gap tables in SQLite database.
This bypasses Alembic migrations which are configured for PostgreSQL.

Usage:
    python create_skill_gap_tables.py
"""

import sqlite3

# Connect to the database
conn = sqlite3.connect('skill_leveling_db.db')
cursor = conn.cursor()

print("Creating Skill Gap Analysis tables...")

# Create skill_gap_reports table
cursor.execute("""
CREATE TABLE IF NOT EXISTS skill_gap_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER NOT NULL,
    attempt_id INTEGER NOT NULL UNIQUE,
    level_id INTEGER NOT NULL,
    created_at DATETIME NOT NULL,
    summary TEXT,
    overall_performance TEXT,
    recommendations TEXT,
    study_plan TEXT,
    next_level_readiness VARCHAR,
    next_level_id INTEGER,
    adaptive_assessment_plan TEXT,
    confidence VARCHAR,
    confidence_factors TEXT,
    evidence_quality TEXT,
    analysis_version VARCHAR,
    llm_interpretation TEXT,
    FOREIGN KEY (student_id) REFERENCES students(id),
    FOREIGN KEY (attempt_id) REFERENCES attempts(id),
    FOREIGN KEY (level_id) REFERENCES levels(id),
    FOREIGN KEY (next_level_id) REFERENCES levels(id)
)
""")

print("[OK] Created skill_gap_reports table")

# Create indexes for skill_gap_reports
cursor.execute("""
CREATE INDEX IF NOT EXISTS ix_skill_gap_reports_student_id
ON skill_gap_reports(student_id)
""")

cursor.execute("""
CREATE INDEX IF NOT EXISTS ix_skill_gap_reports_attempt_id
ON skill_gap_reports(attempt_id)
""")

print("[OK] Created indexes for skill_gap_reports")

# Create skill_gap_items table
cursor.execute("""
CREATE TABLE IF NOT EXISTS skill_gap_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    report_id INTEGER NOT NULL,
    topic_id INTEGER NOT NULL,
    subtopic_id INTEGER,
    topic_name VARCHAR,
    subtopic_name VARCHAR,
    accuracy FLOAT,
    severity VARCHAR,
    priority INTEGER,
    classification VARCHAR,
    trend VARCHAR,
    evidence TEXT,
    reason TEXT,
    recommended_action TEXT,
    confidence VARCHAR,
    FOREIGN KEY (report_id) REFERENCES skill_gap_reports(id),
    FOREIGN KEY (topic_id) REFERENCES topics(id),
    FOREIGN KEY (subtopic_id) REFERENCES subtopics(id)
)
""")

print("[OK] Created skill_gap_items table")

# Create index for skill_gap_items
cursor.execute("""
CREATE INDEX IF NOT EXISTS ix_skill_gap_items_report_id
ON skill_gap_items(report_id)
""")

print("[OK] Created indexes for skill_gap_items")

# Commit changes
conn.commit()
conn.close()

print("\n[SUCCESS] All Skill Gap Analysis tables created successfully!")
print("\nYou can now run:")
print("  uvicorn app.main:app --reload")
