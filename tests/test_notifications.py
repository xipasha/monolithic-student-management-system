import json

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

    def get_queue_sender(self, queue_name):
        assert queue_name == "student-notifications"
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
