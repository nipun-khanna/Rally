# Pending group extraction recovery

Inbound messages are persisted before conversation extraction. If extraction fails, the message remains unprocessed. That state intentionally blocks approval of proposals while earlier plan changes are unresolved. The periodic scheduler does not re-run old messages through `receive`, because that could repeat direct replies or interpret an old approval as a new action.

Recovery is a local operator action. Load `.env` into the shell as described in the README, then run:

```sh
.venv/bin/python -m scripts.recover_pending status
.venv/bin/python -m scripts.recover_pending run --apply
```

`status` prints the pending human-message count and sanitized extraction error categories. The current old backlog predates this diagnostic field, so it appears as `not_recorded`. `run` requires `--apply` before settings are loaded or the extractor is built. It sends one ordered prefix, starting at the oldest pending human row, to the configured extractor. The default prefix is 75 messages. `--limit` must be from 1 through 200; a longer history stays pending for the next explicit run. Use `--chat-id` only when more than one group is allowlisted.

Recovery calls only the extractor, then marks processed only the pending human ids inside that prefix. It never sends a direct reply, books a venue, creates a calendar event, or processes old approval phrases. A sent `direct_reply` does not clear a row by itself. A provider failure leaves the included rows pending. The command replaces the send function with a hard failure as a guard against accidental outbound messages.

`save_plan` replaces `last_human_at` when the stored facts change, and a `DONE` or `ABANDONED` plan is not updated in place: the next save inserts a new current row. A prefix that ends before a newer processed human message, or before the current plan's `last_human_at`, is a historical slice. Recovery still extracts it and acks the included pending ids, and it does not call `save_plan`. The newer date, location, version, proposal, and abandoned state stay as they are.

Those historical facts are not merged into the newer plan. A merge cannot tell which older fields the later processed messages superseded and which they left unchanged, so the extracted facts are dropped for plan state. A prefix that already reaches the newest processed human message, and whose newest human timestamp is at least `last_human_at`, still follows the normal save path.

New extraction failures record only attempt count, stage, broad error kind and optional HTTP status. Message text and provider response bodies are not copied into these diagnostics.

Each explicit run continues from the oldest row that is still pending. Automatic recovery stays off until a persisted cursor and retry backoff exist. The scheduler does not re-enter `receive`.
