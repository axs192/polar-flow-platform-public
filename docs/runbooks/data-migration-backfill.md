# Runbook: backfill historical exercise data from the old account

**Run this last** — after the web app + `exercise-insights` changes are built,
tested, and confirmed working end-to-end. Without a backfill, the coach only
sees data from the 2026-08-07 EXERCISE-path cutover forward (per
`docs/architecture.md` step 8, item 9), and most of the exercise prompt's
VALIDITY RULES (28-day metrics need ≥14 days, 90-day need ≥40) will report
"insufficient data" for everything until enough real time has passed on its
own — a backfill is what fixes that immediately instead of waiting weeks.

## Hard constraint

The old account is read-only reference material (`CLAUDE.md`'s Hard
Constraints) — full stop, no exceptions for this migration.
`scripts/backfill_from_old_account.py` enforces this structurally (its
`ReadOnlyTable` wrapper around the old-account session has no
put/update/delete methods at all), but the operational discipline matters
too: never run any AWS CLI command against the old account's profile in this
runbook beyond read-only ones (`scan`, `get-item`, `describe-table`).

## Before running

1. Confirm the new account's real post-cutover data is actually there (sanity
   check that step 8 landed, not a hard requirement of this script, but worth
   knowing before backfilling around it):

   ```sh
   aws dynamodb scan --table-name exercise_data --profile polar-app-prod \
     --select COUNT --query 'Count'
   ```

2. Get a rough sense of the old account's data volume, so the dry run's
   numbers are sane against something concrete:

   ```sh
   aws dynamodb scan --table-name exercise_data --select COUNT --query 'Count'
   ```

   (No `--profile` — this uses the default profile, which per `CLAUDE.md` is
   the old account.)

## Step 1 — dry run

```sh
cd services/exercise-insights
uv run python scripts/backfill_from_old_account.py --dry-run
```

Review the printed counts: `scanned` (total old-account items), `would_write`
(items missing from the new account — these are the real backfill target),
`skipped` (items whose `(uid, date)` key already exists in the new account —
these are left alone, never overwritten, so real post-cutover syncs can't be
clobbered by this script even accidentally).

If `would_write` looks wrong (e.g. suspiciously low, or includes dates you'd
expect to already be covered), stop and investigate before proceeding — this
is exactly the kind of one-time, hard-to-cleanly-reverse operation on real
data that's worth double-checking rather than rushing.

## Step 2 — get the go-ahead

**This needs your explicit confirmation before running for real** — same as
every other action in this repo that writes to live AWS state. Nothing past
this point should run unattended.

## Step 3 — execute

```sh
uv run python scripts/backfill_from_old_account.py --execute
```

Re-run the dry run afterward (`--dry-run`) — `would_write` should now be `0`
(everything that was missing is now present, and re-running is safe/idempotent
either way since existing items are always skipped, never overwritten).

## Step 4 — verify from the app's own perspective

Ask the coach something that needs 28- or 90-day history — the VALIDITY RULES
in the exercise prompt should now find enough real historical data instead of
reporting "insufficient data" for those windows.

## Scope

`exercise_data` only, matching what the web app's `get_my_training_data` tool
actually uses. `health_metrics` isn't backfilled here — there's no
health-insights feature built on it yet (see `docs/architecture.md`'s Open
Items), so it's an optional future follow-up, not required for this.
