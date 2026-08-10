"""One-off maintenance script: backfill historical exercise_data from the old
AWS account into the new one.

NOT part of the deployed service -- run manually, once, from a checkout.
See docs/runbooks/data-migration-backfill.md before running this for real.

Hard constraint (see CLAUDE.md): the old account is read-only reference
material. This script only ever Scans it -- it never calls PutItem,
UpdateItem, or DeleteItem against the old-account session. All writes go to
the new account via --new-profile.

Safety: never overwrites an existing item in the new account's table. Real
post-cutover syncs (2026-08-07 onward, per docs/architecture.md step 8) are
detected by their (uid, date) key already being present in the new account
and are skipped, not overwritten. Defaults to --dry-run; pass --execute to
actually write.

Usage:
    uv run python scripts/backfill_from_old_account.py --dry-run
    uv run python scripts/backfill_from_old_account.py --execute
"""

from __future__ import annotations

import argparse
import logging

import boto3

logging.basicConfig(level=logging.INFO, format="%(levelname)-8s %(message)s")
logger = logging.getLogger(__name__)


class ReadOnlyTable:
    """Wraps a boto3 Table resource, exposing only Scan/Query/GetItem.

    Deliberately has no put_item/update_item/delete_item passthrough -- the
    old-account table is never given the chance to be written to by this
    script, structurally, not just by convention.
    """

    def __init__(self, table):
        self._table = table

    def scan_all(self):
        response = self._table.scan()
        yield from response["Items"]
        while "LastEvaluatedKey" in response:
            response = self._table.scan(ExclusiveStartKey=response["LastEvaluatedKey"])
            yield from response["Items"]


def _table(profile: str | None, table_name: str):
    session = boto3.Session(profile_name=profile) if profile else boto3.Session()
    return session.resource("dynamodb").Table(table_name)


def backfill(old_profile: str | None, new_profile: str, table_name: str, execute: bool) -> None:
    old_table = ReadOnlyTable(_table(old_profile, table_name))
    new_table = _table(new_profile, table_name)

    scanned = 0
    would_write = 0
    skipped_existing = 0

    for item in old_table.scan_all():
        scanned += 1
        uid, date = item.get("uid"), item.get("date")
        if uid is None or date is None:
            logger.warning("Skipping item with no uid/date key: %s", item)
            continue

        existing = new_table.get_item(Key={"uid": uid, "date": date}).get("Item")
        if existing is not None:
            skipped_existing += 1
            continue

        would_write += 1
        if execute:
            new_table.put_item(Item=item)

        if scanned % 100 == 0:
            logger.info("Progress: scanned=%d would_write=%d skipped=%d", scanned, would_write, skipped_existing)

    verb = "Wrote" if execute else "Would write (dry run -- pass --execute to write for real)"
    logger.info(
        "Done. Scanned %d old-account items. %s %d. Skipped %d already present in the new account.",
        scanned,
        verb,
        would_write,
        skipped_existing,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--old-profile",
        default=None,
        help="AWS CLI profile for the OLD account (read-only). Default: the default profile.",
    )
    parser.add_argument(
        "--new-profile",
        default="polar-app-prod",
        help="AWS CLI profile for the NEW account (write target). Default: polar-app-prod.",
    )
    parser.add_argument("--table", default="exercise_data", help="Table name (same in both accounts).")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Report what would happen; write nothing (default).")
    mode.add_argument("--execute", action="store_true", help="Actually write to the new account.")
    args = parser.parse_args()

    backfill(
        old_profile=args.old_profile,
        new_profile=args.new_profile,
        table_name=args.table,
        execute=args.execute,
    )


if __name__ == "__main__":
    main()
