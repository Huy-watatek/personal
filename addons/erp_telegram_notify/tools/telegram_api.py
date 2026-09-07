"""Thin HTTP client for the Telegram Bot API.

Deliberately free of any ORM dependency so it can be reused from the outbox
worker, the inbound webhook controller and tests alike.
"""

import logging

import requests

_logger = logging.getLogger(__name__)

BASE_URL = "https://api.telegram.org"
DEFAULT_TIMEOUT = 10


class TelegramError(Exception):
    """Raised for both API-level errors and transport failures."""

    def __init__(self, description, error_code=None, retry_after=None):
        self.description = description
        self.error_code = error_code
        self.retry_after = retry_after
        super().__init__(description)


def call(token, method, payload, timeout=DEFAULT_TIMEOUT):
    """Invoke ``method`` on the Bot API and return its ``result`` payload.

    :raises TelegramError: on transport failure or a non-ok API response.
    """
    url = "%s/bot%s/%s" % (BASE_URL, token, method)
    try:
        response = requests.post(url, json=payload, timeout=timeout)
    except requests.exceptions.RequestException as exc:
        # The token must never leak through an exception message or a log line.
        message = str(exc).replace(token, "***")
        _logger.warning("Telegram transport error on %s: %s", method, message)
        raise TelegramError(message) from exc

    try:
        body = response.json()
    except ValueError as exc:
        raise TelegramError("Non-JSON response (HTTP %s)" % response.status_code) from exc

    if body.get("ok"):
        return body.get("result")

    parameters = body.get("parameters") or {}
    raise TelegramError(
        body.get("description") or "Unknown Telegram error",
        error_code=body.get("error_code"),
        retry_after=parameters.get("retry_after"),
    )
