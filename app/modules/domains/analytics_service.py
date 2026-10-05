"""
app/modules/domains/analytics_service.py
-----------------------------------------
Domain analytics business logic for Track Owner dashboard.

Provides analytics for:
- Student overview (enrollment, levels, semesters)
- Topic-wise performance across track
- Difficulty-wise performance
- Individual student reports

Cross-module calls:
- Reads from analytics summary tables (student_performance_summary, etc.)
- Queries attempts, results, enrollments, level_progress
- Does NOT import other module models directly (uses service layer)
"""

from datetime import datetime
from sqlalchemy import select, func, case, and_, or_, desc, Float
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.modules.domains.models import Track, Level, Topic
from app.modules.users.models import Student, User
# Import analytics models - allowed since we're querying them
from app.modules.analytics.models import StudentPerformanceSummary
from app.modules.attempts.models import Attempt, Result, TopicResult
from app.modules.progress.models import Enrollment, LevelProgress
from app.modules.ai_engine.models import Question
from app.modules.attempts.models import AttemptAnswer
from app.modules.ai_engine.models import QuestionOption


async def get_domain_overview(track_id: int, db: AsyncSession) -> dict:
    """
    Get overall domain statistics.

    Returns:
        {
            'track_id': int,
            'track_name': str,
            'total_students': int,
            'blocked_students': int,
            'total_attempts': int,
            'total_levels': int,
            'avg_completion_rate': float,
            'last_updated': datetime
        }
    """
    # Get track info
    track = await db.get(Track, track_id)
    if not track:
        raise NotFoundError(f"Track {track_id} not found")

    # Count total students enrolled
    total_students_result = await db.execute(
        select(func.count(func.distinct(Enrollment.student_id)))
        .where(Enrollment.track_id == track_id)
    )
    total_students = total_students_result.scalar() or 0

    # Count blocked students
    blocked_students_result = await db.execute(
        select(func.count(func.distinct(Enrollment.student_id)))
        .where(
            Enrollment.track_id == track_id,
            Enrollment.is_blocked == True
        )
    )
    blocked_students = blocked_students_result.scalar() or 0

    # Count total attempts for this track
    total_attempts_result = await db.execute(
        select(func.count(Attempt.id))
        .select_from(Attempt)
        .join(Enrollment, Enrollment.id == Attempt.enrollment_id)
        .where(Enrollment.track_id == track_id)
    )
    total_attempts = total_attempts_result.scalar() or 0

    # Count levels in track
    levels_result = await db.execute(
        select(func.count(Level.id))
        .where(Level.track_id == track_id)
    )
    total_levels = levels_result.scalar() or 0

    # Calculate average completion rate
    # For each student, count passed levels / total levels
    if total_students > 0 and total_levels > 0:
        completion_result = await db.execute(
            select(func.avg(
                func.cast(
                    select(func.count(LevelProgress.id))
                    .select_from(LevelProgress)
                    .join(Level, Level.id == LevelProgress.level_id)
                    .where(
                        LevelProgress.enrollment_id == Enrollment.id,
                        LevelProgress.status == 'passed',
                        Level.track_id == track_id
                    )
                    .correlate(Enrollment)
                    .scalar_subquery(),
                    Float
                ) / total_levels
            ))
            .select_from(Enrollment)
            .where(Enrollment.track_id == track_id)
        )
        avg_completion_rate = completion_result.scalar() or 0.0
    else:
        avg_completion_rate = 0.0

    return {
        'track_id': track_id,
        'track_name': track.name,
        'total_students': total_students,
        'blocked_students': blocked_students,
        'total_attempts': total_attempts,
        'total_levels': total_levels,
        'avg_completion_rate': avg_completion_rate,
        'last_updated': datetime.utcnow()
    }


async def get_students_by_level(track_id: int, db: AsyncSession) -> list[dict]:
    """
    Get student counts grouped by level.

    For each level in the track, count:
    - Total students who have attempted or are at this level
    - Students who passed
    - Students who failed (with retries left)
    - Students in progress
    - Students blocked at this level

    Returns list of dicts, one per level, ordered by level_no.
    """
    # Get all levels for this track
    levels_result = await db.execute(
        select(Level)
        .where(Level.track_id == track_id)
        .order_by(Level.level_no)
    )
    levels = levels_result.scalars().all()

    results = []
    for level in levels:
        # Count students by status for this level
        status_counts = await db.execute(
            select(
                LevelProgress.status,
                func.count(func.distinct(LevelProgress.enrollment_id)).label('count')
            )
            .select_from(LevelProgress)
            .join(Enrollment, Enrollment.id == LevelProgress.enrollment_id)
            .where(
                LevelProgress.level_id == level.id,
                Enrollment.track_id == track_id
            )
            .group_by(LevelProgress.status)
        )

        status_map = {row.status: row.count for row in status_counts.all()}

        # Count blocked students at this level
        # A student is blocked at a level if they're enrolled in the track,
        # is_blocked=true, and this is their current/last attempted level
        blocked_result = await db.execute(
            select(func.count(func.distinct(Enrollment.student_id)))
            .select_from(Enrollment)
            .join(LevelProgress, LevelProgress.enrollment_id == Enrollment.id)
            .where(
                Enrollment.track_id == track_id,
                Enrollment.is_blocked == True,
                LevelProgress.level_id == level.id
            )
        )
        blocked_count = blocked_result.scalar() or 0

        passed_count = status_map.get('passed', 0)
        failed_count = status_map.get('failed', 0)
        in_progress_count = status_map.get('in_progress', 0)
        unlocked_count = status_map.get('unlocked', 0)

        total_students = sum(status_map.values())

        results.append({
            'level_id': level.id,
            'level_no': level.level_no,
            'level_name': level.name,
            'total_students': total_students,
            'passed_count': passed_count,
            'failed_count': failed_count,
            'in_progress_count': in_progress_count + unlocked_count,
            'blocked_count': blocked_count
        })

    return results


async def get_students_by_semester(track_id: int, db: AsyncSession) -> list[dict]:
    """
    Get student counts grouped by semester (curr_sem 1-10).

    For each semester, calculate:
    - Number of students in that semester enrolled in this track
    - Average levels completed by those students

    Returns list of dicts, one per semester (1-10).
    """
    results = []

    for sem in range(1, 11):  # Semesters 1-10
        # Count students in this semester enrolled in track
        student_count_result = await db.execute(
            select(func.count(func.distinct(Student.id)))
            .select_from(Student)
            .join(Enrollment, Enrollment.student_id == Student.id)
            .where(
                Student.curr_sem == sem,
                Enrollment.track_id == track_id
            )
        )
        student_count = student_count_result.scalar() or 0

        # Calculate average levels completed
        if student_count > 0:
            avg_levels_result = await db.execute(
                select(func.avg(
                    select(func.count(LevelProgress.id))
                    .select_from(LevelProgress)
                    .join(Level, Level.id == LevelProgress.level_id)
                    .where(
                        LevelProgress.enrollment_id == Enrollment.id,
                        LevelProgress.status == 'passed',
                        Level.track_id == track_id
                    )
                    .correlate(Enrollment)
                    .scalar_subquery()
                ))
                .select_from(Enrollment)
                .join(Student, Student.id == Enrollment.student_id)
                .where(
                    Student.curr_sem == sem,
                    Enrollment.track_id == track_id
                )
            )
            avg_levels = avg_levels_result.scalar() or 0.0
        else:
            avg_levels = 0.0

        # Calculate year from semester: year = ⌈sem / 2⌉
        year = (sem + 1) // 2

        results.append({
            'curr_sem': sem,
            'year': year,
            'student_count': student_count,
            'avg_levels_completed': avg_levels
        })

    return results


async def get_topic_performance(
    track_id: int,
    level_id: int | None,
    db: AsyncSession
) -> list[dict]:
    """
    Get topic-wise performance across all students in track.

    Args:
        track_id: The track to analyze
        level_id: Optional level filter (None = all levels)

    Returns list of dicts with topic performance metrics.
    """
    # Build query
    query = (
        select(
            Topic.id.label('topic_id'),
            Topic.name.label('topic_name'),
            Topic.level_id,
            Level.level_no,
            Level.name.label('level_name'),
            func.count(func.distinct(TopicResult.id)).label('total_attempts'),
            func.avg(TopicResult.accuracy).label('avg_accuracy'),
            func.count(func.distinct(Attempt.student_id)).label('students_attempted'),
            func.count(func.distinct(
                case((TopicResult.accuracy >= 0.7, Attempt.student_id), else_=None)
            )).label('students_passed'),
            func.count(func.distinct(
                case((TopicResult.accuracy < 0.5, Attempt.student_id), else_=None)
            )).label('students_struggling')
        )
        .select_from(Topic)
        .join(Level, Level.id == Topic.level_id)
        .outerjoin(TopicResult, TopicResult.topic_id == Topic.id)
        .outerjoin(Result, Result.id == TopicResult.result_id)
        .outerjoin(Attempt, Attempt.id == Result.attempt_id)
        .outerjoin(Enrollment, Enrollment.id == Attempt.enrollment_id)
        .where(Level.track_id == track_id)
    )

    if level_id is not None:
        query = query.where(Level.id == level_id)

    query = query.group_by(
        Topic.id, Topic.name, Topic.level_id, Level.level_no, Level.name
    ).order_by(Level.level_no, Topic.sequence_no)

    result = await db.execute(query)
    rows = result.all()

    return [
        {
            'topic_id': row.topic_id,
            'topic_name': row.topic_name,
            'level_id': row.level_id,
            'level_no': row.level_no,
            'level_name': row.level_name,
            'total_attempts': row.total_attempts or 0,
            'avg_accuracy': float(row.avg_accuracy or 0.0),
            'students_attempted': row.students_attempted or 0,
            'students_passed': row.students_passed or 0,
            'students_struggling': row.students_struggling or 0
        }
        for row in rows
    ]


async def get_difficulty_performance(track_id: int, db: AsyncSession) -> list[dict]:
    """
    Get difficulty-wise performance summary for track.

    For each difficulty (easy, medium, hard), calculate:
    - Total questions attempted
    - Total correct answers
    - Accuracy
    - Number of students who attempted this difficulty

    Returns list of dicts, one per difficulty.
    """
    # Query attempts -> questions -> answers
    # Join through enrollment to filter by track
    query = (
        select(
            Question.difficulty,
            func.count(AttemptAnswer.id).label('total_questions'),
            func.sum(
                case((QuestionOption.is_correct == True, 1), else_=0)
            ).label('total_correct'),
            func.count(func.distinct(Attempt.student_id)).label('student_count')
        )
        .select_from(AttemptAnswer)
        .join(Question, Question.id == AttemptAnswer.question_id)
        .join(QuestionOption, QuestionOption.id == AttemptAnswer.selected_option_id)
        .join(Attempt, Attempt.id == AttemptAnswer.attempt_id)
        .join(Enrollment, Enrollment.id == Attempt.enrollment_id)
        .where(Enrollment.track_id == track_id)
        .group_by(Question.difficulty)
    )

    result = await db.execute(query)
    rows = result.all()

    return [
        {
            'difficulty': row.difficulty,
            'total_questions': row.total_questions or 0,
            'total_correct': row.total_correct or 0,
            'accuracy': (row.total_correct / row.total_questions) if row.total_questions > 0 else 0.0,
            'student_count': row.student_count or 0
        }
        for row in rows
    ]


async def get_student_report(
    student_id: int,
    track_id: int,
    db: AsyncSession
) -> dict:
    """
    Get comprehensive student report across all 8 levels.

    Returns detailed report including:
    - Student info
    - Current progress
    - Attempt statistics
    - Level-by-level breakdown (all 8 levels)
    """
    # Get student and user info
    student_result = await db.execute(
        select(Student, User)
        .join(User, User.id == Student.user_id)
        .where(Student.id == student_id)
    )
    student_row = student_result.first()
    if not student_row:
        raise NotFoundError(f"Student {student_id} not found")

    student, user = student_row

    # Get enrollment
    enrollment_result = await db.execute(
        select(Enrollment)
        .where(
            Enrollment.student_id == student_id,
            Enrollment.track_id == track_id
        )
    )
    enrollment = enrollment_result.scalar_one_or_none()
    if not enrollment:
        raise NotFoundError(f"Student {student_id} not enrolled in track {track_id}")

    # Get track info
    track = await db.get(Track, track_id)

    # Get all 8 levels for the track
    levels_result = await db.execute(
        select(Level)
        .where(Level.track_id == track_id)
        .order_by(Level.level_no)
        .limit(8)
    )
    levels = levels_result.scalars().all()

    # Get level progress for all levels
    level_details = []
    levels_passed = 0
    levels_failed = 0
    current_level = 1

    for level in levels:
        # Get level progress
        progress_result = await db.execute(
            select(LevelProgress)
            .where(
                LevelProgress.enrollment_id == enrollment.id,
                LevelProgress.level_id == level.id
            )
        )
        progress = progress_result.scalar_one_or_none()

        # Get attempt info for this level
        attempts_result = await db.execute(
            select(
                func.count(Attempt.id).label('attempt_count'),
                func.max(Result.percentage).label('best_score'),
                func.max(Attempt.submitted_at).label('last_attempt_date')
            )
            .select_from(Attempt)
            .outerjoin(Result, Result.attempt_id == Attempt.id)
            .where(
                Attempt.student_id == student_id,
                Attempt.level_id == level.id
            )
        )
        attempt_info = attempts_result.first()

        status = progress.status if progress else 'locked'
        attempt_count = attempt_info.attempt_count or 0
        best_score = float(attempt_info.best_score) if attempt_info.best_score is not None else None
        last_attempt_date = attempt_info.last_attempt_date

        level_details.append({
            'level_id': level.id,
            'level_no': level.level_no,
            'level_name': level.name,
            'attempt_count': attempt_count,
            'status': status,
            'best_score': best_score,
            'last_attempt_date': last_attempt_date
        })

        if status == 'passed':
            levels_passed += 1
        elif status == 'failed':
            levels_failed += 1

        # Determine current level (highest unlocked or passed + 1)
        if status in ['unlocked', 'in_progress', 'failed']:
            current_level = max(current_level, level.level_no)
        elif status == 'passed':
            current_level = max(current_level, level.level_no + 1)

    # Clamp current level to valid range
    current_level = min(current_level, 8)

    # Get overall attempt statistics
    overall_attempts_result = await db.execute(
        select(
            func.count(Attempt.id).label('total_attempts'),
            func.count(case((Result.verdict == 'pass', 1), else_=None)).label('successful_attempts'),
            func.count(case((Result.verdict == 'fail', 1), else_=None)).label('failed_attempts'),
            func.avg(Result.percentage).label('avg_score')
        )
        .select_from(Attempt)
        .join(Result, Result.attempt_id == Attempt.id)
        .join(Enrollment, Enrollment.id == Attempt.enrollment_id)
        .where(
            Attempt.student_id == student_id,
            Enrollment.track_id == track_id
        )
    )
    overall_stats = overall_attempts_result.first()

    total_attempts = overall_stats.total_attempts or 0
    successful_attempts = overall_stats.successful_attempts or 0
    failed_attempts = overall_stats.failed_attempts or 0
    overall_avg_score = float(overall_stats.avg_score or 0.0)

    # Get last activity date
    last_activity_result = await db.execute(
        select(func.max(Attempt.submitted_at))
        .where(
            Attempt.student_id == student_id,
            Attempt.enrollment_id == enrollment.id
        )
    )
    last_activity = last_activity_result.scalar()

    # Calculate year from semester
    year = (student.curr_sem + 1) // 2

    return {
        'student_id': student_id,
        'student_name': user.full_name or user.email,
        'reg_num': student.reg_num or student.roll_number or '',
        'curr_sem': student.curr_sem or 1,
        'year': year,
        'track_id': track_id,
        'track_name': track.name,
        'current_level': current_level,
        'levels_passed': levels_passed,
        'levels_failed': levels_failed,
        'is_blocked': enrollment.is_blocked,
        'total_attempts': total_attempts,
        'successful_attempts': successful_attempts,
        'failed_attempts': failed_attempts,
        'overall_avg_score': overall_avg_score,
        'level_details': level_details,
        'first_enrollment_date': enrollment.enrolled_at,
        'last_activity_date': last_activity
    }


async def list_students_for_track(
    track_id: int,
    filters: dict,
    page: int,
    page_size: int,
    db: AsyncSession
) -> tuple[list[dict], int]:
    """
    List all students enrolled in track with filters and pagination.

    Args:
        track_id: Track to filter by
        filters: {
            'curr_sem': int | None,
            'is_blocked': bool | None,
            'search': str | None (search in name, email, reg_num)
        }
        page: Page number (1-indexed)
        page_size: Items per page

    Returns:
        (students, total_count)
    """
    # Base query
    query = (
        select(
            Student.id.label('student_id'),
            Student.user_id,
            User.full_name,
            User.email,
            Student.reg_num,
            Student.curr_sem,
            Enrollment.is_blocked
        )
        .select_from(Student)
        .join(User, User.id == Student.user_id)
        .join(Enrollment, Enrollment.student_id == Student.id)
        .where(Enrollment.track_id == track_id)
    )

    # Apply filters
    if filters.get('curr_sem') is not None:
        query = query.where(Student.curr_sem == filters['curr_sem'])

    if filters.get('is_blocked') is not None:
        query = query.where(Enrollment.is_blocked == filters['is_blocked'])

    if filters.get('search'):
        search_term = f"%{filters['search']}%"
        query = query.where(
            or_(
                User.full_name.ilike(search_term),
                User.email.ilike(search_term),
                Student.reg_num.ilike(search_term)
            )
        )

    # Count total
    count_query = select(func.count()).select_from(query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    # Apply pagination
    query = query.order_by(User.full_name).offset((page - 1) * page_size).limit(page_size)

    result = await db.execute(query)
    rows = result.all()

    students = []
    for row in rows:
        # Calculate year
        year = (row.curr_sem + 1) // 2 if row.curr_sem else 1

        # Get student performance summary
        perf_result = await db.execute(
            select(StudentPerformanceSummary)
            .where(
                StudentPerformanceSummary.student_id == row.student_id,
                StudentPerformanceSummary.track_id == track_id
            )
        )
        perf = perf_result.scalar_one_or_none()

        # Get current level (highest passed + 1, or highest unlocked)
        level_progress_result = await db.execute(
            select(Level.level_no, LevelProgress.status)
            .select_from(LevelProgress)
            .join(Level, Level.id == LevelProgress.level_id)
            .join(Enrollment, Enrollment.id == LevelProgress.enrollment_id)
            .where(
                LevelProgress.enrollment_id == Enrollment.id,
                Enrollment.student_id == row.student_id,
                Enrollment.track_id == track_id
            )
            .order_by(Level.level_no)
        )
        level_progress_rows = level_progress_result.all()

        current_level = 1
        for lp_row in level_progress_rows:
            if lp_row.status == 'passed':
                current_level = max(current_level, lp_row.level_no + 1)
            elif lp_row.status in ['unlocked', 'in_progress', 'failed']:
                current_level = max(current_level, lp_row.level_no)

        current_level = min(current_level, 8)

        # Get last activity
        last_activity_result = await db.execute(
            select(func.max(Attempt.submitted_at))
            .select_from(Attempt)
            .join(Enrollment, Enrollment.id == Attempt.enrollment_id)
            .where(
                Attempt.student_id == row.student_id,
                Enrollment.track_id == track_id
            )
        )
        last_activity = last_activity_result.scalar()

        students.append({
            'student_id': row.student_id,
            'user_id': row.user_id,
            'full_name': row.full_name or row.email,
            'email': row.email,
            'reg_num': row.reg_num or '',
            'curr_sem': row.curr_sem or 1,
            'year': year,
            'current_level': current_level,
            'levels_passed': perf.passed_levels if perf else 0,
            'total_attempts': perf.total_attempts if perf else 0,
            'avg_score': perf.avg_percentage if perf else 0.0,
            'is_blocked': row.is_blocked,
            'last_activity': last_activity
        })

    return students, total
