"""PostgreSQL operations for the isolated courses schema."""

import os

import psycopg2
from psycopg2 import sql
from psycopg2.extras import RealDictCursor


def connect(database_url=None, schema=None):
    database_url = database_url or os.environ["DATABASE_URL"]
    connection = psycopg2.connect(database_url, cursor_factory=RealDictCursor)
    if schema or os.environ.get("COURSES_DATABASE_SCHEMA", "courses"):
        with connection.cursor() as cursor:
            cursor.execute(
                sql.SQL("SET search_path TO {}").format(
                    sql.Identifier(schema or os.environ.get("COURSES_DATABASE_SCHEMA", "courses"))
                )
            )
    return connection


def fetch_courses(connection):
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT id, course_code, course_name, description "
            "FROM courses ORDER BY course_code"
        )
        return [dict(row) for row in cursor.fetchall()]


def create_course(connection, code, name, description):
    with connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO courses (course_code, course_name, description) "
            "VALUES (%s, %s, %s) RETURNING id, course_code, course_name, description",
            (code.strip().upper(), name.strip(), description.strip()),
        )
        course = dict(cursor.fetchone())
    connection.commit()
    return course


def get_course(connection, course_id):
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT id, course_code, course_name, description FROM courses WHERE id = %s",
            (course_id,),
        )
        row = cursor.fetchone()
        return dict(row) if row else None


def delete_course(connection, course_id):
    with connection.cursor() as cursor:
        cursor.execute("DELETE FROM courses WHERE id = %s", (course_id,))
    connection.commit()


def fetch_enrolments(connection):
    with connection.cursor() as cursor:
        cursor.execute(
            """SELECT e.id, e.course_id, e.student_number, e.enrolled_at,
                      c.course_code, c.course_name
               FROM enrolments e JOIN courses c ON c.id = e.course_id
               ORDER BY e.id DESC"""
        )
        return [dict(row) for row in cursor.fetchall()]


def create_enrolment(connection, course_id, student_number):
    with connection.cursor() as cursor:
        cursor.execute("SELECT id FROM courses WHERE id = %s", (course_id,))
        if not cursor.fetchone():
            return None, "unknown_course"
        cursor.execute(
            """INSERT INTO enrolments (course_id, student_number)
               VALUES (%s, %s)
               RETURNING id, course_id, student_number, enrolled_at""",
            (course_id, student_number),
        )
        enrolment = dict(cursor.fetchone())
    connection.commit()
    return enrolment, None


def delete_enrolment(connection, enrolment_id):
    with connection.cursor() as cursor:
        cursor.execute("DELETE FROM enrolments WHERE id = %s", (enrolment_id,))
    connection.commit()


def fetch_student_courses(connection, student_number):
    with connection.cursor() as cursor:
        cursor.execute(
            """SELECT c.id, c.course_code, c.course_name, c.description, e.enrolled_at
               FROM enrolments e JOIN courses c ON c.id = e.course_id
               WHERE e.student_number = %s ORDER BY c.course_code""",
            (student_number,),
        )
        return [dict(row) for row in cursor.fetchall()]


def fetch_course_students(connection, course_id):
    with connection.cursor() as cursor:
        cursor.execute(
            """SELECT id, student_number, enrolled_at FROM enrolments
               WHERE course_id = %s ORDER BY id""",
            (course_id,),
        )
        return [dict(row) for row in cursor.fetchall()]
