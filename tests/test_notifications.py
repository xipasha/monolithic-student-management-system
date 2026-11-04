import json
import threading
from concurrent.futures import ThreadPoolExecutor

import notifications
from notifications import publish_student_event


class FakeSender:
    def __init__(self):
        self.messages = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def send_messages(self, message):
        body = b"".join(message.body)
        self.messages.append(json.loads(body.decode("utf-8")))


class FakeClient:
    def __init__(self):
        self.sender = FakeSender()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def get_queue_sender(self, queue_name, socket_timeout=None):
        assert queue_name == "student-notifications"
        assert socket_timeout == notifications.TOKEN_TIMEOUT_SECONDS
        return self.sender


def test_publisher_does_nothing_when_disabled(monkeypatch):
    monkeypatch.setenv("NOTIFICATIONS_ENABLED", "false")
    called = []
    assert not publish_student_event("student_created", "ST10", "cid", lambda: called.append(1))
    assert called == []


def test_publisher_sends_safe_payload_when_enabled(monkeypatch):
    monkeypatch.setenv("NOTIFICATIONS_ENABLED", "true")
    client = FakeClient()
    assert publish_student_event(
        "password_reset", "ST10", "correlation-1", lambda: (client, "student-notifications")
    )
    payload = client.sender.messages[0]
    assert payload["event_type"] == "password_reset"
    assert payload["student_number"] == "ST10"
    assert payload["correlation_id"] == "correlation-1"
    assert "timestamp" in payload
    assert not any("password" in key.lower() for key in payload)


def test_publisher_swallows_send_failure(monkeypatch, caplog):
    monkeypatch.setenv("NOTIFICATIONS_ENABLED", "true")

    def fail():
        raise RuntimeError("queue unavailable")

    assert not publish_student_event("student_created", "ST10", "cid", fail)
    assert "notification_publish_failed" in caplog.text


def test_live_publisher_queues_delivery_without_waiting(monkeypatch):
    monkeypatch.setenv("NOTIFICATIONS_ENABLED", "true")
    submitted = []

    class RecordingExecutor:
        def submit(self, function, *args):
            submitted.append((function, args))

    monkeypatch.setattr(notifications, "_notification_executor", RecordingExecutor())
    assert publish_student_event("student_created", "ST11", "correlation-2")
    assert len(submitted) == 1
    function, args = submitted.pop()
    assert args[0]["student_number"] == "ST11"
    assert args[0]["correlation_id"] == "correlation-2"


def test_slow_token_failure_is_logged_without_blocking_publisher(monkeypatch, caplog):
    monkeypatch.setenv("NOTIFICATIONS_ENABLED", "true")
    token_started = threading.Event()
    allow_timeout = threading.Event()
    executor = ThreadPoolExecutor(max_workers=1)
    futures = []

    class ObservedExecutor:
        def submit(self, function, *args):
            future = executor.submit(function, *args)
            futures.append(future)
            return future

    def slow_token_client():
        token_started.set()
        assert allow_timeout.wait(timeout=1)
        raise TimeoutError("Managed Identity token acquisition timed out after 2 seconds")

    monkeypatch.setattr(notifications, "_notification_executor", ObservedExecutor())
    monkeypatch.setattr(notifications, "_client", slow_token_client)
    try:
        assert publish_student_event("student_created", "ST12", "slow-token-correlation")
        assert token_started.wait(timeout=1)
        assert not allow_timeout.is_set()
        allow_timeout.set()
        assert futures[0].result(timeout=1) is False
        assert "notification_publish_failed" in caplog.text
        assert "slow-token-correlation" in caplog.text
        assert "timed out after 2 seconds" in caplog.text
    finally:
        allow_timeout.set()
        executor.shutdown(wait=True)


def test_managed_identity_uses_short_token_timeout(monkeypatch):
    observed = {}

    class FakeCredential:
        def __init__(self, **kwargs):
            observed["credential"] = kwargs

    class FakeTransport:
        def __init__(self, **kwargs):
            observed["transport"] = kwargs

    monkeypatch.setenv("IDENTITY_ENDPOINT", "http://identity.test/token")
    monkeypatch.setattr(notifications, "ManagedIdentityCredential", FakeCredential)
    monkeypatch.setattr(notifications, "RequestsTransport", FakeTransport)
    notifications._credential.cache_clear()
    try:
        notifications._credential()
    finally:
        notifications._credential.cache_clear()
    assert observed["transport"] == {"connection_timeout": 2, "read_timeout": 2}
    assert observed["credential"]["retry_total"] == 0
    assert observed["credential"]["transport"] is not None
