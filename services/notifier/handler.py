"""Pure message handling logic, with broker settlement injected for tests."""

import json
import logging

logger = logging.getLogger("notifier")


def handle_message(message, complete, abandon, log=logger):
    """Log a simulated notification, completing or abandoning the delivery."""
    try:
        body = b"".join(message.body) if not isinstance(message.body, (bytes, bytearray)) else message.body
        event = json.loads(body.decode("utf-8"))
        log.info(json.dumps({
            "event": "notification_simulated",
            "event_type": event["event_type"],
            "student_number": event["student_number"],
            "timestamp": event["timestamp"],
            "correlation_id": event["correlation_id"],
        }))
        complete(message)
        return True
    except Exception as exc:
        log.error(json.dumps({"event": "notification_processing_failed", "error": str(exc)}))
        abandon(message)
        return False
