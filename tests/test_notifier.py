import json

from services.notifier.handler import handle_message


class FakeMessage:
    def __init__(self, body):
        self.body = body


class FakeLog:
    def __init__(self):
        self.records = []

    def info(self, message):
        self.records.append(message)

    def error(self, message):
        self.records.append(message)


def test_handler_logs_and_completes_valid_message():
    message = FakeMessage(json.dumps({
        "event_type": "student_created",
        "student_number": "ST10",
        "timestamp": "2026-01-01T00:00:00+00:00",
        "correlation_id": "correlation-1",
    }).encode())
    completed, abandoned, log = [], [], FakeLog()
    assert handle_message(message, completed.append, abandoned.append, log)
    assert completed == [message]
    assert abandoned == []
    assert "correlation-1" in log.records[0]


def test_handler_abandons_invalid_message_for_retry():
    message = FakeMessage(b"not-json")
    completed, abandoned = [], []
    assert not handle_message(message, completed.append, abandoned.append, FakeLog())
    assert completed == []
    assert abandoned == [message]
