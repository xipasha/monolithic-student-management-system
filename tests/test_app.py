import os

import pytest
from werkzeug.security import generate_password_hash

os.environ.setdefault("SECRET_KEY", "test-import-secret-key")

import app as application


@pytest.fixture
def client(tmp_path, monkeypatch):
    """Use an isolated SQLite database for every test."""
    test_db = tmp_path / "test_sms.db"

    monkeypatch.setattr(application, "DATABASE", test_db)
    monkeypatch.setenv("ADMIN_USERNAME", "testadmin")
    monkeypatch.setenv("ADMIN_PASSWORD", "TestAdminPassword123!")

    application.app.config.update(
        TESTING=True,
        SECRET_KEY="test-secret-key",
    )

    with application.app.test_client() as client:
        yield client


def login(client, username, password):
    return client.post(
        "/login",
        data={"login_id": username, "password": password},
        follow_redirects=False,
    )


def create_student_record(student_number="ST1001", password="StudentPass123!"):
    """Create a student directly in the isolated test database."""
    with application.app.app_context():
        application.init_db()
        db = application.get_db()
        cursor = db.execute(
            """
            INSERT INTO users
                (username, password_hash, role, must_change_password, active)
            VALUES (?, ?, 'student', 0, 1)
            """,
            (
                f"student_{student_number}",
                generate_password_hash(password),
            ),
        )
        user_id = cursor.lastrowid
        db.execute(
            """
            INSERT INTO students
                (user_id, student_number, first_name, last_name, email)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                user_id,
                student_number,
                "Test",
                "Student",
                f"{student_number.lower()}@example.com",
            ),
        )
        db.commit()


def student_id(student_number):
    with application.app.app_context():
        return application.get_db().execute(
            "SELECT id FROM students WHERE student_number = ?",
            (student_number,),
        ).fetchone()["id"]


def test_login_page_loads(client):
    response = client.get("/login")
    assert response.status_code == 200


def test_admin_can_log_in(client):
    response = login(client, "testadmin", "TestAdminPassword123!")
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/admin")


def test_admin_login_rejects_wrong_password(client):
    response = login(client, "testadmin", "wrong-password")
    assert response.status_code == 200
    assert b"Invalid" in response.data


def test_student_can_log_in(client):
    create_student_record()
    response = login(client, "ST1001", "StudentPass123!")
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/student")


def test_unauthenticated_user_cannot_access_admin(client):
    response = client.get("/admin")
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_student_cannot_access_admin(client):
    create_student_record()
    login(client, "ST1001", "StudentPass123!")
    response = client.get("/admin")
    assert response.status_code == 403


def test_admin_can_create_course(client):
    login(client, "testadmin", "TestAdminPassword123!")
    response = client.post(
        "/admin/courses/create",
        data={
            "course_code": "cs101",
            "course_name": "Introduction to Computing",
            "description": "A test course",
        },
    )
    assert response.status_code == 302
    with application.app.app_context():
        course = application.get_db().execute(
            "SELECT * FROM courses WHERE course_code = ?", ("CS101",)
        ).fetchone()
    assert course is not None
    assert course["course_name"] == "Introduction to Computing"
    assert course["description"] == "A test course"


def test_admin_can_create_student(client):
    login(client, "testadmin", "TestAdminPassword123!")
    response = client.post(
        "/admin/students/create",
        data={
            "student_number": "ST2001",
            "first_name": "Alice",
            "last_name": "Example",
            "email": "alice@example.com",
        },
    )
    assert response.status_code == 302
    assert "/admin/student-credentials" in response.headers["Location"]
    with application.app.app_context():
        student = application.get_db().execute(
            "SELECT * FROM students WHERE student_number = ?", ("ST2001",)
        ).fetchone()
    assert student is not None
    assert student["first_name"] == "Alice"


def test_admin_can_activate_and_deactivate_student(client):
    create_student_record("ST2002")
    login(client, "testadmin", "TestAdminPassword123!")
    record_id = student_id("ST2002")

    response = client.post(f"/admin/students/{record_id}/toggle")
    assert response.status_code == 302
    with application.app.app_context():
        active = application.get_db().execute(
            "SELECT u.active FROM students s JOIN users u ON u.id = s.user_id "
            "WHERE s.id = ?", (record_id,)
        ).fetchone()["active"]
    assert active == 0

    client.post(f"/admin/students/{record_id}/toggle")
    with application.app.app_context():
        active = application.get_db().execute(
            "SELECT u.active FROM students s JOIN users u ON u.id = s.user_id "
            "WHERE s.id = ?", (record_id,)
        ).fetchone()["active"]
    assert active == 1


def test_admin_can_reset_student_password(client):
    create_student_record("ST2003")
    login(client, "testadmin", "TestAdminPassword123!")
    response = client.post(f"/admin/students/{student_id('ST2003')}/reset-password")
    assert response.status_code == 302
    assert "/admin/student-credentials" in response.headers["Location"]
    with application.app.app_context():
        user = application.get_db().execute(
            "SELECT must_change_password FROM users WHERE username = ?",
            ("student_ST2003",),
        ).fetchone()
    assert user["must_change_password"] == 1


def test_admin_can_delete_course(client):
    login(client, "testadmin", "TestAdminPassword123!")
    client.post(
        "/admin/courses/create",
        data={"course_code": "CS102", "course_name": "Testing"},
    )
    with application.app.app_context():
        course_id = application.get_db().execute(
            "SELECT id FROM courses WHERE course_code = ?", ("CS102",)
        ).fetchone()["id"]
    response = client.post(f"/admin/courses/{course_id}/delete")
    assert response.status_code == 302
    with application.app.app_context():
        assert application.get_db().execute(
            "SELECT id FROM courses WHERE id = ?", (course_id,)
        ).fetchone() is None


def test_admin_can_enrol_and_remove_student(client):
    create_student_record("ST2004")
    login(client, "testadmin", "TestAdminPassword123!")
    client.post(
        "/admin/courses/create",
        data={"course_code": "CS103", "course_name": "Cloud Applications"},
    )
    with application.app.app_context():
        course_id = application.get_db().execute(
            "SELECT id FROM courses WHERE course_code = ?", ("CS103",)
        ).fetchone()["id"]
    response = client.post(
        "/admin/enrolments/create",
        data={"student_id": student_id("ST2004"), "course_id": course_id},
    )
    assert response.status_code == 302
    with application.app.app_context():
        enrolment_id = application.get_db().execute(
            "SELECT id FROM enrolments WHERE course_id = ?", (course_id,)
        ).fetchone()["id"]
    response = client.post(f"/admin/enrolments/{enrolment_id}/delete")
    assert response.status_code == 302


def test_student_can_view_profile_and_courses(client):
    create_student_record("ST2005")
    with application.app.app_context():
        db = application.get_db()
        record_id = student_id("ST2005")
        db.execute(
            "INSERT INTO courses (course_code, course_name, description) "
            "VALUES (?, ?, ?)",
            ("CS104", "Student Experience", ""),
        )
        course_id = db.execute(
            "SELECT id FROM courses WHERE course_code = ?", ("CS104",)
        ).fetchone()["id"]
        db.execute(
            "INSERT INTO enrolments (student_id, course_id) VALUES (?, ?)",
            (record_id, course_id),
        )
        db.commit()
    login(client, "ST2005", "StudentPass123!")
    response = client.get("/student")
    assert response.status_code == 200
    assert b"ST2005" in response.data
    assert b"Student Experience" in response.data


def test_student_must_change_password_before_dashboard(client):
    with application.app.app_context():
        application.init_db()
        db = application.get_db()
        cursor = db.execute(
            "INSERT INTO users (username, password_hash, role, must_change_password) "
            "VALUES (?, ?, 'student', 1)",
            ("student_ST2006", generate_password_hash("TemporaryPass123!")),
        )
        db.execute(
            "INSERT INTO students "
            "(user_id, student_number, first_name, last_name, email) "
            "VALUES (?, ?, ?, ?, ?)",
            (cursor.lastrowid, "ST2006", "Change", "Me", "change@example.com"),
        )
        db.commit()
    login(client, "ST2006", "TemporaryPass123!")
    response = client.get("/student")
    assert response.status_code == 302
    assert "/change-password" in response.headers["Location"]
    response = client.post(
        "/change-password",
        data={
            "password": "NewStudentPass123!",
            "confirm_password": "NewStudentPass123!",
        },
    )
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/")
