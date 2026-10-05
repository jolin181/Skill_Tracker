"""
app/modules/domains/schemas.py
-------------------------------
Pydantic schemas for the domains module.

TODO: Add TrackListResponse, LevelDetailResponse.
TODO: Add TopicResponse with ordered subtopics list.
TODO: Add SubtopicResponse.
"""

from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional


class TrackResponse(BaseModel):
    id: int
    name: str
    description: str
    is_active: bool


class LevelResponse(BaseModel):
    id: int
    track_id: int
    level_no: int
    name: str
    description: str


class TopicResponse(BaseModel):
    id: int
    level_id: int
    name: str
    description: str
    sequence_no: int
    is_optional: bool


class SubtopicResponse(BaseModel):
    id: int
    topic_id: int
    name: str
    description: str
    sequence_no: int


# ═══════════════════════════════════════════════════════════════════════════
# DOMAIN ANALYTICS SCHEMAS
# ═══════════════════════════════════════════════════════════════════════════

class DomainOverviewResponse(BaseModel):
    """Overall domain/track statistics."""
    track_id: int
    track_name: str
    total_students: int = Field(..., ge=0, description="Total students enrolled in track")
    blocked_students: int = Field(..., ge=0, description="Students blocked from track")
    total_attempts: int = Field(..., ge=0, description="Total attempts across all students")
    total_levels: int = Field(..., ge=0, description="Number of levels in track")
    avg_completion_rate: float = Field(..., ge=0.0, le=1.0, description="Average fraction of levels completed")
    last_updated: datetime


class StudentByLevelResponse(BaseModel):
    """Students grouped by current level."""
    level_id: int
    level_no: int
    level_name: str
    total_students: int = Field(..., ge=0, description="Students at this level")
    passed_count: int = Field(..., ge=0, description="Students who passed this level")
    failed_count: int = Field(..., ge=0, description="Students who failed (with retries left)")
    in_progress_count: int = Field(..., ge=0, description="Students currently attempting")
    blocked_count: int = Field(..., ge=0, description="Students blocked at this level")


class StudentBySemesterResponse(BaseModel):
    """Students grouped by current semester."""
    curr_sem: int = Field(..., ge=1, le=10, description="Semester number (1-10)")
    year: int = Field(..., ge=1, le=5, description="Academic year (1-5)")
    student_count: int = Field(..., ge=0, description="Number of students in this semester")
    avg_levels_completed: float = Field(..., ge=0.0, description="Average levels completed by these students")


class TopicPerformanceResponse(BaseModel):
    """Topic performance across all students in track."""
    topic_id: int
    topic_name: str
    level_id: int
    level_no: int
    level_name: str

    # Aggregated metrics
    total_attempts: int = Field(..., ge=0)
    avg_accuracy: float = Field(..., ge=0.0, le=1.0, description="Average accuracy (0.0-1.0)")
    students_attempted: int = Field(..., ge=0)
    students_passed: int = Field(..., ge=0, description="Students with accuracy >= 0.7")
    students_struggling: int = Field(..., ge=0, description="Students with accuracy < 0.5")


class DifficultyPerformanceResponse(BaseModel):
    """Difficulty-wise performance for the track."""
    difficulty: str = Field(..., description="easy, medium, or hard")
    total_questions: int = Field(..., ge=0)
    total_correct: int = Field(..., ge=0)
    accuracy: float = Field(..., ge=0.0, le=1.0, description="Fraction correct")
    student_count: int = Field(..., ge=0, description="Students who attempted this difficulty")


class StudentAttemptSummary(BaseModel):
    """Summary of attempts for one level."""
    level_id: int
    level_no: int
    level_name: str
    attempt_count: int = Field(..., ge=0, le=3, description="Number of attempts (0-3)")
    status: str = Field(..., description="locked, unlocked, passed, failed, in_progress")
    best_score: Optional[float] = Field(None, ge=0.0, le=100.0, description="Best percentage achieved")
    last_attempt_date: Optional[datetime] = None


class StudentReportResponse(BaseModel):
    """Comprehensive student report across all levels."""
    student_id: int
    student_name: str
    reg_num: str
    curr_sem: int = Field(..., ge=1, le=10)
    year: int = Field(..., ge=1, le=5)
    track_id: int
    track_name: str

    # Overall progress
    current_level: int = Field(..., ge=1, le=8, description="Current level number")
    levels_passed: int = Field(..., ge=0, le=8)
    levels_failed: int = Field(..., ge=0)
    is_blocked: bool

    # Attempt statistics
    total_attempts: int = Field(..., ge=0)
    successful_attempts: int = Field(..., ge=0, description="Passed attempts")
    failed_attempts: int = Field(..., ge=0)

    # Performance
    overall_avg_score: float = Field(..., ge=0.0, le=100.0)

    # Level-by-level breakdown (all 8 levels)
    level_details: list[StudentAttemptSummary] = Field(..., min_length=8, max_length=8)

    # Activity summary
    first_enrollment_date: datetime
    last_activity_date: Optional[datetime] = None


class StudentListItem(BaseModel):
    """Item in student list for domain dashboard."""
    student_id: int
    user_id: int
    full_name: str
    email: str
    reg_num: str
    curr_sem: int = Field(..., ge=1, le=10)
    year: int = Field(..., ge=1, le=5)
    current_level: int = Field(..., ge=1, le=8)
    levels_passed: int = Field(..., ge=0, le=8)
    total_attempts: int = Field(..., ge=0)
    avg_score: float = Field(..., ge=0.0, le=100.0)
    is_blocked: bool
    last_activity: Optional[datetime] = None


class StudentListResponse(BaseModel):
    """Paginated student list."""
    students: list[StudentListItem]
    total: int = Field(..., ge=0)
    page: int = Field(..., ge=1)
    page_size: int = Field(..., ge=1)
    filters_applied: dict = Field(default_factory=dict)


# ═══════════════════════════════════════════════════════════════════════════
# SYLLABUS SCHEMAS
# ═══════════════════════════════════════════════════════════════════════════


class SyllabusUploadResponse(BaseModel):
    """Response after successful syllabus upload."""
    success: bool = Field(..., description="Upload success flag")
    message: str = Field(..., description="Success message")
    syllabus_id: int = Field(..., description="ID of uploaded syllabus")
    track_id: int = Field(..., description="Track ID")
    file_name: str = Field(..., description="Original filename")
    uploaded_at: datetime = Field(..., description="Upload timestamp")
    page_count: Optional[int] = Field(None, description="Number of pages extracted")
    extracted_text_length: int = Field(..., description="Length of extracted text")
    text_preview: str = Field(..., description="First 200 chars of text")


class SyllabusResponse(BaseModel):
    """Full syllabus data including extracted text."""
    syllabus_id: int
    track_id: int
    track_name: str
    file_name: str
    uploaded_by: int  # User ID
    uploaded_at: datetime
    page_count: Optional[int]
    file_size_bytes: int
    raw_text: str = Field(..., description="Full extracted text from PDF")
    status: str = Field(..., description="active, replaced, or archived")
    notes: Optional[str] = None


class SyllabusMetadataResponse(BaseModel):
    """Lightweight syllabus metadata (no full text)."""
    has_syllabus: bool = Field(..., description="Whether track has a syllabus")
    track_id: int
    track_name: Optional[str] = None
    syllabus_id: Optional[int] = None
    file_name: Optional[str] = None
    uploaded_at: Optional[datetime] = None
    page_count: Optional[int] = None
    text_length: int = Field(default=0, description="Length of extracted text")
