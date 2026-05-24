"""Tests for the ``httpx`` API-key redaction logging filter (PR #29).

Background: ``httpx`` logs every request at INFO with the full URL —
for Gemini that URL includes ``?key=<api-key>``. This filter rewrites
the URL in log records so the key never reaches stdout / sinks.
"""

from __future__ import annotations

import logging

import httpx
import pytest

from app.services.trends._httpx_log_redact import (
    KeyQueryRedactingFilter,
    install_httpx_key_redaction,
    redact_key_in_url,
)

# ---------------------------------------------------------------------------
# redact_key_in_url — pure string helper
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (
            "https://generativelanguage.googleapis.com/v1beta/models/gemini:generateContent?key=AIzaSy1234567890abcdef",
            "https://generativelanguage.googleapis.com/v1beta/models/gemini:generateContent?key=REDACTED",
        ),
        (
            "GET https://api.example/path?foo=1&key=secret&bar=2 HTTP/1.1",
            "GET https://api.example/path?foo=1&key=REDACTED&bar=2 HTTP/1.1",
        ),
        # case-insensitive on the ``key`` token
        (
            "https://api.example/path?Key=ABCDEF",
            "https://api.example/path?Key=REDACTED",
        ),
        # multiple occurrences in one line (theoretical)
        (
            "first?key=AAA second?key=BBB",
            "first?key=REDACTED second?key=REDACTED",
        ),
    ],
)
def test_redact_key_in_url_replaces_value(raw: str, expected: str) -> None:
    assert redact_key_in_url(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        # No ``key=`` query param — left alone
        "https://api.example/path?foo=1&bar=2",
        # Unrelated token whose name happens to contain ``key`` — only
        # exact ``[?&]key=`` matches, not ``apikey=`` (which is the
        # *value*, not the param name) — but we still over-redact when
        # ``key`` itself appears as the param name. Verify ``apikey=`` is
        # NOT redacted by accident.
        "https://api.example/path?apikey=AIzaSy123",
        # Bare ``key`` in path (not query) — left alone
        "https://api.example/key/foo",
        # No URL at all
        "some unrelated log line without query params",
    ],
)
def test_redact_key_in_url_is_a_noop_for_unrelated_urls(raw: str) -> None:
    assert redact_key_in_url(raw) == raw


# ---------------------------------------------------------------------------
# KeyQueryRedactingFilter — applied as a logging.Filter
# ---------------------------------------------------------------------------


def _make_record(msg: str, args: tuple | dict) -> logging.LogRecord:
    return logging.LogRecord(
        name="httpx",
        level=logging.INFO,
        pathname=__file__,
        lineno=0,
        msg=msg,
        args=args,
        exc_info=None,
    )


def test_filter_redacts_string_arg_with_key_query() -> None:
    f = KeyQueryRedactingFilter()
    record = _make_record(
        'HTTP Request: %s %s "%s %d %s"',
        (
            "POST",
            "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key=AIzaSyAXsQUeFVE",
            "HTTP/1.1",
            200,
            "OK",
        ),
    )
    f.filter(record)
    assert (
        record.args[1]
        == "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key=REDACTED"
    )
    # Other args untouched — int stays int so %d still works.
    assert record.args[0] == "POST"
    assert record.args[3] == 200
    assert record.getMessage().endswith('"HTTP/1.1 200 OK"')


def test_filter_redacts_httpx_url_object_arg() -> None:
    """httpx.URL renders via ``__str__`` — filter should redact via the rendered form."""
    f = KeyQueryRedactingFilter()
    url = httpx.URL("https://api.example/foo?key=AIzaSy987&bar=1")
    record = _make_record("HTTP Request: %s %s", ("GET", url))
    f.filter(record)
    assert "key=REDACTED" in record.getMessage()
    assert "AIzaSy987" not in record.getMessage()


def test_filter_passes_through_when_no_key_query() -> None:
    f = KeyQueryRedactingFilter()
    record = _make_record(
        'HTTP Request: %s %s "%s %d %s"',
        ("GET", "https://api.example/path?foo=1", "HTTP/1.1", 200, "OK"),
    )
    f.filter(record)
    assert (
        record.getMessage() == 'HTTP Request: GET https://api.example/path?foo=1 "HTTP/1.1 200 OK"'
    )


def test_filter_redacts_msg_field_when_no_args() -> None:
    """Direct ``logger.info("...key=AIza...")`` calls (no %-args) are still redacted."""
    f = KeyQueryRedactingFilter()
    record = _make_record(
        "manual log: https://api.example/path?key=SECRET",
        (),
    )
    f.filter(record)
    assert record.getMessage() == "manual log: https://api.example/path?key=REDACTED"


def test_filter_never_drops_record() -> None:
    f = KeyQueryRedactingFilter()
    record = _make_record("anything", ())
    # ``logging.Filter.filter`` should return truthy to keep the record.
    assert f.filter(record) is True


# ---------------------------------------------------------------------------
# install_httpx_key_redaction — idempotent installer
# ---------------------------------------------------------------------------


def _clear_httpx_filter() -> None:
    """Remove the redaction filter from the ``httpx`` logger between tests."""
    logger = logging.getLogger("httpx")
    sentinel = "_kheritage_httpx_key_redaction_installed"
    for f in list(logger.filters):
        if isinstance(f, KeyQueryRedactingFilter):
            logger.removeFilter(f)
    if hasattr(logger, sentinel):
        delattr(logger, sentinel)


def test_install_attaches_filter_to_httpx_logger() -> None:
    _clear_httpx_filter()
    try:
        install_httpx_key_redaction()
        httpx_logger = logging.getLogger("httpx")
        assert any(isinstance(f, KeyQueryRedactingFilter) for f in httpx_logger.filters)
    finally:
        _clear_httpx_filter()


def test_install_is_idempotent() -> None:
    _clear_httpx_filter()
    try:
        install_httpx_key_redaction()
        install_httpx_key_redaction()
        install_httpx_key_redaction()
        httpx_logger = logging.getLogger("httpx")
        count = sum(1 for f in httpx_logger.filters if isinstance(f, KeyQueryRedactingFilter))
        assert count == 1, f"expected 1 redaction filter, got {count}"
    finally:
        _clear_httpx_filter()


def test_install_via_logger_caplog_redacts_actual_message(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """End-to-end: install + emit a record on ``httpx`` logger → captured log is redacted."""
    _clear_httpx_filter()
    try:
        install_httpx_key_redaction()
        httpx_logger = logging.getLogger("httpx")
        # caplog hooks into the root logger handler chain; emit a record
        # on the ``httpx`` logger so our filter runs before propagation.
        with caplog.at_level(logging.INFO, logger="httpx"):
            httpx_logger.info(
                'HTTP Request: %s %s "%s %d %s"',
                "POST",
                "https://generativelanguage.googleapis.com/v1beta/models/x:generateContent?key=AIzaSyREALSECRET",
                "HTTP/1.1",
                200,
                "OK",
            )
        # Verify the secret never appears in any captured record.
        for rec in caplog.records:
            msg = rec.getMessage()
            assert "AIzaSyREALSECRET" not in msg, msg
            if "key=" in msg:
                assert "key=REDACTED" in msg
    finally:
        _clear_httpx_filter()
