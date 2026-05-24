"""Logging filter that redacts API-key query parameters from httpx logs.

``httpx`` logs every request at INFO with the full URL — including the
query string. The Gemini REST endpoint takes its API key as a ``key=``
query parameter (header-based auth is not supported), so every successful
LLM call would otherwise emit something like::

    HTTP Request: POST https://generativelanguage.googleapis.com/v1beta/
    models/gemini-2.5-flash:generateContent?key=AIzaSy... "HTTP/1.1 200 OK"

…and that line gets persisted to stdout, log aggregators, Sentry
breadcrumbs etc. This filter rewrites every ``?key=...`` / ``&key=...``
occurrence in the formatted message AND in the underlying ``record.args``
so the key never leaves the process via logging.

Install with :func:`install_httpx_key_redaction`. It is idempotent — the
first call attaches the filter to the ``httpx`` logger, subsequent calls
are no-ops. Call it from the constructor of any class that issues
httpx requests with a sensitive ``key`` query parameter.
"""

from __future__ import annotations

import logging
import re
from typing import Any

# Match ``?key=...`` or ``&key=...`` and capture the prefix so we can keep
# it in the redacted output. Stops at the next ``&``, whitespace, quote, or
# common URL terminator. ``key`` is matched case-insensitively to cover
# anyone writing ``?Key=...`` by accident.
_KEY_QUERY_RE: re.Pattern[str] = re.compile(
    r"([?&][Kk]ey=)[^&\s'\"]+",
)

_REDACTED_REPLACEMENT = r"\1REDACTED"

# Marker attribute on the httpx logger so the filter is only attached once
# even if multiple call sites call :func:`install_httpx_key_redaction`.
_FILTER_INSTALLED_FLAG = "_kheritage_httpx_key_redaction_installed"


def redact_key_in_url(text: str) -> str:
    """Public helper — return ``text`` with any ``?key=...`` redacted.

    Useful for ad-hoc log statements (e.g. exception ``str(exc)`` that
    contains a URL) where the filter alone wouldn't intercept the value.
    """
    return _KEY_QUERY_RE.sub(_REDACTED_REPLACEMENT, text)


class KeyQueryRedactingFilter(logging.Filter):
    """``logging.Filter`` that redacts ``key=`` query params in records.

    The filter is conservative: it never raises, never drops the record,
    and only rewrites args whose string form actually contains ``key=``.
    Non-string args (e.g. integers passed as ``%d``) are left untouched
    so the formatter still receives the correct types.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if record.args:
            new_args: list[Any] = []
            mutated = False
            args_iter: tuple[Any, ...] | dict[str, Any]
            if isinstance(record.args, dict):
                # %-style mapping args — rewrite values that contain key=.
                redacted_map: dict[str, Any] = {}
                for k, v in record.args.items():
                    if isinstance(v, str) and "key=" in v.lower():
                        redacted_map[k] = redact_key_in_url(v)
                        mutated = True
                    else:
                        redacted_map[k] = v
                if mutated:
                    record.args = redacted_map  # type: ignore[assignment]
            else:
                args_iter = record.args
                for a in args_iter:
                    if isinstance(a, str):
                        if "key=" in a.lower():
                            new_args.append(redact_key_in_url(a))
                            mutated = True
                        else:
                            new_args.append(a)
                    else:
                        # ``httpx.URL`` and similar render their full string
                        # via ``__str__``; if the rendered form contains the
                        # key we substitute the *string* form for the arg so
                        # the formatter still produces a redacted message.
                        rendered = str(a)
                        if "key=" in rendered.lower():
                            new_args.append(redact_key_in_url(rendered))
                            mutated = True
                        else:
                            new_args.append(a)
                if mutated:
                    record.args = tuple(new_args)
        if isinstance(record.msg, str) and "key=" in record.msg.lower():
            record.msg = redact_key_in_url(record.msg)
        return True


def install_httpx_key_redaction() -> None:
    """Attach :class:`KeyQueryRedactingFilter` to the ``httpx`` logger.

    Safe to call repeatedly — the filter is installed at most once per
    logger instance, guarded by a sentinel attribute on the logger.
    """
    httpx_logger = logging.getLogger("httpx")
    if getattr(httpx_logger, _FILTER_INSTALLED_FLAG, False):
        return
    httpx_logger.addFilter(KeyQueryRedactingFilter())
    setattr(httpx_logger, _FILTER_INSTALLED_FLAG, True)
