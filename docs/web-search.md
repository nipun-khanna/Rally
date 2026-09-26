# Rally public web search

Rally can use xAI's Responses API `web_search` tool for directly addressed requests about public or current information, such as nearby food, weather, events, or news. Set `RALLY_WEB_ENABLED=1` with the existing xAI key. `RALLY_WEB_DAILY_LIMIT` defaults to 20 requests per UTC day and `RALLY_WEB_MAX_TOOL_CALLS` to 3 per request. The quota is persisted in SQLite and consumed before the provider call; an uncertain timeout is not retried automatically. Web search incurs xAI tool and model costs. The request sends only the latest addressed text and an abstract local group tone label to the web model, with `store=false`; it does not send surrounding group history or relationship-source texts.

The web client is read-only. It has no BlueBubbles, booking, calendar, code execution, filesystem or arbitrary MCP tool. Existing explicit approval rules govern those side effects. The model is told not to treat web pages as instructions and not to claim availability or completed actions without evidence. Replies include plain source URLs where returned. If search fails, Rally says current options could not be verified and records a single same-thread reply.

The tone hint is `casual`, `formal`, or `neutral`, inferred locally from up to twenty recent human messages. It guides informal or formal wording without copying a person's voice. Web responses can be slower and use the existing per-service lock while they run.

To verify without a group send, run `python -m pytest -q tests/test_web.py tests/test_tone.py` and call `GrokWebClient.answer` with a synthetic public query. For live group verification, send one explicitly labeled `Rally, find ...` message in an allowlisted chat and inspect its outbox status. Do not blindly retry uncertain sends.
