"""Tests for the polite HTTP client's retry logic -- specifically, that
permanent 4xx errors (unlike 5xx errors or network exceptions) fail on the
first attempt instead of being retried. Retrying a 404 can never succeed;
doing so anyway wasted real wall-clock time on every dead link (see
PermanentHTTPError and the "keeps retrying and freezes" complaint that
prompted this fix)."""
from __future__ import annotations

import dataclasses
from unittest.mock import MagicMock, patch

import pytest
import requests

from gst_agent.config import settings as real_settings
from gst_agent.http_client import PermanentHTTPError, PoliteSession


@pytest.fixture
def session():
    s = PoliteSession()
    # These tests are about retry *count*, not real robots.txt lookups or
    # real network timing -- both are stubbed out.
    s.is_allowed = lambda url: True
    return s


def _fake_response(status_code: int) -> MagicMock:
    response = MagicMock(spec=requests.Response)
    response.status_code = status_code
    if status_code >= 400:
        response.raise_for_status.side_effect = requests.HTTPError(f"{status_code} error")
    else:
        response.raise_for_status.return_value = None
    return response


def test_404_fails_immediately_without_retrying(session):
    test_settings = dataclasses.replace(real_settings, max_retries=3, request_delay_seconds=0)
    mock_get = MagicMock(return_value=_fake_response(404))

    with patch("gst_agent.http_client.settings", test_settings), \
         patch.object(session, "_session") as mock_requests_session, \
         patch("time.sleep") as mock_sleep:
        mock_requests_session.get = mock_get
        with pytest.raises(PermanentHTTPError):
            session.get("https://example.com/missing.pdf")

    assert mock_get.call_count == 1  # not retried
    mock_sleep.assert_not_called()  # no wasted backoff delay either


def test_403_and_400_also_fail_immediately(session):
    test_settings = dataclasses.replace(real_settings, max_retries=3, request_delay_seconds=0)
    for status in (400, 403):
        mock_get = MagicMock(return_value=_fake_response(status))
        with patch("gst_agent.http_client.settings", test_settings), \
             patch.object(session, "_session") as mock_requests_session, \
             patch("time.sleep"):
            mock_requests_session.get = mock_get
            with pytest.raises(PermanentHTTPError):
                session.get("https://example.com/doc.pdf")
        assert mock_get.call_count == 1


def test_500_is_retried_up_to_max_retries(session):
    test_settings = dataclasses.replace(real_settings, max_retries=3, request_delay_seconds=0)
    mock_get = MagicMock(return_value=_fake_response(500))

    with patch("gst_agent.http_client.settings", test_settings), \
         patch.object(session, "_session") as mock_requests_session, \
         patch("time.sleep"):
        mock_requests_session.get = mock_get
        with pytest.raises(requests.HTTPError):
            session.get("https://example.com/flaky.pdf")

    assert mock_get.call_count == 3  # genuine server error IS worth retrying


def test_429_is_retried_not_treated_as_permanent(session):
    # Rate limiting is transient by nature -- worth backing off and
    # retrying, unlike a 404/403/400.
    test_settings = dataclasses.replace(real_settings, max_retries=2, request_delay_seconds=0)
    mock_get = MagicMock(return_value=_fake_response(429))

    with patch("gst_agent.http_client.settings", test_settings), \
         patch.object(session, "_session") as mock_requests_session, \
         patch("time.sleep"):
        mock_requests_session.get = mock_get
        with pytest.raises(requests.HTTPError):
            session.get("https://example.com/rate-limited.pdf")

    assert mock_get.call_count == 2


def test_network_exception_is_still_retried(session):
    test_settings = dataclasses.replace(real_settings, max_retries=3, request_delay_seconds=0)
    mock_get = MagicMock(side_effect=requests.ConnectionError("connection reset"))

    with patch("gst_agent.http_client.settings", test_settings), \
         patch.object(session, "_session") as mock_requests_session, \
         patch("time.sleep"):
        mock_requests_session.get = mock_get
        with pytest.raises(requests.ConnectionError):
            session.get("https://example.com/doc.pdf")

    assert mock_get.call_count == 3


def test_successful_response_returned_without_retry(session):
    test_settings = dataclasses.replace(real_settings, max_retries=3, request_delay_seconds=0)
    ok_response = _fake_response(200)
    mock_get = MagicMock(return_value=ok_response)

    with patch("gst_agent.http_client.settings", test_settings), \
         patch.object(session, "_session") as mock_requests_session, \
         patch("time.sleep"):
        mock_requests_session.get = mock_get
        result = session.get("https://example.com/ok.pdf")

    assert result is ok_response
    assert mock_get.call_count == 1
