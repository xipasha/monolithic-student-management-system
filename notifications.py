"""Best-effort publisher for student lifecycle notifications."""

import json
import logging
import os
from datetime import datetime, timezone

from azure.identity import DefaultAzureCredential
from azure.servicebus import ServiceBusClient, ServiceBusMessage

logger = logging.getLogger(__name__)


def _client():
    """Create the Azure client lazily so disabled mode needs no cloud setup."""
    namespace = os.environ.get("SERVICEBUS_NAMESPACE")
    queue = os.environ.get("SERVICEBUS_QUEUE", "student-notifications")
    if not namespace:
        raise RuntimeError("SERVICEBUS_NAMESPACE is required when notifications are enabled")
    return ServiceBusClient(
        fully_qualified_namespace=namespace,
        credential=DefaultAzureCredential(),
    ), queue


def publish_student_event(event_type, student_number, correlation_id, client_factory=None):
    """Send a non-sensitive event. Broker failures never fail the student request."""
    if os.environ.get("NOTIFICATIONS_ENABLED", "false").lower() != "true":
        return False

    payload = {
        "event_type": event_type,
        "student_number": student_number,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "correlation_id": correlation_id,
    }
    try:
        client, queue = (client_factory or _client)()
        with client:
            sender = client.get_queue_sender(queue_name=queue)
            with sender:
                sender.send_messages(ServiceBusMessage(json.dumps(payload)))
        return True
    except Exception as exc:  # Notification outages must not change route results.
        logger.error(
            json.dumps({
                "event": "notification_publish_failed",
                "event_type": event_type,
                "student_number": student_number,
                "correlation_id": correlation_id,
                "error": str(exc),
            })
        )
        return False
