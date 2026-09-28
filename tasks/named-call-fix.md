# Named call routing fix

Observed request: `rally call Tarun ask him when hes free`. The request was processed as conversation, its reply claimed a call, and the call-attempt table is empty.

- [x] Trace the actual request and response and identify the routing gap.
- [ ] Add failing regressions for named-call routing, unique local contacts, ambiguity, missing contacts, task overrides, and duplicate webhook delivery.
- [ ] Resolve contacts locally and route explicit name-based call commands through the durable Vapi handler. Never let an unresolved call command fall through to the model.
- [ ] Send the requested task to the voice assistant and acknowledge only a provider-backed call attempt.
- [ ] Verify focused and full tests, prepare the real contact payload without posting it, and restart the existing server with publication off.
- [x] Persist named-call purpose and report the callee's actual answers from role-tagged Vapi evidence for any requested task.

No real call, message, deployment, or historical request replay is part of this fix.
