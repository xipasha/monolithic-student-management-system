import os
import secrets
import sqlite3
import json
import logging
import uuid
from functools import wraps
from pathlib import Path
from urllib.parse import unquote

from flask import (
    Flask, abort, flash, g, redirect,
    render_template, request, session, url_for
)
from werkzeug.security import check_password_hash, generate_password_hash
import psycopg2
from psycopg2.extras import DictCursor
from notifications import publish_student_event
from courses_client import (
    CoursesServiceUnavailable,
    request_courses_service,
    student_courses_path,
)


BASE_DIR = Path(__file__).resolve().parent
DATABASE = BASE_DIR / "instance" / "sms.db"

app = Flask(__name__)
logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
secret_key = os.environ.get("SECRET_KEY")
if not secret_key:
    raise RuntimeError("SECRET_KEY environment variable must be set")
app.config["SECRET_KEY"] = secret_key
app.config["DATABASE"] = str(DATABASE)


class PostgresCursor:
    def __init__(self, cursor):
        self._cursor = cursor

    @property
    def lastrowid(self):
        with self._cursor.connection.cursor() as cursor:
            cursor.execute("SELECT LASTVAL()")
            return cursor.fetchone()[0]

    def fetchone(self):
        return self._cursor.fetchone()

    def fetchall(self):
        return self._cursor.fetchall()


class PostgresConnection:
    def __init__(self, connection):
        self._connection = connection

    def execute(self, sql, parameters=()):
        cursor = self._connection.cursor(cursor_factory=DictCursor)
        cursor.execute(sql.replace("?", "%s"), parameters)
        return PostgresCursor(cursor)

    def executescript(self, sql):
        with self._connection.cursor() as cursor:
            cursor.execute(sql)

    def commit(self):
        self._connection.commit()

    def rollback(self):
        self._connection.rollback()

    def close(self):
        self._connection.close()


def is_postgres(db=None):
    database_url = os.environ.get("DATABASE_URL", "")
    return database_url.startswith(("postgres://", "postgresql://")) or isinstance(
        db, PostgresConnection
    )


def courses_service_enabled():
    return os.environ.get("COURSES_SERVICE_ENABLED", "false").strip().lower() == "true"


def courses_service_call(method, path, payload=None):
    return request_courses_service(
        method, path, payload=payload, correlation_id=getattr(g, "correlation_id", None)
    )


def courses_service_error():
    return render_template("service_unavailable.html"), 503


def get_db():
    if "db" not in g:
        database_url = os.environ.get("DATABASE_URL")
        if database_url and database_url.startswith(("postgres://", "postgresql://")):
            g.db = PostgresConnection(psycopg2.connect(database_url))
        else:
            if database_url:
                if not database_url.startswith("sqlite:///"):
                    raise RuntimeError("DATABASE_URL must use PostgreSQL or SQLite.")
                database_path = Path(unquote(database_url[len("sqlite:///"):]))
            else:
                database_path = DATABASE
            database_path.parent.mkdir(parents=True, exist_ok=True)
            g.db = sqlite3.connect(database_path)
            g.db.row_factory = sqlite3.Row
            g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(error=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = get_db()
    postgres = is_postgres(db)
    if postgres:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            username TEXT UNIQUE,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('admin', 'student')),
            must_change_password INTEGER NOT NULL DEFAULT 0,
            active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP::text
        );
        CREATE TABLE IF NOT EXISTS students (
            id SERIAL PRIMARY KEY,
            user_id INTEGER UNIQUE NOT NULL REFERENCES users(id),
            student_number TEXT UNIQUE NOT NULL,
            first_name TEXT NOT NULL,
            last_name TEXT NOT NULL,
            email TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS courses (
            id SERIAL PRIMARY KEY,
            course_code TEXT UNIQUE NOT NULL,
            course_name TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS enrolments (
            id SERIAL PRIMARY KEY,
            student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
            course_id INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
            enrolled_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP::text,
            UNIQUE(student_id, course_id)
        );
        """)
    else:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE,
    password_hash TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('admin', 'student')),
            must_change_password INTEGER NOT NULL DEFAULT 0,
            active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS students (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER UNIQUE NOT NULL,
            student_number TEXT UNIQUE NOT NULL,
            first_name TEXT NOT NULL,
            last_name TEXT NOT NULL,
            email TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS courses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            course_code TEXT UNIQUE NOT NULL,
            course_name TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS enrolments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            course_id INTEGER NOT NULL,
            enrolled_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(student_id, course_id),
            FOREIGN KEY(student_id) REFERENCES students(id) ON DELETE CASCADE,
            FOREIGN KEY(course_id) REFERENCES courses(id) ON DELETE CASCADE
        );
        """)

    if postgres:
        course_columns = {row["column_name"] for row in db.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'courses'"
        ).fetchall()}
    else:
        course_columns = {row["name"] for row in db.execute(
            "PRAGMA table_info(courses)").fetchall()}
    if "description" not in course_columns:
        db.execute(
            "ALTER TABLE courses ADD COLUMN description TEXT NOT NULL DEFAULT ''"
        )

    if postgres:
        columns = {row["column_name"] for row in db.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'users'"
        ).fetchall()}
    else:
        columns = {row["name"] for row in db.execute(
            "PRAGMA table_info(users)").fetchall()}
    if "username" not in columns:
        db.execute("ALTER TABLE users ADD COLUMN username TEXT")
    admin_username = os.environ.get("ADMIN_USERNAME", "admin")
    db.execute(
        """
        UPDATE users
        SET username = ?
        WHERE role = 'admin' AND username IS NULL
        """,
        (admin_username,),
    )
    db.execute(
        """
        UPDATE users
        SET username = 'student_' || (
            SELECT student_number
            FROM students
            WHERE students.user_id = users.id
        )
        WHERE role = 'student' AND username IS NULL
        """
    )
    db.commit()

    admin_username = os.environ.get("ADMIN_USERNAME", "admin")
    admin_password = os.environ.get("ADMIN_PASSWORD")

    existing = db.execute(
        "SELECT id FROM users WHERE username = ?", (admin_username,)
    ).fetchone()

    if not existing:
        if not admin_password:
            admin_password = secrets.token_urlsafe(12)
            print(
                "\nINITIAL ADMIN CREDENTIALS"
                f"\nUsername: {admin_username}"
                f"\nPassword: {admin_password}\n"
                "Set ADMIN_PASSWORD in your environment for a fixed password.\n"
            )

        db.execute(
            """INSERT INTO users
               (username, password_hash, role, must_change_password)
               VALUES (?, ?, 'admin', 0)""",
            (admin_username, generate_password_hash(admin_password)),
        )
        db.commit()


@app.before_request
def initialise_database():
    init_db()


@app.before_request
def assign_correlation_id():
    incoming = request.headers.get("X-Correlation-ID", "").strip()
    allowed = all(char.isalnum() or char in "-_.:" for char in incoming)
    g.correlation_id = incoming[:128] if incoming and allowed else str(uuid.uuid4())


@app.after_request
def log_request(response):
    correlation_id = getattr(g, "correlation_id", str(uuid.uuid4()))
    response.headers["X-Correlation-ID"] = correlation_id
    logging.getLogger("student_management").info(json.dumps({
        "event": "http_request",
        "method": request.method,
        "path": request.path,
        "status_code": response.status_code,
        "correlation_id": correlation_id,
    }))
    return response


def login_required(role=None):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if "user_id" not in session:
                return redirect(url_for("login"))

            db = get_db()
            user = db.execute(
                "SELECT * FROM users WHERE id = ? AND active = 1",
                (session["user_id"],),
            ).fetchone()

            if not user:
                session.clear()
                return redirect(url_for("login"))

            if user["must_change_password"] and request.endpoint != "change_password":
                return redirect(url_for("change_password"))

            if role and user["role"] != role:
                abort(403)

            g.user = user
            return view(*args, **kwargs)
        return wrapped
    return decorator


@app.get("/")
def home():
    if "user_id" in session:
        user = get_db().execute(
            "SELECT role FROM users WHERE id = ? AND active = 1",
            (session["user_id"],),
        ).fetchone()
        if user:
            return redirect(
                url_for("admin_dashboard")
                if user["role"] == "admin"
                else url_for("student_dashboard")
            )
        session.clear()
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        login_id = request.form.get("login_id", "").strip()
        password = request.form.get("password", "")

        user = get_db().execute(
            """SELECT u.*
               FROM users u
               LEFT JOIN students s ON s.user_id = u.id
               WHERE u.active = 1
                 AND (
                     (u.role = 'admin' AND u.username = ?)
                     OR
                     (u.role = 'student' AND s.student_number = ?)
                 )
               LIMIT 1""",
            (login_id, login_id),
        ).fetchone()

        if user and check_password_hash(user["password_hash"], password):
            session.clear()
            session["user_id"] = user["id"]
            if user["must_change_password"]:
                return redirect(url_for("change_password"))
            if user["role"] == "admin":
                return redirect(url_for("admin_dashboard"))
            return redirect(url_for("student_dashboard"))

        flash("Invalid student ID/username or password.", "error")

    return render_template("login.html")


@app.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.get("/admin")
@login_required("admin")
def admin_dashboard():
    db = get_db()
    if courses_service_enabled():
        try:
            _, courses = courses_service_call("GET", "/api/courses")
            _, enrolments = courses_service_call("GET", "/api/enrolments")
        except CoursesServiceUnavailable:
            return courses_service_error()
        counts = {
            "students": db.execute("SELECT COUNT(*) FROM students").fetchone()[0],
            "courses": len(courses),
            "enrolments": len(enrolments),
        }
    else:
        counts = {
            "students": db.execute("SELECT COUNT(*) FROM students").fetchone()[0],
            "courses": db.execute("SELECT COUNT(*) FROM courses").fetchone()[0],
            "enrolments": db.execute("SELECT COUNT(*) FROM enrolments").fetchone()[0],
        }
    students = db.execute(
        """SELECT s.*, u.username, u.active
           FROM students s JOIN users u ON u.id = s.user_id
           ORDER BY s.id DESC"""
    ).fetchall()
    if not courses_service_enabled():
        courses = db.execute("SELECT * FROM courses ORDER BY course_code").fetchall()
        enrolments = db.execute(
            """SELECT e.id, s.student_number, s.first_name, s.last_name,
                      c.course_code, c.course_name
               FROM enrolments e
               JOIN students s ON s.id = e.student_id
               JOIN courses c ON c.id = e.course_id
               ORDER BY e.id DESC"""
        ).fetchall()
    else:
        for enrolment in enrolments:
            student = db.execute(
                "SELECT first_name, last_name FROM students WHERE student_number = ?",
                (enrolment["student_number"],),
            ).fetchone()
            enrolment["first_name"] = student["first_name"] if student else ""
            enrolment["last_name"] = student["last_name"] if student else ""
    return render_template(
        "admin.html", counts=counts, students=students,
        courses=courses, enrolments=enrolments
    )


@app.post("/admin/students/create")
@login_required("admin")
def create_student():
    db = get_db()
    fields = {
        "student_number": request.form.get("student_number", "").strip(),
        "first_name": request.form.get("first_name", "").strip(),
        "last_name": request.form.get("last_name", "").strip(),
        "email": request.form.get("email", "").strip(),
    }

    if not all(fields.values()):
        flash("Complete all student account fields.", "error")
        return redirect(url_for("admin_dashboard"))

    temporary_password = secrets.token_urlsafe(10)

    try:
        internal_username = f"student_{fields['student_number']}"
        cursor = db.execute(
            """INSERT INTO users
               (username, password_hash, role, must_change_password)
               VALUES (?, ?, 'student', 1)""",
            (internal_username, generate_password_hash(temporary_password)),
        )
        db.execute(
            """INSERT INTO students
               (user_id, student_number, first_name, last_name, email)
               VALUES (?, ?, ?, ?, ?)""",
            (
                cursor.lastrowid, fields["student_number"],
                fields["first_name"], fields["last_name"], fields["email"]
            ),
        )
        db.commit()
    except (sqlite3.IntegrityError, psycopg2.IntegrityError):
        db.rollback()
        flash("Student ID already exists or the account could not be created.", "error")
        return redirect(url_for("admin_dashboard"))

    publish_student_event("student_created", fields["student_number"], g.correlation_id)

    # Show the generated temporary password once to the administrator.
    session["new_student_credentials"] = {
        "student_id": fields["student_number"],
        "password": temporary_password,
    }
    return redirect(url_for("student_credentials"))


@app.get("/admin/student-credentials")
@login_required("admin")
def student_credentials():
    credentials = session.pop("new_student_credentials", None)
    if not credentials:
        return redirect(url_for("admin_dashboard"))
    return render_template("credentials.html", credentials=credentials)


@app.post("/admin/students/<int:student_id>/toggle")
@login_required("admin")
def toggle_student(student_id):
    db = get_db()
    student = db.execute(
        """SELECT u.id, u.active, s.student_number FROM students s
           JOIN users u ON u.id = s.user_id WHERE s.id = ?""",
        (student_id,),
    ).fetchone()
    if not student:
        abort(404)

    db.execute(
        "UPDATE users SET active = ? WHERE id = ?",
        (0 if student["active"] else 1, student["id"]),
    )
    db.commit()
    publish_student_event(
        "student_activated" if not student["active"] else "student_deactivated",
        student["student_number"],
        g.correlation_id,
    )
    flash("Student account status updated.", "success")
    return redirect(url_for("admin_dashboard"))


@app.post("/admin/students/<int:student_id>/reset-password")
@login_required("admin")
def reset_student_password(student_id):
    db = get_db()
    student = db.execute(
        """SELECT u.id, s.student_number
           FROM students s
           JOIN users u ON u.id = s.user_id
           WHERE s.id = ?""",
        (student_id,),
    ).fetchone()
    if not student:
        abort(404)

    temporary_password = secrets.token_urlsafe(10)
    db.execute(
        """UPDATE users
           SET password_hash = ?, must_change_password = 1 WHERE id = ?""",
        (generate_password_hash(temporary_password), student["id"]),
    )
    db.commit()

    publish_student_event("password_reset", student["student_number"], g.correlation_id)

    session["new_student_credentials"] = {
        "student_id": student["student_number"],
        "password": temporary_password,
    }
    return redirect(url_for("student_credentials"))


@app.post("/admin/courses/create")
@login_required("admin")
def create_course():
    code = request.form.get("course_code", "").strip().upper()
    name = request.form.get("course_name", "").strip()
    description = request.form.get("description", "").strip()

    if not code or not name:
        flash("Course code and course name are required.", "error")
    elif courses_service_enabled():
        try:
            status, _ = courses_service_call(
                "POST", "/api/courses",
                {"course_code": code, "course_name": name, "description": description},
            )
        except CoursesServiceUnavailable:
            return courses_service_error()
        if status == 201:
            flash("Course created.", "success")
        elif status == 409:
            flash("That course code already exists.", "error")
        else:
            flash("Course code and course name are required.", "error")
    else:
        try:
            db = get_db()
            db.execute(
                """INSERT INTO courses (course_code, course_name, description)
                   VALUES (?, ?, ?)""",
                (code, name, description),
            )
            db.commit()
            flash("Course created.", "success")
        except (sqlite3.IntegrityError, psycopg2.IntegrityError):
            db.rollback()
            flash("That course code already exists.", "error")

    return redirect(url_for("admin_dashboard"))


@app.post("/admin/courses/<int:course_id>/delete")
@login_required("admin")
def delete_course(course_id):
    if courses_service_enabled():
        try:
            courses_service_call("DELETE", f"/api/courses/{course_id}")
        except CoursesServiceUnavailable:
            return courses_service_error()
        flash("Course deleted if it existed.", "success")
        return redirect(url_for("admin_dashboard"))
    db = get_db()
    db.execute("DELETE FROM courses WHERE id = ?", (course_id,))
    db.commit()
    flash("Course deleted if it existed.", "success")
    return redirect(url_for("admin_dashboard"))


@app.post("/admin/enrolments/create")
@login_required("admin")
def create_enrolment():
    student_id = request.form.get("student_id", type=int)
    course_id = request.form.get("course_id", type=int)
    db = get_db()

    student = db.execute(
        """SELECT s.id FROM students s
           JOIN users u ON u.id = s.user_id
           WHERE s.id = ? AND u.active = 1""",
        (student_id,),
    ).fetchone() if student_id else None

    if courses_service_enabled():
        course = bool(course_id)
    else:
        course = db.execute(
            "SELECT id FROM courses WHERE id = ?", (course_id,)
        ).fetchone() if course_id else None

    if not student or not course:
        flash("Select a valid active student and course.", "error")
    elif courses_service_enabled():
        student_number = db.execute(
            "SELECT student_number FROM students WHERE id = ?", (student_id,)
        ).fetchone()["student_number"]
        try:
            status, _ = courses_service_call(
                "POST", "/api/enrolments",
                {"course_id": course_id, "student_number": student_number},
            )
        except CoursesServiceUnavailable:
            return courses_service_error()
        if status == 201:
            flash("Student enrolled.", "success")
        elif status == 409:
            flash("That student is already enrolled in the course.", "error")
        elif status == 404:
            flash("Select a valid active student and course.", "error")
        else:
            flash("Could not create the enrolment.", "error")
    else:
        try:
            db.execute(
                "INSERT INTO enrolments (student_id, course_id) VALUES (?, ?)",
                (student_id, course_id),
            )
            db.commit()
            flash("Student enrolled.", "success")
        except (sqlite3.IntegrityError, psycopg2.IntegrityError):
            db.rollback()
            flash("That student is already enrolled in the course.", "error")

    return redirect(url_for("admin_dashboard"))


@app.post("/admin/enrolments/<int:enrolment_id>/delete")
@login_required("admin")
def delete_enrolment(enrolment_id):
    if courses_service_enabled():
        try:
            courses_service_call("DELETE", f"/api/enrolments/{enrolment_id}")
        except CoursesServiceUnavailable:
            return courses_service_error()
        flash("Enrolment removed if it existed.", "success")
        return redirect(url_for("admin_dashboard"))
    db = get_db()
    db.execute("DELETE FROM enrolments WHERE id = ?", (enrolment_id,))
    db.commit()
    flash("Enrolment removed if it existed.", "success")
    return redirect(url_for("admin_dashboard"))


@app.route("/change-password", methods=["GET", "POST"])
@login_required()
def change_password():
    if request.method == "POST":
        password = request.form.get("password", "")
        confirm = request.form.get("confirm_password", "")
        if len(password) < 10:
            flash("Use a password of at least 10 characters.", "error")
        elif password != confirm:
            flash("The passwords do not match.", "error")
        else:
            db = get_db()
            db.execute(
                """UPDATE users
                   SET password_hash = ?, must_change_password = 0
                   WHERE id = ?""",
                (generate_password_hash(password), g.user["id"]),
            )
            db.commit()
            flash("Password changed successfully.", "success")
            return redirect(url_for("home"))
    return render_template("change_password.html")


@app.get("/student")
@login_required("student")
def student_dashboard():
    db = get_db()
    student = db.execute(
        "SELECT * FROM students WHERE user_id = ?", (g.user["id"],)
    ).fetchone()

    if not student:
        abort(404)

    if courses_service_enabled():
        try:
            _, courses = courses_service_call(
                "GET", student_courses_path(student["student_number"])
            )
        except CoursesServiceUnavailable:
            return courses_service_error()
    else:
        courses = db.execute(
            """SELECT c.course_code, c.course_name, e.enrolled_at
               FROM enrolments e JOIN courses c ON c.id = e.course_id
               WHERE e.student_id = ? ORDER BY c.course_code""",
            (student["id"],),
        ).fetchall()

    return render_template("student.html", student=student, courses=courses)


@app.get("/health")
def health():
    return {"status": "ok", "application": "Student Management System"}


if __name__ == "__main__":
    app.run(debug=True)
