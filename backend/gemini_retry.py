"""Shared retry wrapper for Gemini `generate_content` calls.

Handles transient failures the same way for every caller:

- 429 RESOURCE_EXHAUSTED → honor the server-supplied `retryDelay`
  (falls back to `DEFAULT_RETRY_DELAY_SEC` when missing).
- 500 / 503 / 504 → server-side transient (overload, gateway, upstream
  timeout). Exponential backoff per `SERVER_BACKOFF_SCHEDULE`.

Auth errors (401, 403) and client errors (400, etc.) are NOT retried —
they're not going to succeed on their own.

Single source of truth so `detect_inventory.py` and `generate_packet.py`
can't drift in their retry behavior.
"""

from __future__ import annotations

import re
import time
from typing import Any

MAX_RETRIES: int = 3
DEFAULT_RETRY_DELAY_SEC: float = 20.0
# Exponential-ish backoff for server-side transient errors.
# Index = retry attempt number (0-based). The last value is reused if
# the schedule is shorter than MAX_RETRIES.
SERVER_BACKOFF_SCHEDULE: tuple[float, ...] = (5.0, 15.0, 30.0)
SERVER_RETRY_STATUSES: frozenset[int] = frozenset({500, 503, 504})
AUTH_STATUSES: frozenset[int] = frozenset({401, 403})


def _error_status(e: Exception) -> int | None:
    """Best-effort HTTP status extraction from a google-genai error."""
    for attr in ("code", "status_code"):
        v = getattr(e, attr, None)
        if isinstance(v, int):
            return v
    m = re.match(r"^\s*(\d{3})\b", str(e))
    return int(m.group(1)) if m else None


def _parse_retry_delay(
    e: Exception, default: float = DEFAULT_RETRY_DELAY_SEC
) -> float:
    """Pull `retryDelay` (seconds) out of a Gemini 429 error body."""
    details = getattr(e, "details", None)
    if isinstance(details, list):
        for d in details:
            if isinstance(d, dict) and isinstance(d.get("retryDelay"), str):
                rd = d["retryDelay"]
                if rd.endswith("s"):
                    try:
                        return float(rd[:-1])
                    except ValueError:
                        pass
    m = re.search(
        r"['\"]retryDelay['\"]\s*:\s*['\"](\d+(?:\.\d+)?)s['\"]", str(e)
    )
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            pass
    return default


def _server_backoff(attempt: int) -> float:
    if attempt < len(SERVER_BACKOFF_SCHEDULE):
        return SERVER_BACKOFF_SCHEDULE[attempt]
    return SERVER_BACKOFF_SCHEDULE[-1]


def call_with_retry(
    client: Any, *, log_prefix: str = "[gemini]", **gen_kwargs: Any
) -> Any:
    """Invoke `client.models.generate_content(**gen_kwargs)` with retry.

    Args:
        client: a google-genai `Client` instance.
        log_prefix: shown in the retry log lines so callers are
            distinguishable in the console (e.g. `"[detect_inventory]"`).
        **gen_kwargs: forwarded verbatim to `generate_content`.

    Raises:
        Re-raises the underlying SDK exception when retries are
        exhausted, or immediately for non-retriable errors (auth, 400,
        SDK assertion failures, etc.).
    """
    last_error: Exception | None = None

    for attempt in range(MAX_RETRIES + 1):
        try:
            return client.models.generate_content(**gen_kwargs)
        except Exception as e:
            last_error = e
            status = _error_status(e)

            if status in AUTH_STATUSES:
                print(f"{log_prefix} auth error ({status}); not retrying")
                raise

            if status == 429 and attempt < MAX_RETRIES:
                delay = _parse_retry_delay(e)
                print(
                    f"{log_prefix} Rate limited (429), sleeping {delay:.1f}s "
                    f"and retrying (attempt {attempt + 1}/{MAX_RETRIES})..."
                )
                time.sleep(delay)
                continue

            if status in SERVER_RETRY_STATUSES and attempt < MAX_RETRIES:
                delay = _server_backoff(attempt)
                print(
                    f"{log_prefix} Gemini overloaded ({status}), sleeping "
                    f"{delay:.1f}s and retrying "
                    f"(attempt {attempt + 1}/{MAX_RETRIES})..."
                )
                time.sleep(delay)
                continue

            raise

    if last_error is not None:
        raise last_error
    raise RuntimeError("unreachable: retry loop exited without return")
