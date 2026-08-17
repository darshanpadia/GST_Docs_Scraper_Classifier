"""Central configuration for the GST document agent.

All tunables live here and are overridable via environment variables (or a
local .env file, see .env.example). Business logic modules must not read
os.environ directly -- they import from this module instead, so behaviour
can be changed without touching code.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

# Load a local .env file if present (never committed; see .env.example).
load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent


def _env_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    return int(value) if value not in (None, "") else default


def _env_float(name: str, default: float) -> float:
    value = os.environ.get(name)
    return float(value) if value not in (None, "") else default


def _env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value in (None, ""):
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


# Categories the classifier is allowed to assign. "Other" is always the
# fallback for anything that doesn't confidently match a rule.
#
# "Council Meeting" isn't one of the assignment's example categories -- it
# was added because gstcouncil.gov.in's real, actively-maintained meeting
# archive publishes an Agenda and Minutes PDF for every GST Council meeting,
# which are official GST-law-adjacent documents that don't fit any of the
# other categories (they're not Acts/Rules/Notifications/Circulars/Orders).
CATEGORIES = [
    "Act",
    "Rule",
    "Notification",
    "Circular",
    "Order",
    "Instruction",
    "Press Release",
    "Council Meeting",
    "Other",
]

# Keywords that mark a discovered item as administrative/irrelevant noise
# (mainly relevant for gstcouncil.gov.in, whose listings mix in HR/admin
# content alongside real GST-law documents). Case-insensitive substring match
# against the item's title/subject text.
IRRELEVANT_KEYWORDS = [
    "vacancy",
    "recruitment",
    "tender",
    "newsletter",
    "consultant appointment",
    "walk-in",
    "empanelment",
]


@dataclass(frozen=True)
class Settings:
    # --- paths ---
    base_dir: Path = BASE_DIR
    data_dir: Path = BASE_DIR / "data"
    downloads_dir: Path = BASE_DIR / "data" / "downloads"
    db_path: Path = BASE_DIR / "data" / "state.db"
    log_dir: Path = BASE_DIR / "data" / "logs"

    # --- run behaviour ---
    max_new_docs_per_run: int = field(
        default_factory=lambda: _env_int("MAX_NEW_DOCS_PER_RUN", 100)
    )

    # --- politeness / HTTP ---
    request_delay_seconds: float = field(
        default_factory=lambda: _env_float("REQUEST_DELAY_SECONDS", 1.5)
    )
    request_timeout_seconds: int = field(
        default_factory=lambda: _env_int("REQUEST_TIMEOUT_SECONDS", 30)
    )
    max_retries: int = field(default_factory=lambda: _env_int("MAX_RETRIES", 3))
    user_agent_contact: str = field(
        default_factory=lambda: os.environ.get(
            "USER_AGENT_CONTACT", "gst-docs-agent-contact-not-configured@example.com"
        )
    )

    # --- OCR ---
    # If native text extraction yields fewer than this many characters per
    # page (averaged), the page is treated as scanned/image-based and OCR is
    # attempted instead.
    ocr_min_chars_per_page: int = field(
        default_factory=lambda: _env_int("OCR_MIN_CHARS_PER_PAGE", 20)
    )
    tesseract_cmd: str | None = field(
        default_factory=lambda: os.environ.get("TESSERACT_CMD") or None
    )

    # --- sources ---
    enabled_sources: tuple[str, ...] = field(
        default_factory=lambda: tuple(
            s.strip()
            for s in os.environ.get(
                "ENABLED_SOURCES", "cbic,gstcouncil"
            ).split(",")
            if s.strip()
        )
    )

    # --- LLM fallback classification ---
    # Off by default: the rule-based classifier needs no API key and covers
    # the common cases. When enabled, it's used only for documents the
    # rule-based pass couldn't confidently categorize -- never as the primary
    # classifier -- and any failure (no key, network error, refusal) is
    # caught and treated as "stay Other", not a run-ending error.
    enable_llm_fallback: bool = field(
        default_factory=lambda: _env_bool("ENABLE_LLM_FALLBACK", False)
    )
    # Providers tried in this order (see gst_agent.llm_providers); "anthropic"
    # isn't in the default list since it isn't free -- add it yourself if you
    # have a key. Each provider is skipped (not an error) if its own API key
    # env var isn't set, so listing a provider you haven't configured is
    # harmless.
    llm_provider_order: str = field(
        default_factory=lambda: os.environ.get("LLM_PROVIDER_ORDER", "gemini,groq")
    )
    gemini_api_key: str | None = field(
        default_factory=lambda: os.environ.get("GEMINI_API_KEY") or None
    )
    gemini_model: str = field(
        default_factory=lambda: os.environ.get("GEMINI_MODEL", "gemini-flash-latest")
    )
    groq_api_key: str | None = field(
        default_factory=lambda: os.environ.get("GROQ_API_KEY") or None
    )
    groq_model: str = field(
        default_factory=lambda: os.environ.get("GROQ_MODEL", "openai/gpt-oss-20b")
    )
    # Anthropic's own SDK reads ANTHROPIC_API_KEY directly from the
    # environment (see llm_providers/anthropic_provider.py) -- no field
    # needed here for the key itself, only its model name.
    llm_model: str = field(
        default_factory=lambda: os.environ.get("LLM_MODEL", "claude-opus-5")
    )
    # How many distinct documents must independently get the same
    # LLM-proposed new category (cumulative across runs) before that category
    # is promoted into a real folder. Keeps a single hallucinated proposal
    # from creating folder sprawl while letting a genuinely recurring
    # document type earn its own place.
    category_promotion_threshold: int = field(
        default_factory=lambda: _env_int("CATEGORY_PROMOTION_THRESHOLD", 3)
    )

    @property
    def user_agent(self) -> str:
        # NOTE: the product token deliberately avoids common substrings like
        # "doc", "fetch", "zao" etc. Python's urllib.robotparser matches
        # robots.txt "User-agent:" rules by checking whether the LISTED bot
        # name is a *substring* of our UA (not an exact/whole-word match).
        # indiacode.nic.in's robots.txt disallows a bot literally named
        # "DOC" -- an earlier UA of "GST-Docs-Agent" was (harmlessly but
        # incorrectly) caught by that rule because "Docs" contains "doc".
        return (
            "GSTLawArchiver/1.0 "
            f"(+contact: {self.user_agent_contact}; educational/interview assignment)"
        )


settings = Settings()


def ensure_directories() -> None:
    """Create data/download/log directories (including per-category folders)."""
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.log_dir.mkdir(parents=True, exist_ok=True)
    for category in CATEGORIES:
        (settings.downloads_dir / category).mkdir(parents=True, exist_ok=True)
