"""Explicit operator entry point; API requests never send external notifications."""

import argparse
import json
import sys
import time
from collections.abc import Sequence
from datetime import UTC, datetime

from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from projects_service.config import Settings
from projects_service.database import create_database_engine
from projects_service.module6_client import Module6Client
from projects_service.notification_delivery import dispatch
from projects_service.notification_repository import NotificationOutbox


def batch_size(value: str) -> int:
    size = int(value)
    if not 1 <= size <= 100:
        raise argparse.ArgumentTypeError("Use a batch of 1 to 100 events")
    return size


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Module 6 durable notification worker")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status", help="Counts only; no payloads or HTTP calls")
    listing = commands.add_parser("list", help="List event IDs and delivery state, never payloads")
    listing.add_argument(
        "--status",
        choices=["pending", "sending", "delivered", "blocked", "failed", "uncertain"],
        default="uncertain",
    )
    listing.add_argument("--limit", type=batch_size, default=50)
    once = commands.add_parser("dispatch", help="Dispatch one bounded batch")
    once.add_argument("--batch-size", type=batch_size, default=50)
    run = commands.add_parser("run", help="Poll continuously in a dedicated worker")
    run.add_argument("--batch-size", type=batch_size, default=50)
    run.add_argument(
        "--poll-seconds", type=int, choices=range(5, 301), default=10, metavar="5..300"
    )
    retry = commands.add_parser("retry", help="Manually requeue a blocked/failed delivery")
    retry.add_argument("event_id")
    retry.add_argument(
        "--acknowledge-duplicate-risk",
        action="store_true",
        help="Also allow uncertain events; confirm delivery with the receiver first",
    )
    args = parser.parse_args(argv)
    try:
        settings = Settings()
        if args.command in {"dispatch", "run"} and not settings.module6_enabled:
            print("Module 6 delivery is disabled.", file=sys.stderr)
            return 2
        engine = create_database_engine(settings)
        try:
            outbox = NotificationOutbox(engine)
            if args.command == "status":
                print(json.dumps(outbox.counts(), sort_keys=True))
                return 0
            if args.command == "list":
                print(json.dumps(outbox.list_events(args.status, args.limit), sort_keys=True))
                return 0
            if args.command == "retry":
                accepted = outbox.retry(
                    args.event_id,
                    datetime.now(UTC),
                    acknowledge_duplicate_risk=args.acknowledge_duplicate_risk,
                )
                print("Delivery requeued." if accepted else "Delivery not eligible for retry.")
                return 0 if accepted else 2
            assert settings.module6_key is not None
            sender = Module6Client(
                settings.module6_endpoint, settings.module6_key.get_secret_value()
            )
            while True:
                attempted = dispatch(outbox, sender, limit=args.batch_size)
                print(
                    json.dumps({"attempted": attempted, "states": outbox.counts()}, sort_keys=True),
                    flush=True,
                )
                if args.command == "dispatch":
                    return 0
                time.sleep(args.poll_seconds)
        finally:
            engine.dispose()
    except KeyboardInterrupt:
        return 0
    except (ValidationError, SQLAlchemyError, ValueError, OSError):
        print(
            "Notification worker unavailable. "
            "Check private configuration and explicit schema migration.",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
