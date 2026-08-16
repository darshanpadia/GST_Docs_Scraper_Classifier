"""CLI entrypoint for the GST document agent.

Usage:
    python -m gst_agent.main --once            Run one discover/download/classify pass.
    python -m gst_agent.main --stats            Show current DB state and exit.
    python -m gst_agent.main --retry-failed     Retry documents stuck in a failed state.
    python -m gst_agent.main --loop             Run --once every --interval-hours (default
                                                 24) until killed. A convenience for demos
                                                 and non-Windows use -- the documented
                                                 production mechanism is an OS scheduler
                                                 (Windows Task Scheduler / cron) invoking
                                                 --once once a day. See README.
"""
from __future__ import annotations

import argparse
import json
import sys
import time

from gst_agent import db, pipeline
from gst_agent.config import ensure_directories, settings
from gst_agent.logging_setup import configure_logging


def cmd_stats() -> int:
    with db.open_db(settings.db_path) as conn:
        stats = db.get_stats(conn)
    print(json.dumps(stats, indent=2))
    return 0


def cmd_once() -> int:
    with db.open_db(settings.db_path) as conn:
        result = pipeline.run_once(conn)
    print(json.dumps(result, indent=2))
    return 0


def cmd_retry_failed() -> int:
    with db.open_db(settings.db_path) as conn:
        result = pipeline.retry_failed(conn)
    print(json.dumps(result, indent=2))
    return 0


def cmd_loop(interval_hours: float) -> int:
    while True:
        cmd_once()
        time.sleep(interval_hours * 3600)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gst_agent", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--once", action="store_true", help="Run a single discover/download/classify pass.")
    group.add_argument("--stats", action="store_true", help="Print document counts by status/category and exit.")
    group.add_argument("--retry-failed", action="store_true", help="Retry documents currently in a failed state.")
    group.add_argument("--loop", action="store_true", help="Run --once every --interval-hours (default 24) until killed.")
    parser.add_argument(
        "--interval-hours", type=float, default=24.0, help="Interval for --loop, in hours (default: 24)."
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    ensure_directories()
    configure_logging(settings.log_dir)

    if args.once:
        return cmd_once()
    if args.stats:
        return cmd_stats()
    if args.retry_failed:
        return cmd_retry_failed()
    if args.loop:
        return cmd_loop(args.interval_hours)

    print("No action specified. Try: python -m gst_agent.main --once")
    return 1


if __name__ == "__main__":
    sys.exit(main())
