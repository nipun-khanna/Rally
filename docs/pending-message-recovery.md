# Pending group extraction recovery

Inbound messages are persisted before conversation extraction. If extraction fails, the message remains unprocessed. That state intentionally blocks approval of proposals while earlier plan changes are unresolved. The periodic scheduler does not re-run old messages through `receive`, because that could repeat direct replies or interpret an old approval as a new action.

Recovery is a local operator action. Load `.env` into the shell as described in the README, then run:

```sh
.venv/bin/python -m scripts.recover_pending status
.venv/bin/python -m scripts.recover_pending run --apply
```

`status` prints the pending human-message count. `run` requires `--apply`; it sends the bounded stored conversation window for the one allowlisted group to the configured extractor. The default recovery window is 75 total messages and the command refuses a partial window. Use `--chat-id` only when more than one group is allowlisted, and `--limit` to set a reviewed window size.

Recovery calls only the extractor, updates the current plan through normal versioning, and then marks the covered pending human messages processed. It never sends a direct reply, books a venue, creates a calendar event, or processes old approval phrases. A provider failure leaves the messages pending. The command replaces the send function with a hard failure as a guard against accidental outbound messages.

This is intended for a bounded backlog. Large or ongoing backlogs need slicing with a persisted cursor and retry backoff before automatic recovery is enabled.
