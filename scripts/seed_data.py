"""Development seed data. Run from the project root after `alembic upgrade head`:

    python -m scripts.seed_data

Safe to run more than once: existing accounts and the demo track are left as they are.
Accounts (development only):
    admin@college.edu     / admin123     admin
    student@college.edu   / student123   student
    fullstack@college.edu / fullstack123 fullstack_domain_owner (limited to the Web Development track)
"""

import asyncio
import sys

from sqlalchemy import select

from app.core.config import settings
from app.core.database import AsyncSessionLocal, engine
from app.core.security import hash_password
from app.modules.auth.models import RoleName
from app.modules.auth.service import ensure_roles, get_roles, new_user, set_user_roles
from app.modules.domains.models import Level, Subtopic, Topic, Track
from app.modules.users.models import AcademicYear, Department, DomainIncharge, Student, User


async def main() -> None:
    if settings.app_env == "production":
        sys.exit("Refusing to create demo accounts in production.")
    print("Seeding database...")

    async with AsyncSessionLocal() as session:
        await ensure_roles(session)

        # Department & academic year
        dept = await session.scalar(select(Department).where(Department.code == "CSE"))
        if dept is None:
            dept = Department(code="CSE", name="Computer Science")
            session.add(dept)
        year = await session.scalar(select(AcademicYear).where(AcademicYear.label == "2026-2027"))
        if year is None:
            year = AcademicYear(label="2026-2027")
            session.add(year)
        await session.flush()

        # Track -> Level -> Topic -> Subtopic
        track = await session.scalar(select(Track).where(Track.name == "Web Development"))
        if track is None:
            track = Track(name="Web Development", description="Fullstack web dev track", is_active=True)
            session.add(track)
            await session.flush()

            level1 = Level(track_id=track.id, level_no=1, name="Beginner", description="HTML, CSS, JS basics")
            session.add(level1)
            await session.flush()

            topic1 = Topic(level_id=level1.id, name="HTML5", description="Semantic HTML", sequence_no=1)
            topic2 = Topic(level_id=level1.id, name="CSS3", description="Styling and layout", sequence_no=2)
            session.add_all([topic1, topic2])
            await session.flush()

            subtopic1 = Subtopic(topic_id=topic1.id, name="Forms", description="Input elements", sequence_no=1)
            subtopic2 = Subtopic(topic_id=topic1.id, name="Flexbox", description="CSS Flex layout", sequence_no=1)
            session.add_all([subtopic1, subtopic2])

        # Limit the Full Stack domain owner role to this track (unless an admin already linked it).
        (fullstack_role,) = await get_roles(session, [RoleName.FULLSTACK_DOMAIN_OWNER])
        if fullstack_role.track_id is None:
            fullstack_role.track_id = track.id

        accounts = [
            ("admin", "admin@college.edu", "admin123", RoleName.ADMIN),
            ("student", "student@college.edu", "student123", RoleName.STUDENT),
            ("fullstack", "fullstack@college.edu", "fullstack123", RoleName.FULLSTACK_DOMAIN_OWNER),
        ]
        for username, email, password, role in accounts:
            if await session.scalar(select(User.id).where(User.email == email)):
                continue
            user = new_user(
                username=username,
                email=email,
                full_name=username.title(),
                password_hash=await hash_password(password),
            )
            set_user_roles(user, await get_roles(session, [role]))
            if role == RoleName.STUDENT:
                user.student = Student(
                    department_id=dept.id,
                    academic_year_id=year.id,
                    roll_number="CS26001",
                    reg_num="DEMO0001",
                    curr_sem=3,
                )
            if role == RoleName.FULLSTACK_DOMAIN_OWNER:
                user.track_assignments.append(DomainIncharge(track=track, emp_id="EMP001"))
            session.add(user)

        await session.commit()
    await engine.dispose()
    print("Data seeded successfully!")


if __name__ == "__main__":
    asyncio.run(main())
