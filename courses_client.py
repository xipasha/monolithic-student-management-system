"""Bounded-timeout HTTP client used by the monolith's courses adapter."""

import json
import os
import socket
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


class CoursesServiceUnavailable(Exception):
    """The courses service could not provide a usable response."""


def request_courses_service(method, path, payload=None, correlation_id=None):
    base_url = os.environ.get("COURSES_SERVICE_URL", "").rstrip("/")
    token = os.environ.get("COURSES_SERVICE_TOKEN", "")
    if not base_url or not token:
        raise CoursesServiceUnavailable("Courses service configuration is missing")

    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {token}",
    }
    if correlation_id:
        headers["X-Correlation-ID"] = correlation_id
    data = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload).encode("utf-8")
    request = Request(f"{base_url}{path}", data=data, headers=headers, method=method)

    try:
        with urlopen(request, timeout=3) as response:
            status = response.status
            body = response.read()
    except HTTPError as error:
        status = error.code
        body = error.read()
    except (URLError, TimeoutError, socket.timeout, OSError) as error:
        raise CoursesServiceUnavailable("Courses service request failed") from error

    if status in {401, 403}:
        raise CoursesServiceUnavailable(f"Courses service returned HTTP {status}")
    if status >= 500:
        raise CoursesServiceUnavailable(f"Courses service returned HTTP {status}")
    if status == 204 or not body:
        return status, None
    try:
        return status, json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CoursesServiceUnavailable("Courses service returned invalid JSON") from error


def student_courses_path(student_number):
    return f"/api/students/{quote(student_number, safe='')}/courses"
