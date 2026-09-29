import pytest

from app.core.config import settings
from app.modules.auth.tests.helpers import API
from app.modules.users.models import AcademicYear

pytestmark = pytest.mark.asyncio

REGISTER = f"{API}/auth/register"


def payload(department_id: int, **overrides: object) -> dict[str, object]:
    data: dict[str, object] = {
        "username": "Arun.K",
        "email": "Arun.K@College.edu",
        "full_name": "  Arun Kumar ",
        "phone": "98765 43210",
        "password": "Str0ng-Passw0rd",
        "reg_num": "312324104001",
        "roll_number": "24cs001",
        "department_id": department_id,
        "curr_sem": 3,
    }
    data.update(overrides)
    return data


async def test_student_can_register(client, department):
    response = await client.post(REGISTER, json=payload(department.id))

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["username"] == "arun.k"  # stored lowercase
    assert body["email"] == "arun.k@college.edu"
    assert body["full_name"] == "Arun Kumar"
    assert body["phone"] == "9876543210"
    assert body["roles"] == ["student"]
    assert body["must_change_password"] is False
    assert body["student"]["reg_num"] == "312324104001"
    assert body["student"]["roll_number"] == "24CS001"
    assert body["student"]["department"]["code"] == "CSE"
    assert body["student"]["curr_sem"] == 3
    assert body["student"]["year"] == 2  # derived from the semester, not stored
    assert "password_hash" not in body
    assert "Str0ng-Passw0rd" not in response.text


async def test_registration_with_an_academic_year(client, department, db):
    year = AcademicYear(label="2026-2027")
    db.add(year)
    await db.commit()

    ok = await client.post(REGISTER, json=payload(department.id, academic_year_id=year.id))
    assert ok.status_code == 201
    assert ok.json()["student"]["academic_year_id"] == year.id

    unknown = await client.post(
        REGISTER,
        json=payload(
            department.id,
            academic_year_id=year.id + 99,
            username="someone",
            email="someone@college.edu",
            reg_num="312324104999",
            roll_number="24CS999",
        ),
    )
    assert unknown.status_code == 400
    assert unknown.json()["code"] == "ACADEMIC_YEAR_NOT_FOUND"


async def test_registration_cannot_choose_a_role(client, department):
    """An extra "roles" field is ignored: self-registration always creates a student."""
    response = await client.post(REGISTER, json=payload(department.id, roles=["admin"], role="admin"))
    assert response.status_code == 201
    assert response.json()["roles"] == ["student"]


async def test_registered_student_can_log_in_with_username_or_email(client, department):
    await client.post(REGISTER, json=payload(department.id))

    for identifier in ("arun.k", "ARUN.K", "arun.k@college.edu"):
        response = await client.post(f"{API}/auth/login", data={"username": identifier, "password": "Str0ng-Passw0rd"})
        assert response.status_code == 200, identifier
        assert response.json()["user"]["roles"] == ["student"]


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("username", "ARUN.K", "USERNAME_TAKEN"),
        ("email", "arun.k@COLLEGE.edu", "EMAIL_TAKEN"),
        ("reg_num", "312324104001", "REG_NUM_TAKEN"),
        ("roll_number", "24cs001", "ROLL_NUMBER_TAKEN"),
    ],
)
async def test_duplicate_details_are_rejected(client, department, field, value, code):
    assert (await client.post(REGISTER, json=payload(department.id))).status_code == 201
    other = payload(
        department.id, username="someone", email="someone@college.edu", reg_num="312324104999", roll_number="24CS999"
    )
    other[field] = value

    response = await client.post(REGISTER, json=other)

    assert response.status_code == 409
    assert response.json()["code"] == code


async def test_unknown_department_is_rejected(client, department):
    response = await client.post(REGISTER, json=payload(department.id + 999))
    assert response.status_code == 400
    assert response.json()["code"] == "DEPARTMENT_NOT_FOUND"


@pytest.mark.parametrize(
    "overrides",
    [
        {"password": "short"},
        {"password": "312324104001"},  # same as the register number
        {"username": "has@sign"},
        {"email": "not-an-email"},
        {"phone": "12345"},
        {"curr_sem": 0},
        {"curr_sem": 11},
    ],
)
async def test_invalid_input_is_rejected(client, department, overrides):
    response = await client.post(REGISTER, json=payload(department.id, **overrides))
    assert response.status_code == 422, overrides
    assert response.json()["code"] == "VALIDATION_ERROR"


async def test_registration_can_be_closed(client, department, monkeypatch):
    monkeypatch.setattr(settings, "allow_student_self_registration", False)
    response = await client.post(REGISTER, json=payload(department.id))
    assert response.status_code == 403
    assert response.json()["code"] == "REGISTRATION_CLOSED"
