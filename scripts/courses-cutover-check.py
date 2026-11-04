#!/usr/bin/env python3
"""Check that the monolith dashboard remains available during flag rehearsal."""

import os
from http.cookiejar import CookieJar
from urllib.parse import urlencode, urljoin, urlparse
from urllib.request import HTTPCookieProcessor, Request, build_opener


def main():
    base_url = os.environ["WEBAPP_URL"].rstrip("/")
    correlation_id = os.environ["CUTOVER_CORRELATION_ID"]
    opener = build_opener(HTTPCookieProcessor(CookieJar()))
    for path, values in (
        ("/login", {"login_id": "admin", "password": os.environ["ADMIN_PASSWORD"]}),
        ("/admin", None),
    ):
        data = urlencode(values).encode() if values else None
        headers = {"X-Correlation-ID": correlation_id}
        if data:
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        request = Request(urljoin(base_url + "/", path.lstrip("/")), data=data, headers=headers)
        with opener.open(request, timeout=30) as response:
            body = response.read().decode()
            if response.headers.get("X-Correlation-ID") != correlation_id:
                raise RuntimeError(f"Correlation ID mismatch on {path}.")
            final_path = urlparse(response.geturl()).path
            if path == "/login" and final_path != "/admin":
                raise RuntimeError("Administrator login failed during flag rehearsal.")
            if path == "/admin" and (
                response.status != 200 or "Administrator Dashboard" not in body
            ):
                raise RuntimeError("Admin dashboard failed during flag rehearsal.")
    print(f"Admin dashboard check passed with correlation_id={correlation_id}.")


if __name__ == "__main__":
    main()
