"""HTTP API for courses and enrolments."""

import hmac
import json
import logging
import os
import re
import uuid

import psycopg2
from flask import Flask, g, jsonify, request

from services.courses import storage


app = Flask(__name__)
logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
TOKEN = os.environ.get("COURSES_SERVICE_TOKEN", "")


@app.before_request
def set_correlation_id():
    incoming = request.headers.get("X-Correlation-ID", "")
    g.correlation_id = incoming if re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", incoming) else str(uuid.uuid4())


@app.after_request
def add_correlation_id(response):
    response.headers["X-Correlation-ID"] = g.correlation_id
    logging.getLogger("courses_service").info(json.dumps({
        "event": "http_request",
        "method": request.method,
        "path": request.path,
        "status_code": response.status_code,
        "correlation_id": g.correlation_id,
    }))
    return response


@app.errorhandler(psycopg2.IntegrityError)
def integrity_error(error):
    from psycopg2 import errorcodes

    if error.pgcode == errorcodes.UNIQUE_VIOLATION:
        return jsonify(error={"code": "duplicate", "message": "Record already exists."}), 409
    return jsonify(error={"code": "invalid_record", "message": "Record could not be saved."}), 400


@app.errorhandler(psycopg2.Error)
def database_error(_error):
    logging.exception("Courses database operation failed correlation_id=%s", g.correlation_id)
    return jsonify(error={"code": "database_unavailable", "message": "Courses are temporarily unavailable."}), 503


@app.before_request
def require_token():
    if request.path == "/health":
        return None
    supplied = request.headers.get("Authorization", "")
    expected = f"Bearer {TOKEN}"
    if not TOKEN or not hmac.compare_digest(supplied, expected):
        return jsonify(error={"code": "unauthorized", "message": "A valid bearer token is required."}), 401
    return None


def database():
    if "database" not in g:
        g.database = storage.connect()
    return g.database


@app.teardown_appcontext
def close_database(_error=None):
    connection = g.pop("database", None)
    if connection is not None:
        connection.close()


@app.get("/health")
def health():
    return jsonify(application="Courses Service", status="ok")


@app.get("/ready")
def ready():
    with database().cursor() as cursor:
        cursor.execute("SELECT 1")
        cursor.fetchone()
    return jsonify(application="Courses Service", database="ok", status="ready")


@app.get("/api/courses")
def list_courses():
    return jsonify(storage.fetch_courses(database()))


@app.post("/api/courses")
def post_course():
    payload = request.get_json(silent=True) or {}
    code = str(payload.get("course_code", "")).strip().upper()
    name = str(payload.get("course_name", "")).strip()
    description = str(payload.get("description", "")).strip()
    if not code or not name:
        return jsonify(error={"code": "invalid_fields", "message": "Course code and name are required."}), 400
    course = storage.create_course(database(), code, name, description)
    return jsonify(course), 201


@app.delete("/api/courses/<int:course_id>")
def remove_course(course_id):
    storage.delete_course(database(), course_id)
    return "", 204


@app.get("/api/courses/<int:course_id>/students")
def list_course_students(course_id):
    if not storage.get_course(database(), course_id):
        return jsonify(error={"code": "not_found", "message": "Course not found."}), 404
    return jsonify(storage.fetch_course_students(database(), course_id))


@app.get("/api/enrolments")
def list_enrolments():
    return jsonify(storage.fetch_enrolments(database()))


@app.post("/api/enrolments")
def post_enrolment():
    payload = request.get_json(silent=True) or {}
    course_id = payload.get("course_id")
    student_number = str(payload.get("student_number", "")).strip()
    if not isinstance(course_id, int) or not student_number:
        return jsonify(error={"code": "invalid_fields", "message": "Course and student number are required."}), 400
    enrolment, error = storage.create_enrolment(database(), course_id, student_number)
    if error == "unknown_course":
        return jsonify(error={"code": "not_found", "message": "Course not found."}), 404
    return jsonify(enrolment), 201


@app.delete("/api/enrolments/<int:enrolment_id>")
def remove_enrolment(enrolment_id):
    storage.delete_enrolment(database(), enrolment_id)
    return "", 204


@app.get("/api/students/<string:student_number>/courses")
def list_student_courses(student_number):
    return jsonify(storage.fetch_student_courses(database(), student_number))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))
