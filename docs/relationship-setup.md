# Private relationship reminders

Rally can track calls, visits, messages, and other contact; send private reminders;
and suggest a contact rhythm using confirmed events or selected text conversations.
Monitoring runs locally without a model. Selected text history is never sent to
Grok or exported to the group portal.

## Choose the reminder conversation

Use an existing **direct iMessage conversation GUID**, not a group. With the current
shared iMessage account, its other recipient sees the reminders. This does not
create a new Rally contact. A dedicated account can be configured later.

From the repository root, using the Python environment with the app dependencies:

```sh
python -m scripts.configure_relationships configure \
  --destination 'iMessage;-;YOUR_PRIVATE_THREAD' \
  --zone America/New_York --hour 18
python -m scripts.configure_relationships status
```

The default owner is `local-imessage-account`, so commands sent from the current
account work. For an external owner, place `--owner 'EXACT_INCOMING_HANDLE'` before
the subcommand. Configuration is private SQLite data; no secrets or imported texts
are printed by status. `--database` can select a different SQLite file and must
match `RALLY_DATABASE_PATH` used by the running app. Use one app worker/process;
startup recovery marks interrupted sends uncertain.

No messages are sent by these setup commands. Destination changes cancel queued
messages for the previous destination. An in-progress send cannot be recalled.

## Requests in the selected private conversation

Start each request with `Hey Rally`:

- `remind me to call Mom every week`
- `remind me to message Sam every 10 days`
- `I called Mom today` or `I visited Mom yesterday`
- `I called Mom on 2026-09-25`
- `relationship status`
- `change Mom to every 10 days`
- `snooze Mom until Friday` or `snooze Mom until 2026-10-02`
- `pause reminders for Mom`, `resume reminders for Mom`, `remove Mom`
- `suggest cadence for Sam`, then `accept cadence for Sam` if you agree

Calls and visits require your confirmation. A text never counts as a call. Unknown
contact produces a question rather than a claim that you have not connected.
Cadences are 1–90 calendar days. Ambiguous dates/names ask for clarification.
Reminders arrive after the configured local hour and before midnight, once per
due cycle. Confirming relevant contact resets the cycle. An uncertain send is
shown in status and is not automatically retried.

## Select learning sources

Global group archive reading remains controlled by `RALLY_HISTORY_ENABLED`; it can
stay `0`. Personal learning has a separate, explicit selection list.

Create a messaging relationship first, in the private conversation or locally:

```sh
python -m scripts.configure_relationships add-relationship \
  --name Sam --mode message --days 7
python -m scripts.configure_relationships add-source \
  --chat 'iMessage;-;SELECTED_CONVERSATION' --relationship Sam
python -m scripts.configure_relationships sources
python -m scripts.configure_relationships disable-source \
  --chat 'iMessage;-;SELECTED_CONVERSATION'
python -m scripts.configure_relationships enable-source \
  --chat 'iMessage;-;SELECTED_CONVERSATION'
python -m scripts.configure_relationships remove-source \
  --chat 'iMessage;-;SELECTED_CONVERSATION'
```

The running app imports available text history in resumable pages and observes new
messages. No attachments are imported. Coverage is shown in `sources`; it describes
an available-history scan, not proof of a consistent snapshot during edits. Full
reconciliation runs hourly, page by page. Failed scans do not discard unseen rows.

At least four distinct outbound human contact days can produce a median-gap rhythm
suggestion. Incoming-only texts, reactions, deleted messages, and Rally replies do
not count. Live source contact resets **messaging** reminders only. Suggestions
require acceptance and never silently change your preferred cadence.

Disabling stops reads and excludes source evidence from active reminders and
suggestions while preserving its private stored texts. Removal deletes source
texts and derived evidence; manual confirmations remain. A selected group becomes
local learning only: new messages and scheduled planning for it are excluded from
Grok and portal publishing, including while disabled. Removing the source restores
normal group behavior if it is allowlisted. Previously published snapshots and
caches cannot be guaranteed erased immediately by this selection.

Local relationship state is stored in `rel_*` tables inside the ignored database.
Protect local backups as you would the original Messages database. Nothing here
enables monitoring of an unselected conversation.
