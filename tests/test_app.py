
import sqlite3

import pytest
from werkzeug.security import generate_password_hash

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
        # Create the database tables before inserting test data.
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
            "SELECT * FROM courses WHERE course_code = ?",
            ("CS101",),
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
            "SELECT * FROM students WHERE student_number = ?",
            ("ST2001",),
        ).fetchone()

    assert student is not None
    assert student["first_name"] == "Alice"
