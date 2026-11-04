#!/usr/bin/env python3
"""Exercise course create, enrolment, and student view through the monolith."""

import html
import os
import re
import secrets
import sys
from http.cookiejar import CookieJar
from urllib.parse import urlencode, urljoin, urlparse
from urllib.request import HTTPCookieProcessor, Request, build_opener

import psycopg2


def main():
    base_url = os.environ["WEBAPP_URL"].rstrip("/")
    correlation_id = os.environ["CUTOVER_CORRELATION_ID"]
    run_id = os.environ["GITHUB_RUN_ID"]
    run_attempt = os.environ["GITHUB_RUN_ATTEMPT"]
    admin_password = os.environ["ADMIN_PASSWORD"]
    student_number = f"CUTOVER{run_id}{run_attempt}"
    course_code = f"CUT{run_id[-7:]}{run_attempt}"
    course_name = f"Cutover Verification {run_id}"
    admin = build_opener(HTTPCookieProcessor(CookieJar()))
    student = build_opener(HTTPCookieProcessor(CookieJar()))
    course_id = None

    def request(opener, path, values=None):
        data = urlencode(values).encode() if values is not None else None
        headers = {"X-Correlation-ID": correlation_id}
        if data is not None:
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        req = Request(urljoin(base_url + "/", path.lstrip("/")), data=data, headers=headers)
        with opener.open(req, timeout=30) as response:
            body = response.read().decode()
            returned_correlation = response.headers.get("X-Correlation-ID")
            if returned_correlation != correlation_id:
                raise RuntimeError(
                    f"Correlation ID mismatch on {path}: {returned_correlation!r}"
                )
            return urlparse(response.geturl()).path, body

    try:
        path, _ = request(admin, "/login", {"login_id": "admin", "password": admin_password})
        if path != "/admin":
            raise RuntimeError("Administrator login failed during cutover E2E.")

        credentials_path, credentials_page = request(
            admin,
            "/admin/students/create",
            {
                "student_number": student_number,
                "first_name": "Cutover",
                "last_name": "Verification",
                "email": f"{student_number.lower()}@example.invalid",
            },
        )
        if credentials_path != "/admin/student-credentials":
            raise RuntimeError("Temporary student creation failed.")
        password_match = re.search(
            r"Temporary password:</strong>\s*<code>([^<]+)</code>", credentials_page
        )
        if not password_match:
            raise RuntimeError("Temporary student password was not returned.")
        temporary_password = html.unescape(password_match.group(1))

        request(admin, "/admin/courses/create", {
            "course_code": course_code,
            "course_name": course_name,
            "description": "Temporary end-to-end cutover verification",
        })
        _, admin_page = request(admin, "/admin")
        course_match = re.search(
            rf"<td>{re.escape(course_code)}</td>.*?action=\"/admin/courses/(\d+)/delete\"",
            admin_page,
            re.DOTALL,
        )
        student_match = re.search(
            rf"<option value=\"(\d+)\">\s*{re.escape(student_number)}\s",
            admin_page,
        )
        if not course_match or not student_match:
            raise RuntimeError("Created course or student was missing from the admin dashboard.")
        course_id = int(course_match.group(1))
        student_id = int(student_match.group(1))

        request(admin, "/admin/enrolments/create", {
            "student_id": student_id,
            "course_id": course_id,
        })

        student_path, _ = request(
            student, "/login", {"login_id": student_number, "password": temporary_password}
        )
        if student_path != "/change-password":
            raise RuntimeError("Temporary student login failed.")
        new_password = secrets.token_urlsafe(18)
        student_path, _ = request(student, "/change-password", {
            "password": new_password,
            "confirm_password": new_password,
        })
        if student_path != "/student":
            raise RuntimeError("Temporary student password change failed.")
        _, student_page = request(student, "/student")
        if course_code not in student_page or course_name not in student_page:
            raise RuntimeError("Student dashboard did not show the newly enrolled course.")

        print(f"e2e_course={course_code} course_id={course_id}")
        print(f"e2e_student={student_number}")
        print(f"e2e_correlation_id={correlation_id}")
        print("Course creation, student enrolment, and student course view passed.")
    finally:
        cleanup_errors = []
        if course_id is not None:
            try:
                request(admin, f"/admin/courses/{course_id}/delete", {})
            except Exception as exc:
                cleanup_errors.append(f"course API cleanup: {exc}")
        try:
            with psycopg2.connect(os.environ["COURSES_ADMIN_DATABASE_URL"]) as target:
                with target.cursor() as cursor:
                    cursor.execute(
                        "DELETE FROM courses WHERE course_code = %s RETURNING id", (course_code,)
                    )
                    removed = cursor.fetchone()
                    if removed:
                        cursor.execute("DELETE FROM enrolments WHERE course_id = %s", (removed[0],))
        except Exception as exc:
            cleanup_errors.append(f"course database cleanup: {exc}")
        try:
            with psycopg2.connect(os.environ["DATABASE_URL"]) as source:
                with source.cursor() as cursor:
                    cursor.execute(
                        "SELECT id FROM students WHERE student_number = %s", (student_number,)
                    )
                    row = cursor.fetchone()
                    if row:
                        cursor.execute("DELETE FROM enrolments WHERE student_id = %s", (row[0],))
                        cursor.execute("DELETE FROM students WHERE id = %s", (row[0],))
                    cursor.execute("DELETE FROM users WHERE username = %s", (f"student_{student_number}",))
        except Exception as exc:
            cleanup_errors.append(f"student database cleanup: {exc}")
        if cleanup_errors:
            raise RuntimeError("; ".join(cleanup_errors))
        print("Temporary cutover student, course, and enrolment cleanup completed.")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"Cutover E2E failed: {error}", file=sys.stderr)
        raise
