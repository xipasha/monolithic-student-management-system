#!/usr/bin/env python3
"""Create the least-privilege login for the courses PostgreSQL schema."""

import os
import sys
from pathlib import Path

import psycopg2
from psycopg2 import sql

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    database_url = os.environ.get("COURSES_ADMIN_DATABASE_URL")
    role = os.environ.get("COURSES_DATABASE_ROLE", "courses_service")
    password = os.environ.get("COURSES_DATABASE_PASSWORD")
    schema = os.environ.get("COURSES_DATABASE_SCHEMA", "courses")
    if not database_url or not password:
        raise SystemExit("Set COURSES_ADMIN_DATABASE_URL and COURSES_DATABASE_PASSWORD.")

    with psycopg2.connect(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {} AUTHORIZATION CURRENT_USER").format(sql.Identifier(schema)))
            cursor.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,))
            if cursor.fetchone():
                cursor.execute(
                    sql.SQL("ALTER ROLE {} LOGIN PASSWORD {}").format(
                        sql.Identifier(role), sql.Literal(password)
                    )
                )
            else:
                cursor.execute(
                    sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(
                        sql.Identifier(role), sql.Literal(password)
                    )
                )
            cursor.execute(
                sql.SQL("ALTER ROLE {} IN DATABASE {} SET search_path TO {}").format(
                    sql.Identifier(role), sql.Identifier(os.environ.get("PGDATABASE", "sms")),
                    sql.Identifier(schema),
                )
            )
            cursor.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                sql.Identifier(os.environ.get("PGDATABASE", "sms")), sql.Identifier(role)
            ))
            cursor.execute(sql.SQL("GRANT USAGE ON SCHEMA {} TO {}").format(
                sql.Identifier(schema), sql.Identifier(role)
            ))
            cursor.execute(sql.SQL("REVOKE ALL ON ALL TABLES IN SCHEMA {} FROM {}").format(
                sql.Identifier(schema), sql.Identifier(role)
            ))
            cursor.execute(sql.SQL(
                "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA {} TO {}"
            ).format(sql.Identifier(schema), sql.Identifier(role)))
            cursor.execute(sql.SQL(
                "GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA {} TO {}"
            ).format(sql.Identifier(schema), sql.Identifier(role)))
    print(f"Provisioned database role '{role}' with access limited to schema '{schema}'.")


if __name__ == "__main__":
    main()
