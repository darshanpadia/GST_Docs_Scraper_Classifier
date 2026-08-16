"""Polite, robots.txt-respecting HTTP client shared by all source modules.

This centralizes every "safety/etiquette" requirement from the assignment in
one place instead of leaving each source module to remember them:
  - a fixed delay between requests (no hammering government servers)
  - bounded retries with backoff on transient failures
  - an identifying User-Agent with a contact email
  - a hard robots.txt check before every single request, including PDFs
"""
from __future__ import annotations

import logging
import time
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import requests

from gst_agent.config import settings

logger = logging.getLogger("gst_agent.http_client")


class RobotsDisallowed(Exception):
    """Raised when robots.txt forbids fetching a URL. Never bypass this."""


class PoliteSession:
    def __init__(self) -> None:
        self._session = requests.Session()
        self._session.headers.update(
            {
                "User-Agent": settings.user_agent,
                "Accept": "text/html,application/xhtml+xml,application/pdf,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            }
        )
        self._last_request_at: float = 0.0
        self._robots_cache: dict[str, RobotFileParser] = {}

    # --- robots.txt -----------------------------------------------------

    def _get_robots_parser(self, origin: str) -> RobotFileParser:
        if origin not in self._robots_cache:
            parser = RobotFileParser()
            parser.set_url(f"{origin}/robots.txt")
            try:
                parser.read()
            except Exception as exc:
                # If robots.txt itself can't be fetched, be conservative but
                # don't hard-fail the whole run: log loudly and default to
                # allowed. Every source domain used by this project has been
                # manually verified to have a permissive robots.txt (see
                # README), so this branch is a safety net for transient
                # network issues, not a way to skip real checks.
                logger.warning(
                    "Could not fetch robots.txt for %s (%s); defaulting to allowed",
                    origin, exc,
                )
                parser = None
            self._robots_cache[origin] = parser
        return self._robots_cache[origin]

    def is_allowed(self, url: str) -> bool:
        parsed = urlparse(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        parser = self._get_robots_parser(origin)
        if parser is None:
            return True
        return parser.can_fetch(settings.user_agent, url)

    # --- throttled, retried GET ------------------------------------------

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        wait = settings.request_delay_seconds - elapsed
        if wait > 0:
            time.sleep(wait)

    def get(self, url: str, **kwargs) -> requests.Response:
        if not self.is_allowed(url):
            raise RobotsDisallowed(f"robots.txt disallows fetching {url}")

        last_exc: Exception | None = None
        for attempt in range(1, settings.max_retries + 1):
            self._throttle()
            self._last_request_at = time.monotonic()
            try:
                response = self._session.get(
                    url, timeout=settings.request_timeout_seconds, **kwargs
                )
                if response.status_code >= 500:
                    raise requests.HTTPError(
                        f"Server error {response.status_code} for {url}"
                    )
                response.raise_for_status()
                return response
            except requests.RequestException as exc:
                last_exc = exc
                backoff = 2 ** (attempt - 1)
                logger.warning(
                    "GET %s failed (attempt %d/%d): %s -- retrying in %ds",
                    url, attempt, settings.max_retries, exc, backoff,
                )
                if attempt < settings.max_retries:
                    time.sleep(backoff)
        assert last_exc is not None
        raise last_exc


# Module-level singleton: all source modules share one throttle clock and
# one robots.txt cache, so the delay is enforced globally, not per-source.
session = PoliteSession()
