# Adaptive Rally requests

In an allowlisted group, an explicit request such as `Rally, build me a tracker` or `Rally, use tools to check our plan status` enters the adaptive path. Existing portal commands and public web lookup retain priority; ordinary direct questions use Rally's existing answer path.

The planner receives the current request and metadata for registered tools. It can select up to three validated steps. Currently registered read tools are group plan status and Rally's existing web research callback. No commitment tool is registered yet. A saved workflow does not carry approval. Future side effects must bind approval to the exact request, step, revision and argument hash.

When a tool is missing, Rally records the capability. If `RALLY_ADAPTIVE_CODE_PROPOSALS=1`, it asks Grok to draft code and stores that source in ignored `data/capability_proposals/` as an inert review artifact. Syntax checking uses `ast.parse`; Rally never imports, installs or runs the generated source. Generation adds a second xAI model call and can be disabled without disabling adaptive requests.

`RALLY_ADAPTIVE_ENABLED=0` disables this path. A working xAI key and at least one allowlisted chat are required. Set a separate `RALLY_ADMIN_TOKEN` to enable review access. Fetch proposal metadata and source from `GET /adaptive/admin/requests/{request_id}?include_source=true` with the `X-Rally-Admin-Token` request header. The group portal and webhook token do not grant review access. Protect the admin token: it grants source and request access wherever the backend is reachable.

State is stored in the configured Rally SQLite database. Requests are idempotent per chat and incoming message ID. A running step found after restart becomes uncertain and is never replayed automatically. The local review endpoint exposes request status but cannot approve, install or execute generated code.
