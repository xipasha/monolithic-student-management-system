"""Azure Service Bus notification consumer and health endpoint."""

import json
import logging
import os
import threading
import time

from azure.identity import DefaultAzureCredential
from azure.servicebus import ServiceBusClient
from flask import Flask, jsonify

from handler import handle_message

app = Flask(__name__)
logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
_consumer_started = False
_consumer_lock = threading.Lock()


def consume_messages():
    namespace = os.environ.get("SERVICEBUS_NAMESPACE")
    queue = os.environ.get("SERVICEBUS_QUEUE", "student-notifications")
    if not namespace:
        logging.getLogger("notifier").error(json.dumps({
            "event": "consumer_configuration_error",
            "message": "SERVICEBUS_NAMESPACE is required",
        }))
        return

    while True:
        try:
            with ServiceBusClient(
                fully_qualified_namespace=namespace,
                credential=DefaultAzureCredential(),
            ) as client:
                with client.get_queue_receiver(
                    queue_name=queue, max_wait_time=5, max_message_count=10
                ) as receiver:
                    for message in receiver:
                        handle_message(
                            message,
                            complete=receiver.complete_message,
                            abandon=receiver.abandon_message,
                        )
        except Exception as exc:
            logging.getLogger("notifier").error(json.dumps({
                "event": "consumer_connection_failed", "error": str(exc)
            }))
            time.sleep(5)


@app.before_request
def ensure_consumer_started():
    global _consumer_started
    with _consumer_lock:
        if not _consumer_started:
            threading.Thread(target=consume_messages, name="servicebus-consumer", daemon=True).start()
            _consumer_started = True


@app.get("/health")
def health():
    return jsonify({"application": "Student Notifications Worker", "status": "ok"})
