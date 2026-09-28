# Recovery demo check — 2026-09-27

## Runtime retry

Normal runtime does not need an automatic pending retry. `app/main.py` was not changed.

`build_service` defers plan extraction to one thread-pool job after `receive` stores the human row. A direct reply can already have been sent. `mark_processed` runs after extraction succeeds. On extraction failure, a row that already has a `direct_reply` is marked processed inside `_extract_and_learn`; a row without one stays pending and records a sanitized diagnostic.

The scheduler in `periodic` calls `service.tick` and `deliver_pending`. `tick` expires stale proposals, books an approval that is already stored, runs intervention and stall revival, and delivers the outbox. It does not call `receive` or `recover_pending`.

The audited backlog matches that path. Seventy rows are `attempts=0` / `not_recorded`, so the failure recorder never ran. Thirteen of those already have a sent `direct_reply`, and their plan extract never finished. The remaining row is one `extract` / `validation` failure with no reply. Every pending `sent_at` is from before the process that was running at 09:24 UTC. Newer human rows in the same groups are already processed.

An automatic sweep would either re-enter `receive` (another reply, or an old approval treated as a new booking) or call the extractor on stored group text without `--apply`. Clearing the thirteen replied rows because a reply exists would skip the unfinished extract. `docs/pending-message-recovery.md` already keeps automatic recovery off until a persisted cursor and backoff exist. That work stays out of this change.

## Prefix recovery

`Store.recovery_snapshot` now takes one ordered prefix of at most `limit` messages, starting at the oldest pending human row (`sent_at`, then `message_id`). Limits outside 1 through 200 still raise `Invalid recovery limit`. A longer history no longer raises `Pending conversation exceeds bounded recovery window`.

`RallyService.recover_pending` keeps the default limit of 75. It extracts that prefix only when it contains at least one pending human id, and `mark_processed_many` runs only after `extract` returns. Ids outside the prefix stay pending, including a later row that already has a sent `direct_reply`. A provider error records the diagnostic for the included pending ids and leaves them unprocessed. The send function is still replaced by a hard failure in the CLI.

## Chronology

`save_plan` writes the passed timestamp over `last_human_at` when facts change. If the current row is `DONE` or `ABANDONED`, it ignores that row and inserts a new current plan. A prefix that stops before a newer processed human message was applying historical extractor facts through that path: the live plan's date and location moved backward, and an abandoned plan was replaced by a new active row.

A prefix may call `save_plan` only when no processed human row sorts after its last message and, when a plan exists, `last_human_at` is no newer than the newest human timestamp in the prefix. Otherwise the included pending ids are still acked after a successful extract, and the current plan id, version, facts, state, proposal, and `last_human_at` stay put.

Historical facts are not merged into the newer plan. Later processed messages are not in the prefix, so recovery cannot tell a superseded date, location, activity, or abandoned flag from a field those messages left unchanged. That limitation is also in `docs/pending-message-recovery.md`.

`scripts/recover_pending.py` rejects `run` without `--apply`, and rejects `--limit` outside 1 through 200, before `Settings.from_env` and `build_service`. `status` is unchanged and does not call the model.

This session did not run `status` or `run --apply` against the production database. No model context was sent, no call was placed, no text was sent, and nothing was deployed. Auto-review did not reject the pytest command.

`docs/pending-message-recovery.md` now describes the ordered prefix, the `--apply` guard, and the decision to drop historical facts instead of merging them.

## Tests

Red run, before the production edit: the five prefix tests failed with `Pending conversation exceeds bounded recovery window`. The two CLI guard tests failed with `AssertionError: must not load settings or build the service`. Five existing tests passed.

Green run after the edit:

```text
.venv/bin/python -m pytest tests/test_recovery.py -q --tb=short
............                                                             [100%]
12 passed in 0.41s
```

Chronology follow-up, before the guard: `test_historical_prefix_keeps_newer_plan_and_acks_old_pending` failed with version `2 == 1` and lunch facts at `12:00` UTC. `test_historical_prefix_does_not_revive_abandoned_plan` failed because `get_plan` returned a new id.

After the guard:

```text
.venv/bin/python -m pytest tests/test_recovery.py -q --tb=line
..............                                                           [100%]
14 passed in 0.41s
```
