#!/usr/bin/env python3
"""
Lightweight connectivity check for DATABASE_URL and REDIS_URL.

Usage:
  - Set environment variables DATABASE_URL and REDIS_URL (or pass flags)
  - python scripts/health_check.py [--db <db_url>] [--redis <redis_url>]

Exit codes:
  0 on full success, 1 if any check fails.
"""
from __future__ import annotations

import argparse
import os
import sys


def check_db(url: str) -> bool:
    try:
        from sqlalchemy import create_engine, text

        engine = create_engine(url, future=True)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        print(f"DB OK: {redact_url(url)}")
        return True
    except Exception as e:
        print(f"DB FAIL: {redact_url(url)} -> {e}")
        return False


def check_redis(url: str) -> bool:
    try:
        import redis

        r = redis.from_url(url)
        r.ping()
        print(f"Redis OK: {redact_url(url)}")
        return True
    except Exception as e:
        print(f"Redis FAIL: {redact_url(url)} -> {e}")
        return False


def redact_url(url: str) -> str:
    # Basic redaction of credentials in URLs
    try:
        from urllib.parse import urlsplit, urlunsplit

        parts = urlsplit(url)
        netloc = parts.netloc
        if "@" in netloc:
            # Replace credentials with '***'
            creds, host = netloc.split("@", 1)
            if ":" in creds:
                user, _ = creds.split(":", 1)
                netloc = f"{user}:***@{host}"
            else:
                netloc = f"***@{host}"
        return urlunsplit(
            (parts.scheme, netloc, parts.path, parts.query, parts.fragment)
        )
    except Exception:
        return url


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check DB and Redis connectivity")
    parser.add_argument(
        "--db", dest="db", default=os.getenv("DATABASE_URL"), help="Database URL"
    )
    parser.add_argument(
        "--redis",
        dest="redis",
        default=os.getenv("REDIS_URL") or os.getenv("CELERY_BROKER_URL"),
        help="Redis URL",
    )
    args = parser.parse_args(argv)

    ok = True
    if args.db:
        ok &= check_db(args.db)
    else:
        print("DB SKIP: DATABASE_URL not provided")

    if args.redis:
        ok &= check_redis(args.redis)
    else:
        print("Redis SKIP: REDIS_URL/CELERY_BROKER_URL not provided")

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
