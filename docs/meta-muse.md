# Meta Muse Spark extraction evaluation

## Role in Rally

Muse Spark is an **optional conversation extractor**. It produces the same
`PlanFacts` value as Grok extraction: activity, participants, availability,
preferences, objections, blockers, and cited message IDs. Grok remains the
agent that chooses `WAIT`, `NUDGE`, `ASK`, `PROPOSE`, or `ACT`. Muse does not
receive venue-search results, choose a tool, or authorize a reservation.

`app.muse.MuseExtractor` implements this boundary. It reuses Rally's extraction
prompt and validation, including participant and evidence checks. It calls
Meta's structured-output Chat Completions endpoint. The `evidence` field has
dynamic keys, so the request uses Meta's non-strict JSON-schema mode and
validates the result locally with Rally's typed schema.

## Access and cost, checked September 25, 2026

Meta's [Model API overview](https://dev.meta.ai/docs/overview) lists public
access to Muse Spark and the `https://api.meta.ai/v1` base URL. The
[structured-output guide](https://dev.meta.ai/docs/structured-output) describes
`response_format` on Chat Completions. The
[pricing page](https://dev.meta.ai/docs/pricing-rate-limits) lists token-based
pay-as-you-go pricing. LLM calls are the stated exception to Rally's free API
requirement. The standard models are not used to train Meta models according to
the pricing page; the contributor tier permits training on prompts and
completions. The adapter accepts only standard model IDs.

The Meta **Muse consumer agent** and the **Muse Spark model API** are different
products. Rally's integration uses only the model API. It has no access to a
group member's private Meta social graph, Instagram, or Facebook data. Its
social context comes only from group messages supplied to the extractor.

## Integration gate

The adapter can be used where the service currently calls `agent.extract`:

```python
from app.muse import MuseExtractor

extractor = MuseExtractor(
    api_key=meta_model_api_key,
    default_city=default_city,
    time_zone=time_zone,
)
facts = extractor.extract(recent_human_messages, previous_facts)
```

Use a `MODEL_API_KEY` from Meta's Model API dashboard. Keep the existing Grok
client for `decide`. A live deployment should enable Muse only after checking
its extracted facts against recorded, consented group-chat fixtures and a Grok
baseline, with special attention to objections, relative dates, participants,
and evidence citations. This workspace has no Meta key, so live accuracy and
latency are not yet measured. The adapter's request shape, parser, and
validation have offline tests in `tests/test_muse.py`.
