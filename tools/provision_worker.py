"""Generate a one-time worker token and a SQL statement storing only its SHA-256 hash."""

import argparse
import hashlib
import secrets
from datetime import datetime, timedelta, timezone


def sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--node-id", required=True, help="Unique worker identifier, 2-64 characters")
    parser.add_argument("--expires-in-days", type=int, default=90, help="Credential lifetime (default: 90 days)")
    args = parser.parse_args()

    if not 2 <= len(args.node_id) <= 64:
        parser.error("--node-id must contain between 2 and 64 characters")
    if not 1 <= args.expires_in_days <= 365:
        parser.error("--expires-in-days must be between 1 and 365")

    token = secrets.token_urlsafe(48)
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    expiry = (datetime.now(timezone.utc) + timedelta(days=args.expires_in_days)).isoformat()

    print("ONE-TIME WORKER TOKEN (copy it now; FLOPPI stores only its hash):")
    print(token)
    print("\nRun this SQL in the Supabase SQL Editor:")
    print(
        "insert into public.worker_credentials (node_id, token_hash, expires_at, active) values ("
        f"{sql_literal(args.node_id)}, {sql_literal(digest)}, "
        f"{sql_literal(expiry)}, true);"
    )
    print("\nSet this in the worker's environment:")
    print(f"$env:FLOPPI_NODE_ID = {sql_literal(args.node_id)}")
    print(f"$env:FLOPPI_NODE_TOKEN = {sql_literal(token)}")
    print("\nDo not commit or send the token in screenshots/logs.")


if __name__ == "__main__":
    main()
