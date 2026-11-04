import os
import logging
import subprocess
import sys

import pytest

os.environ.setdefault("SECRET_KEY", "test-import-secret-key")

from courses_client import CoursesServiceUnavailable, request_courses_service
from services.courses import app as courses_module
from services.courses import storage


def test_courses_api_requires_bearer_token(monkeypatch):
    import psycopg2

    monkeypatch.setattr(courses_module, "TOKEN", "expected-token")
    monkeypatch.setattr(
        storage, "connect",
        lambda: (_ for _ in ()).throw(psycopg2.OperationalError("test database offline")),
    )
    client = courses_module.app.test_client()
    assert client.get("/api/courses").status_code == 401
    response = client.get(
        "/api/courses", headers={"Authorization": "Bearer expected-token"}
    )
    assert response.status_code == 503


def test_courses_service_logs_request_correlation_id(monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger="courses_service")
    monkeypatch.setattr(courses_module, "TOKEN", "expected-token")
    monkeypatch.setattr(storage, "fetch_courses", lambda _connection: [])
    monkeypatch.setattr(courses_module, "database", lambda: object())
    response = courses_module.app.test_client().get(
        "/api/courses",
        headers={
            "Authorization": "Bearer expected-token",
            "X-Correlation-ID": "course-log-correlation",
        },
    )
    assert response.status_code == 200
    assert response.headers["X-Correlation-ID"] == "course-log-correlation"
    assert '"correlation_id": "course-log-correlation"' in caplog.text


def test_courses_client_uses_three_second_timeout(monkeypatch):
    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self):
            return b"[]"

    def fake_urlopen(request, timeout):
        assert timeout == 3
        assert request.get_header("Authorization") == "Bearer token"
        return Response()

    monkeypatch.setenv("COURSES_SERVICE_URL", "https://courses.example.test")
    monkeypatch.setenv("COURSES_SERVICE_TOKEN", "token")
    monkeypatch.setattr("courses_client.urlopen", fake_urlopen)
    assert request_courses_service("GET", "/api/courses", correlation_id="abc")[1] == []


@pytest.mark.skipif(
    not os.environ.get("DATABASE_URL", "").startswith(("postgres://", "postgresql://")),
    reason="Migration and identity-sequence verification requires PostgreSQL.",
)
def test_migration_is_idempotent_and_next_course_uses_reseeded_sequence():
    import uuid

    import psycopg2
    from psycopg2 import sql
    from services.courses.migration import compare_course_data, migrate_course_data

    suffix = uuid.uuid4().hex[:12]
    source_schema = f"source_{suffix}"
    target_schema = f"target_{suffix}"
    database_url = os.environ["DATABASE_URL"]
    try:
        with psycopg2.connect(database_url) as source, psycopg2.connect(database_url) as target:
            with source.cursor() as cursor:
                cursor.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(source_schema)))
                cursor.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(source_schema)))
                cursor.execute("CREATE TABLE students (id INTEGER PRIMARY KEY, student_number TEXT UNIQUE NOT NULL)")
                cursor.execute("CREATE TABLE courses (id INTEGER PRIMARY KEY, course_code TEXT UNIQUE NOT NULL, course_name TEXT NOT NULL, description TEXT NOT NULL)")
                cursor.execute("CREATE TABLE enrolments (id INTEGER PRIMARY KEY, student_id INTEGER NOT NULL, course_id INTEGER NOT NULL, enrolled_at TEXT NOT NULL)")
                cursor.execute("INSERT INTO students VALUES (4, 'ST-MIGRATE')")
                cursor.execute("INSERT INTO courses VALUES (12, 'MIG101', 'Migrated course', 'copied')")
                cursor.execute("INSERT INTO enrolments VALUES (19, 4, 12, '2026-11-04 10:00:00')")
            with target.cursor() as cursor:
                cursor.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(target_schema)))

            expected = {"courses": 1, "enrolments": 1, "mismatches": []}
            assert migrate_course_data(source, target, source_schema, target_schema) == expected
            assert migrate_course_data(source, target, source_schema, target_schema) == expected
            assert compare_course_data(source, target, source_schema, target_schema) == []
            with target.cursor() as cursor:
                cursor.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(target_schema)))
                cursor.execute(
                    "INSERT INTO courses (course_code, course_name, description) "
                    "VALUES ('NEXT101', 'Created after migration', '') RETURNING id"
                )
                assert cursor.fetchone()[0] == 13
            mismatches = compare_course_data(source, target, source_schema, target_schema)
            assert [item["id"] for item in mismatches] == [13]
            environment = os.environ | {
                "SOURCE_DATABASE_URL": database_url,
                "COURSES_ADMIN_DATABASE_URL": database_url,
                "SOURCE_DATABASE_SCHEMA": source_schema,
                "COURSES_DATABASE_SCHEMA": target_schema,
            }
            result = subprocess.run(
                [sys.executable, "scripts/compare-courses-service.py"],
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )
            assert result.returncode == 1
    finally:
        with psycopg2.connect(database_url) as connection, connection.cursor() as cursor:
            cursor.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(target_schema)))
            cursor.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(source_schema)))
