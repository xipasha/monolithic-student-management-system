"""Best-effort publisher for student lifecycle notifications."""

import json
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from functools import lru_cache

from azure.core.pipeline.transport import RequestsTransport
from azure.identity import DefaultAzureCredential, ManagedIdentityCredential
from azure.servicebus import ServiceBusClient, ServiceBusMessage

logger = logging.getLogger(__name__)
_notification_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="student-event")
TOKEN_TIMEOUT_SECONDS = 2


@lru_cache(maxsize=1)
def _credential():
    """Reuse a credential with bounded token HTTP and retry timeouts."""
    transport = RequestsTransport(
        connection_timeout=TOKEN_TIMEOUT_SECONDS,
        read_timeout=TOKEN_TIMEOUT_SECONDS,
    )
    if os.environ.get("IDENTITY_ENDPOINT"):
        return ManagedIdentityCredential(transport=transport, retry_total=0)
    return DefaultAzureCredential(
        transport=transport,
        retry_total=0,
        process_timeout=TOKEN_TIMEOUT_SECONDS,
    )


def _client():
    """Create the Azure client lazily so disabled mode needs no cloud setup."""
    namespace = os.environ.get("SERVICEBUS_NAMESPACE")
    queue = os.environ.get("SERVICEBUS_QUEUE", "student-notifications")
    if not namespace:
        raise RuntimeError("SERVICEBUS_NAMESPACE is required when notifications are enabled")
    return ServiceBusClient(
        fully_qualified_namespace=namespace,
        credential=_credential(),
        retry_total=0,
        socket_timeout=TOKEN_TIMEOUT_SECONDS,
    ), queue


def _send_event(payload, client_factory=None):
    started = time.monotonic()
    try:
        client, queue = (client_factory or _client)()
        with client:
            sender = client.get_queue_sender(
                queue_name=queue,
                socket_timeout=TOKEN_TIMEOUT_SECONDS,
            )
            with sender:
                sender.send_messages(ServiceBusMessage(json.dumps(payload)))
        logger.info(json.dumps({
            "event": "notification_publish_complete",
            "event_type": payload["event_type"],
            "correlation_id": payload["correlation_id"],
            "elapsed_seconds": round(time.monotonic() - started, 3),
        }))
        return True
    except Exception as exc:  # Notification outages must not change route results.
        logger.error(
            json.dumps({
                "event": "notification_publish_failed",
                "event_type": payload["event_type"],
                "student_number": payload["student_number"],
                "correlation_id": payload["correlation_id"],
                "error": str(exc),
                "elapsed_seconds": round(time.monotonic() - started, 3),
            })
        )
        return False


def publish_student_event(event_type, student_number, correlation_id, client_factory=None):
    """Queue best-effort delivery so identity or broker latency cannot stall a request."""
    if os.environ.get("NOTIFICATIONS_ENABLED", "false").lower() != "true":
        return False

    payload = {
        "event_type": event_type,
        "student_number": student_number,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "correlation_id": correlation_id,
    }
    # Injected factories remain synchronous for deterministic unit tests.
    if client_factory is not None:
        return _send_event(payload, client_factory)
    started = time.monotonic()
    try:
        _notification_executor.submit(_send_event, payload)
    except RuntimeError as exc:
        logger.error(
            json.dumps({
                "event": "notification_queue_failed",
                "event_type": event_type,
                "student_number": student_number,
                "correlation_id": correlation_id,
                "error": str(exc),
            })
        )
        return False
    logger.info(json.dumps({
        "event": "notification_queued",
        "event_type": event_type,
        "correlation_id": correlation_id,
        "enqueue_elapsed_seconds": round(time.monotonic() - started, 3),
    }))
    return True
