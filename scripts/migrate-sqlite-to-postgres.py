#!/usr/bin/env python3
"""Copy an existing SMS SQLite database into an empty PostgreSQL database."""

import os
import sqlite3
import sys
from pathlib import Path

import psycopg2

TABLES = {
    "users": """CREATE TABLE IF NOT EXISTS users (
        id SERIAL PRIMARY KEY, username TEXT UNIQUE, password_hash TEXT NOT NULL,
        role TEXT NOT NULL CHECK(role IN ('admin', 'student')),
        must_change_password INTEGER NOT NULL DEFAULT 0,
        active INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP::text
    )""",
    "students": """CREATE TABLE IF NOT EXISTS students (
        id SERIAL PRIMARY KEY, user_id INTEGER UNIQUE NOT NULL REFERENCES users(id),
        student_number TEXT UNIQUE NOT NULL, first_name TEXT NOT NULL,
        last_name TEXT NOT NULL, email TEXT NOT NULL
    )""",
    "courses": """CREATE TABLE IF NOT EXISTS courses (
        id SERIAL PRIMARY KEY, course_code TEXT UNIQUE NOT NULL,
        course_name TEXT NOT NULL, description TEXT NOT NULL DEFAULT ''
    )""",
    "enrolments": """CREATE TABLE IF NOT EXISTS enrolments (
        id SERIAL PRIMARY KEY,
        student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
        course_id INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
        enrolled_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP::text,
        UNIQUE(student_id, course_id)
    )""",
}


def main():
    source = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("instance/sms.db")
    database_url = os.environ.get("DATABASE_URL")
    if not source.is_file():
        raise SystemExit(f"SQLite database does not exist: {source}")
    if not database_url:
        raise SystemExit("Set DATABASE_URL from a secure source; it will not be printed.")

    sqlite_db = sqlite3.connect(source)
    sqlite_db.row_factory = sqlite3.Row
    postgres_db = psycopg2.connect(database_url)
    try:
        with postgres_db:
            with postgres_db.cursor() as cursor:
                for ddl in TABLES.values():
                    cursor.execute(ddl)
                occupied = {}
                for table in TABLES:
                    cursor.execute(f"SELECT COUNT(*) FROM {table}")
                    occupied[table] = cursor.fetchone()[0]
                if any(occupied.values()):
                    raise RuntimeError("Target PostgreSQL database is not empty; refusing to merge data.")

                copied = {}
                for table in TABLES:
                    source_columns = [row["name"] for row in sqlite_db.execute(
                        f"PRAGMA table_info({table})"
                    )]
                    cursor.execute(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_schema = current_schema() AND table_name = %s "
                        "ORDER BY ordinal_position", (table,)
                    )
                    destination_columns = [row[0] for row in cursor.fetchall()]
                    if source_columns != destination_columns:
                        raise RuntimeError(
                            f"Schema mismatch in {table}: SQLite={source_columns}, PostgreSQL={destination_columns}"
                        )
                    rows = sqlite_db.execute(
                        f"SELECT {', '.join(source_columns)} FROM {table} ORDER BY id"
                    ).fetchall()
                    if rows:
                        columns_sql = ", ".join(source_columns)
                        marks = ", ".join(["%s"] * len(source_columns))
                        cursor.executemany(
                            f"INSERT INTO {table} ({columns_sql}) VALUES ({marks})",
                            [tuple(row[column] for column in source_columns) for row in rows],
                        )
                    copied[table] = len(rows)

                for table in TABLES:
                    cursor.execute(
                        f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), "
                        f"COALESCE(MAX(id), 1), MAX(id) IS NOT NULL) FROM {table}"
                    )
        print("SQLite data copied successfully:")
        for table, count in copied.items():
            print(f"  {table}: {count} rows")
    finally:
        sqlite_db.close()
        postgres_db.close()


if __name__ == "__main__":
    main()
