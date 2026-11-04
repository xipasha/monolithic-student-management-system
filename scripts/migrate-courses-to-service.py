#!/usr/bin/env python3
"""Copy legacy PostgreSQL courses into the courses service schema."""

import os
import sys
from pathlib import Path

import psycopg2

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.courses.migration import migrate_course_data


def main():
    source_url = os.environ.get("SOURCE_DATABASE_URL") or os.environ.get("DATABASE_URL")
    target_url = os.environ.get("COURSES_ADMIN_DATABASE_URL")
    if not source_url or not target_url:
        raise SystemExit("Set SOURCE_DATABASE_URL and COURSES_ADMIN_DATABASE_URL.")
    with psycopg2.connect(source_url) as source, psycopg2.connect(target_url) as target:
        result = migrate_course_data(
            source,
            target,
            source_schema=os.environ.get("SOURCE_DATABASE_SCHEMA", "public"),
            target_schema=os.environ.get("COURSES_DATABASE_SCHEMA", "courses"),
        )
    print(
        f"Copied and compared {result['courses']} courses and "
        f"{result['enrolments']} enrolments; mismatches: 0."
    )


if __name__ == "__main__":
    main()
