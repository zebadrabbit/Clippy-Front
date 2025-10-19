#!/usr/bin/env python3
"""
Create the PostgreSQL database from DATABASE_URL if it doesn't exist.

Reads DATABASE_URL from the environment (or --db flag).
Uses the same credentials to connect to the 'postgres' maintenance DB
and issues CREATE DATABASE <dbname> if missing.
"""
from __future__ import annotations

import argparse
import os
import sys


def main(argv: list[str] | None = None) -> int:
    try:
        from sqlalchemy import create_engine, text
        from sqlalchemy.engine.url import make_url
    except Exception as e:
        print(f"SQLAlchemy not available: {e}")
        return 1

    parser = argparse.ArgumentParser(
        description="Create PostgreSQL database if missing"
    )
    parser.add_argument(
        "--db",
        dest="db",
        default=os.getenv("DATABASE_URL"),
        help="Database URL (postgresql://user:pass@host/dbname)",
    )
    args = parser.parse_args(argv)

    if not args.db:
        print("DATABASE_URL not provided. Set env or pass --db.")
        return 1

    url = make_url(args.db)
    if url.drivername.split("+")[0] != "postgresql":
        print(f"Only postgresql is supported. Got: {url.drivername}")
        return 1

    dbname = url.database
    server_url = url.set(database="postgres")
    engine = create_engine(server_url, isolation_level="AUTOCOMMIT", future=True)

    print(f"Ensuring database exists: {dbname}")
    try:
        with engine.connect() as conn:
            conn.execute(text(f'CREATE DATABASE "{dbname}"'))
        print("Database created.")
    except Exception as e:
        msg = str(e)
        if "already exists" in msg or "duplicate_database" in msg:
            print("Database already exists.")
        else:
            print(f"Failed to create database: {e}")
            return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
