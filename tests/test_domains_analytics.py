"""
Tests for Domain Analytics endpoints.

Tests cover:
- Domain overview
- Students by level
- Students by semester
- Topic performance
- Difficulty performance
- Student reports
- Student list with filters
- Authorization checks
"""

import pytest
from datetime import datetime, timedelta
from sqlalchemy import select

from app.modules.domains.models import Track, Level, Topic
from app.modules.users.models import User, Student, Department, AcademicYear
from app.modules.progress.models import Enrollment, LevelProgress
from app.modules.attempts.models import Attempt, Result, TopicResult
from app.modules.exams.models import Assessment
from app.modules.auth.models import Role, UserRole


@pytest.fixture
async def sample_track(db_session):
    """Create a sample track with 8 levels."""
    track = Track(name="Full Stack", description="Full Stack Development", is_active=True)
    db_session.add(track)
    await db_session.flush()

    levels = []
    for i in range(1, 9):
        level = Level(
            track_id=track.id,
            level_no=i,
            name=f"Level {i}",
            description=f"Level {i} description"
        )
        levels.append(level)
        db_session.add(level)

    await db_session.commit()
    await db_session.refresh(track)
    return track, levels


@pytest.fixture
async def sample_topics(db_session, sample_track):
    """Create sample topics for the first level."""
    track, levels = sample_track
    level_1 = levels[0]

    topics = []
    for i in range(1, 4):
        topic = Topic(
            level_id=level_1.id,
            name=f"Topic {i}",
            description=f"Topic {i} description",
            sequence_no=i,
            is_optional=False
        )
        topics.append(topic)
        db_session.add(topic)

    await db_session.commit()
    return topics


@pytest.fixture
async def sample_students(db_session):
    """Create sample students."""
    dept = Department(name="Computer Science", code="CS")
    db_session.add(dept)

    year = AcademicYear(label="2024-2025")
    db_session.add(year)
    await db_session.flush()

    students = []
    for i in range(1, 6):
        user = User(
            email=f"student{i}@test.com",
            username=f"student{i}",
            full_name=f"Student {i}",
            password_hash="hashed",
            is_active=True
        )
        db_session.add(user)
        await db_session.flush()

        student = Student(
            user_id=user.id,
            department_id=dept.id,
            academic_year_id=year.id,
            roll_number=f"CS{i:03d}",
            reg_num=f"REG{i:03d}",
            curr_sem=i,  # Semesters 1-5
            foundation_year_completed=False
        )
        db_session.add(student)
        students.append(student)

    await db_session.commit()
    return students


@pytest.fixture
async def sample_enrollments(db_session, sample_track, sample_students):
    """Create sample enrollments."""
    track, levels = sample_track
    enrollments = []

    for i, student in enumerate(sample_students):
        enrollment = Enrollment(
            student_id=student.id,
            track_id=track.id,
            enrolled_at=datetime.utcnow() - timedelta(days=30),
            is_blocked=False if i < 4 else True  # Block last student
        )
        db_session.add(enrollment)
        enrollments.append(enrollment)

    await db_session.commit()
    return enrollments


@pytest.fixture
async def sample_level_progress(db_session, sample_track, sample_enrollments):
    """Create sample level progress."""
    track, levels = sample_track

    # Student 1: Passed level 1, unlocked level 2
    progress1 = [
        LevelProgress(
            enrollment_id=sample_enrollments[0].id,
            level_id=levels[0].id,
            status='passed',
            unlocked_at=datetime.utcnow() - timedelta(days=25),
            completed_at=datetime.utcnow() - timedelta(days=20)
        ),
        LevelProgress(
            enrollment_id=sample_enrollments[0].id,
            level_id=levels[1].id,
            status='unlocked',
            unlocked_at=datetime.utcnow() - timedelta(days=20)
        )
    ]

    # Student 2: In progress on level 1
    progress2 = [
        LevelProgress(
            enrollment_id=sample_enrollments[1].id,
            level_id=levels[0].id,
            status='in_progress',
            unlocked_at=datetime.utcnow() - timedelta(days=15)
        )
    ]

    # Student 3: Failed level 1 (with retries left)
    progress3 = [
        LevelProgress(
            enrollment_id=sample_enrollments[2].id,
            level_id=levels[0].id,
            status='failed',
            unlocked_at=datetime.utcnow() - timedelta(days=10)
        )
    ]

    for progress in progress1 + progress2 + progress3:
        db_session.add(progress)

    await db_session.commit()


@pytest.fixture
async def admin_user(db_session):
    """Create admin user with token."""
    user = User(
        email="admin@test.com",
        username="admin",
        full_name="Admin User",
        password_hash="hashed",
        is_active=True
    )
    db_session.add(user)
    await db_session.flush()

    # Get admin role
    role_result = await db_session.execute(select(Role).where(Role.name == "admin"))
    role = role_result.scalar_one()

    user_role = UserRole(user_id=user.id, role_id=role.id)
    db_session.add(user_role)

    await db_session.commit()
    await db_session.refresh(user)

    return user


@pytest.fixture
async def domain_owner_user(db_session, sample_track):
    """Create domain owner user for the sample track."""
    track, _ = sample_track

    user = User(
        email="owner@test.com",
        username="trackowner",
        full_name="Track Owner",
        password_hash="hashed",
        is_active=True
    )
    db_session.add(user)
    await db_session.flush()

    # Get domain owner role and assign track
    role_result = await db_session.execute(
        select(Role).where(Role.name == "fullstack_domain_owner")
    )
    role = role_result.scalar_one()
    role.track_id = track.id

    user_role = UserRole(user_id=user.id, role_id=role.id)
    db_session.add(user_role)

    await db_session.commit()
    await db_session.refresh(user)

    return user


# ═══════════════════════════════════════════════════════════════════════════
# UNIT TESTS - Service Layer
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_get_domain_overview(
    db_session,
    sample_track,
    sample_enrollments,
    sample_level_progress
):
    """Test domain overview retrieves correct statistics."""
    from app.modules.domains import analytics_service

    track, levels = sample_track
    result = await analytics_service.get_domain_overview(track.id, db_session)

    assert result['track_id'] == track.id
    assert result['track_name'] == "Full Stack"
    assert result['total_students'] == 5
    assert result['blocked_students'] == 1
    assert result['total_levels'] == 8
    assert result['avg_completion_rate'] >= 0.0
    assert result['avg_completion_rate'] <= 1.0


@pytest.mark.asyncio
async def test_get_students_by_level(
    db_session,
    sample_track,
    sample_enrollments,
    sample_level_progress
):
    """Test students grouped by level."""
    from app.modules.domains import analytics_service

    track, levels = sample_track
    result = await analytics_service.get_students_by_level(track.id, db_session)

    # Should return all 8 levels
    assert len(result) == 8

    # Check level 1 has the correct counts
    level_1_data = result[0]
    assert level_1_data['level_no'] == 1
    assert level_1_data['passed_count'] == 1  # Student 1 passed
    assert level_1_data['in_progress_count'] >= 1  # Student 2 in progress
    assert level_1_data['failed_count'] == 1  # Student 3 failed


@pytest.mark.asyncio
async def test_get_students_by_semester(
    db_session,
    sample_track,
    sample_students,
    sample_enrollments
):
    """Test students grouped by semester."""
    from app.modules.domains import analytics_service

    track, levels = sample_track
    result = await analytics_service.get_students_by_semester(track.id, db_session)

    # Should return all 10 semesters
    assert len(result) == 10

    # Check semester 1 has 1 student
    sem_1_data = result[0]
    assert sem_1_data['curr_sem'] == 1
    assert sem_1_data['year'] == 1
    assert sem_1_data['student_count'] == 1


@pytest.mark.asyncio
async def test_get_topic_performance(
    db_session,
    sample_track,
    sample_topics,
    sample_enrollments
):
    """Test topic performance aggregation."""
    from app.modules.domains import analytics_service

    track, levels = sample_track
    result = await analytics_service.get_topic_performance(track.id, None, db_session)

    # Should return topics from all levels
    assert len(result) >= 3  # At least the 3 topics we created

    # Each topic should have the required fields
    for topic_data in result:
        assert 'topic_id' in topic_data
        assert 'topic_name' in topic_data
        assert 'level_id' in topic_data
        assert 'avg_accuracy' in topic_data
        assert topic_data['avg_accuracy'] >= 0.0
        assert topic_data['avg_accuracy'] <= 1.0


@pytest.mark.asyncio
async def test_get_difficulty_performance(
    db_session,
    sample_track,
    sample_enrollments
):
    """Test difficulty performance aggregation."""
    from app.modules.domains import analytics_service

    track, levels = sample_track
    result = await analytics_service.get_difficulty_performance(track.id, db_session)

    # Result can be empty if no questions have been attempted
    assert isinstance(result, list)

    # If we have data, validate structure
    for difficulty_data in result:
        assert 'difficulty' in difficulty_data
        assert difficulty_data['difficulty'] in ['easy', 'medium', 'hard']
        assert 'total_questions' in difficulty_data
        assert 'total_correct' in difficulty_data
        assert 'accuracy' in difficulty_data
        assert difficulty_data['accuracy'] >= 0.0
        assert difficulty_data['accuracy'] <= 1.0


@pytest.mark.asyncio
async def test_get_student_report_all_8_levels(
    db_session,
    sample_track,
    sample_students,
    sample_enrollments,
    sample_level_progress
):
    """Test student report includes all 8 levels."""
    from app.modules.domains import analytics_service

    track, levels = sample_track
    student = sample_students[0]

    result = await analytics_service.get_student_report(student.id, track.id, db_session)

    # Should return all 8 levels
    assert len(result['level_details']) == 8

    # All levels should have level_no 1-8
    level_nos = [detail['level_no'] for detail in result['level_details']]
    assert sorted(level_nos) == list(range(1, 9))

    # Check student info
    assert result['student_id'] == student.id
    assert result['curr_sem'] == student.curr_sem
    assert result['track_id'] == track.id
    assert result['is_blocked'] == False


@pytest.mark.asyncio
async def test_list_students_for_track_with_filters(
    db_session,
    sample_track,
    sample_students,
    sample_enrollments
):
    """Test student list with filters and pagination."""
    from app.modules.domains import analytics_service

    track, levels = sample_track

    # Test with no filters
    students, total = await analytics_service.list_students_for_track(
        track.id, {}, page=1, page_size=10, db=db_session
    )

    assert total == 5
    assert len(students) == 5

    # Test with semester filter
    students_sem1, total_sem1 = await analytics_service.list_students_for_track(
        track.id, {'curr_sem': 1}, page=1, page_size=10, db=db_session
    )

    assert total_sem1 == 1
    assert students_sem1[0]['curr_sem'] == 1

    # Test with blocked filter
    students_blocked, total_blocked = await analytics_service.list_students_for_track(
        track.id, {'is_blocked': True}, page=1, page_size=10, db=db_session
    )

    assert total_blocked == 1


# ═══════════════════════════════════════════════════════════════════════════
# INTEGRATION TESTS - Router/API
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_domain_overview_endpoint_admin(
    client,
    admin_user,
    sample_track,
    sample_enrollments
):
    """Test admin can access domain overview."""
    from app.core import security

    track, levels = sample_track
    token, _ = security.create_access_token(
        user_id=admin_user.id,
        roles=admin_user.role_names,
        token_version=admin_user.token_version
    )

    response = await client.get(
        f"/api/v1/domains/{track.id}/analytics/overview",
        headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 200
    data = response.json()
    assert data['track_id'] == track.id
    assert data['total_students'] == 5


@pytest.mark.asyncio
async def test_domain_overview_endpoint_domain_owner(
    client,
    domain_owner_user,
    sample_track,
    sample_enrollments
):
    """Test domain owner can access their track analytics."""
    from app.core import security

    track, levels = sample_track
    token, _ = security.create_access_token(
        user_id=domain_owner_user.id,
        roles=domain_owner_user.role_names,
        token_version=domain_owner_user.token_version
    )

    response = await client.get(
        f"/api/v1/domains/{track.id}/analytics/overview",
        headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 200
    data = response.json()
    assert data['track_id'] == track.id


@pytest.mark.asyncio
async def test_students_by_level_endpoint(
    client,
    admin_user,
    sample_track,
    sample_enrollments,
    sample_level_progress
):
    """Test students by level endpoint."""
    from app.core import security

    track, levels = sample_track
    token, _ = security.create_access_token(
        user_id=admin_user.id,
        roles=admin_user.role_names,
        token_version=admin_user.token_version
    )

    response = await client.get(
        f"/api/v1/domains/{track.id}/analytics/students/by-level",
        headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) == 8  # All 8 levels


@pytest.mark.asyncio
async def test_students_by_semester_endpoint(
    client,
    admin_user,
    sample_track,
    sample_enrollments
):
    """Test students by semester endpoint."""
    from app.core import security

    track, levels = sample_track
    token, _ = security.create_access_token(
        user_id=admin_user.id,
        roles=admin_user.role_names,
        token_version=admin_user.token_version
    )

    response = await client.get(
        f"/api/v1/domains/{track.id}/analytics/students/by-semester",
        headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) == 10  # All 10 semesters


@pytest.mark.asyncio
async def test_topic_performance_endpoint(
    client,
    admin_user,
    sample_track,
    sample_topics
):
    """Test topic performance endpoint."""
    from app.core import security

    track, levels = sample_track
    token, _ = security.create_access_token(
        user_id=admin_user.id,
        roles=admin_user.role_names,
        token_version=admin_user.token_version
    )

    response = await client.get(
        f"/api/v1/domains/{track.id}/analytics/topics/performance",
        headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)


@pytest.mark.asyncio
async def test_student_report_endpoint(
    client,
    admin_user,
    sample_track,
    sample_students,
    sample_enrollments,
    sample_level_progress
):
    """Test student report endpoint."""
    from app.core import security

    track, levels = sample_track
    student = sample_students[0]
    token, _ = security.create_access_token(
        user_id=admin_user.id,
        roles=admin_user.role_names,
        token_version=admin_user.token_version
    )

    response = await client.get(
        f"/api/v1/domains/{track.id}/analytics/students/{student.id}/report",
        headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 200
    data = response.json()
    assert data['student_id'] == student.id
    assert len(data['level_details']) == 8


@pytest.mark.asyncio
async def test_student_list_endpoint_with_pagination(
    client,
    admin_user,
    sample_track,
    sample_enrollments
):
    """Test student list endpoint with pagination."""
    from app.core import security

    track, levels = sample_track
    token, _ = security.create_access_token(
        user_id=admin_user.id,
        roles=admin_user.role_names,
        token_version=admin_user.token_version
    )

    response = await client.get(
        f"/api/v1/domains/{track.id}/analytics/students?page=1&page_size=2",
        headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 200
    data = response.json()
    assert data['total'] == 5
    assert len(data['students']) == 2
    assert data['page'] == 1
    assert data['page_size'] == 2


@pytest.mark.asyncio
async def test_unauthorized_access_denied(
    client,
    sample_track,
    sample_students
):
    """Test unauthorized user cannot access analytics."""
    from app.core import security

    track, levels = sample_track
    # Create token for a regular student
    student_user_id = sample_students[0].user_id
    token, _ = security.create_access_token(
        user_id=student_user_id,
        roles=["student"],
        token_version=0
    )

    response = await client.get(
        f"/api/v1/domains/{track.id}/analytics/overview",
        headers={"Authorization": f"Bearer {token}"}
    )

    # Should be forbidden (students don't have domain owner roles)
    assert response.status_code == 403
