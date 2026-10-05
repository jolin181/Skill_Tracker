"""
app/modules/domains/analytics_router.py
----------------------------------------
Domain analytics endpoints for Track Owner dashboard.

All endpoints require Track Owner or Admin authorization.
Track Owners can only access their assigned track.

Endpoints:
- GET /api/v1/domains/{track_id}/analytics/overview
- GET /api/v1/domains/{track_id}/analytics/students/by-level
- GET /api/v1/domains/{track_id}/analytics/students/by-semester
- GET /api/v1/domains/{track_id}/analytics/topics/performance
- GET /api/v1/domains/{track_id}/analytics/difficulty/performance
- GET /api/v1/domains/{track_id}/analytics/students
- GET /api/v1/domains/{track_id}/analytics/students/{student_id}/report
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.core.exceptions import NotFoundError
from app.modules.domains import analytics_service
from app.modules.domains.schemas import (
    DomainOverviewResponse,
    StudentByLevelResponse,
    StudentBySemesterResponse,
    TopicPerformanceResponse,
    DifficultyPerformanceResponse,
    StudentReportResponse,
    StudentListResponse
)

router = APIRouter()


def verify_track_access(current_user: dict, track_id: int) -> None:
    """
    Verify user can access this track.
    - Admins can access any track
    - Domain owners can only access their role's track

    Raises HTTPException(403) if unauthorized.
    """
    # Admin has full access
    if "admin" in current_user.get("roles", []):
        return

    # Check if user is a domain owner
    user = current_user.get("user")
    if user and hasattr(user, 'is_domain_owner') and user.is_domain_owner:
        # Check if this track is in their owned tracks
        if hasattr(user, 'owned_track_ids') and track_id in user.owned_track_ids:
            return

    # Unauthorized
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={
            "code": "TRACK_ACCESS_DENIED",
            "message": "You can only access analytics for your assigned track."
        }
    )


# ─────────────────────────────────────────────────────────────────────────────
# DOMAIN OVERVIEW
# ─────────────────────────────────────────────────────────────────────────────

@router.get(
    "/{track_id}/analytics/overview",
    response_model=DomainOverviewResponse,
    summary="Get domain overview statistics",
    description="Get overall statistics for a track including student counts, attempts, and completion rates."
)
async def get_domain_overview(
    track_id: int,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> DomainOverviewResponse:
    """
    Get overall domain statistics.

    **Authorization:** Admin or Track Owner for this track.

    Returns:
    - Total students enrolled
    - Blocked students count
    - Total attempts across all students
    - Number of levels in track
    - Average completion rate
    """
    verify_track_access(current_user, track_id)

    try:
        data = await analytics_service.get_domain_overview(track_id, db)
        return DomainOverviewResponse(**data)
    except NotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "TRACK_NOT_FOUND", "message": str(e)}
        )


# ─────────────────────────────────────────────────────────────────────────────
# STUDENTS BY LEVEL
# ─────────────────────────────────────────────────────────────────────────────

@router.get(
    "/{track_id}/analytics/students/by-level",
    response_model=list[StudentByLevelResponse],
    summary="Get students grouped by level",
    description="Get student counts grouped by level, showing passed/failed/in-progress/blocked for each level."
)
async def get_students_by_level(
    track_id: int,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> list[StudentByLevelResponse]:
    """
    Get students grouped by level.

    **Authorization:** Admin or Track Owner for this track.

    Returns list of levels with student counts:
    - Total students at each level
    - Passed count
    - Failed count
    - In progress count
    - Blocked count
    """
    verify_track_access(current_user, track_id)

    data = await analytics_service.get_students_by_level(track_id, db)
    return [StudentByLevelResponse(**item) for item in data]


# ─────────────────────────────────────────────────────────────────────────────
# STUDENTS BY SEMESTER
# ─────────────────────────────────────────────────────────────────────────────

@router.get(
    "/{track_id}/analytics/students/by-semester",
    response_model=list[StudentBySemesterResponse],
    summary="Get students grouped by semester",
    description="Get student counts grouped by semester (1-10), with average levels completed."
)
async def get_students_by_semester(
    track_id: int,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> list[StudentBySemesterResponse]:
    """
    Get students grouped by semester.

    **Authorization:** Admin or Track Owner for this track.

    Returns list of semesters (1-10) with:
    - Student count in each semester
    - Average levels completed by those students
    - Derived year (1-5)
    """
    verify_track_access(current_user, track_id)

    data = await analytics_service.get_students_by_semester(track_id, db)
    return [StudentBySemesterResponse(**item) for item in data]


# ─────────────────────────────────────────────────────────────────────────────
# TOPIC PERFORMANCE
# ─────────────────────────────────────────────────────────────────────────────

@router.get(
    "/{track_id}/analytics/topics/performance",
    response_model=list[TopicPerformanceResponse],
    summary="Get topic-wise performance",
    description="Get performance metrics for each topic across all students in the track."
)
async def get_topic_performance(
    track_id: int,
    level_id: int | None = Query(None, description="Filter by level (optional)"),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> list[TopicPerformanceResponse]:
    """
    Get topic-wise performance across the track.

    **Authorization:** Admin or Track Owner for this track.

    **Query Parameters:**
    - `level_id` (optional): Filter topics to a specific level

    Returns list of topics with:
    - Average accuracy across all students
    - Total attempts
    - Students who attempted
    - Students who passed (accuracy >= 0.7)
    - Students struggling (accuracy < 0.5)
    """
    verify_track_access(current_user, track_id)

    data = await analytics_service.get_topic_performance(track_id, level_id, db)
    return [TopicPerformanceResponse(**item) for item in data]


# ─────────────────────────────────────────────────────────────────────────────
# DIFFICULTY PERFORMANCE
# ─────────────────────────────────────────────────────────────────────────────

@router.get(
    "/{track_id}/analytics/difficulty/performance",
    response_model=list[DifficultyPerformanceResponse],
    summary="Get difficulty-wise performance",
    description="Get performance metrics grouped by difficulty (easy/medium/hard)."
)
async def get_difficulty_performance(
    track_id: int,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> list[DifficultyPerformanceResponse]:
    """
    Get difficulty-wise performance for the track.

    **Authorization:** Admin or Track Owner for this track.

    Returns list of difficulties (easy, medium, hard) with:
    - Total questions attempted
    - Total correct answers
    - Accuracy (correct/total)
    - Number of students who attempted this difficulty
    """
    verify_track_access(current_user, track_id)

    data = await analytics_service.get_difficulty_performance(track_id, db)
    return [DifficultyPerformanceResponse(**item) for item in data]


# ─────────────────────────────────────────────────────────────────────────────
# STUDENT LIST
# ─────────────────────────────────────────────────────────────────────────────

@router.get(
    "/{track_id}/analytics/students",
    response_model=StudentListResponse,
    summary="List students in track",
    description="Get paginated list of students enrolled in track with filters."
)
async def list_students(
    track_id: int,
    page: int = Query(1, ge=1, description="Page number (1-indexed)"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    curr_sem: int | None = Query(None, ge=1, le=10, description="Filter by semester"),
    is_blocked: bool | None = Query(None, description="Filter by blocked status"),
    search: str | None = Query(None, description="Search in name, email, reg_num"),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> StudentListResponse:
    """
    List students enrolled in track with filters and pagination.

    **Authorization:** Admin or Track Owner for this track.

    **Query Parameters:**
    - `page`: Page number (default: 1)
    - `page_size`: Items per page (default: 20, max: 100)
    - `curr_sem`: Filter by semester (1-10)
    - `is_blocked`: Filter by blocked status (true/false)
    - `search`: Search in student name, email, or reg_num

    Returns paginated list of students with:
    - Student info (name, email, reg_num, semester)
    - Current level
    - Levels passed
    - Total attempts
    - Average score
    - Blocked status
    - Last activity date
    """
    verify_track_access(current_user, track_id)

    filters = {
        'curr_sem': curr_sem,
        'is_blocked': is_blocked,
        'search': search
    }

    students, total = await analytics_service.list_students_for_track(
        track_id, filters, page, page_size, db
    )

    return StudentListResponse(
        students=students,
        total=total,
        page=page,
        page_size=page_size,
        filters_applied=filters
    )


# ─────────────────────────────────────────────────────────────────────────────
# STUDENT REPORT
# ─────────────────────────────────────────────────────────────────────────────

@router.get(
    "/{track_id}/analytics/students/{student_id}/report",
    response_model=StudentReportResponse,
    summary="Get comprehensive student report",
    description="Get detailed student report across all 8 levels with attempt history and performance."
)
async def get_student_report(
    track_id: int,
    student_id: int,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> StudentReportResponse:
    """
    Get comprehensive student report.

    **Authorization:** Admin or Track Owner for this track.

    Returns detailed report including:
    - Student information (name, email, reg_num, semester, year)
    - Current progress (current level, levels passed/failed, blocked status)
    - Attempt statistics (total, successful, failed)
    - Overall average score
    - Level-by-level breakdown (all 8 levels, showing status and attempts)
    - Activity dates (enrollment, last activity)

    **Note:** Report always includes all 8 levels, even if not attempted.
    """
    verify_track_access(current_user, track_id)

    try:
        data = await analytics_service.get_student_report(student_id, track_id, db)
        return StudentReportResponse(**data)
    except NotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "STUDENT_NOT_FOUND" if "Student" in str(e) else "ENROLLMENT_NOT_FOUND",
                "message": str(e)
            }
        )
