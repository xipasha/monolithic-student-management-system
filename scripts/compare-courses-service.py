#!/usr/bin/env python3
"""Compare source and courses-service records; exit non-zero on any mismatch."""

import os
import sys
from pathlib import Path

import psycopg2

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.courses.migration import compare_course_data


def main():
    source_url = os.environ.get("SOURCE_DATABASE_URL") or os.environ.get("DATABASE_URL")
    target_url = os.environ.get("COURSES_ADMIN_DATABASE_URL")
    if not source_url or not target_url:
        print("Set SOURCE_DATABASE_URL and COURSES_ADMIN_DATABASE_URL.", file=sys.stderr)
        return 2
    with psycopg2.connect(source_url) as source, psycopg2.connect(target_url) as target:
        mismatches = compare_course_data(
            source,
            target,
            source_schema=os.environ.get("SOURCE_DATABASE_SCHEMA", "public"),
            target_schema=os.environ.get("COURSES_DATABASE_SCHEMA", "courses"),
        )
    if mismatches:
        for mismatch in mismatches:
            print(mismatch)
        print(f"Comparison failed: {len(mismatches)} mismatch(es).", file=sys.stderr)
        return 1
    print("Course and enrolment rows match by ID and field value; mismatches: 0.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
