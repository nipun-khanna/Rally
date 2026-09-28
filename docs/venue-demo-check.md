# Venue demo check

Checked 2026-09-27. This is the old planner venue lookup used when a group
plan searches for a restaurant. It is not the restaurant phone workflow, and
it does not book a table.

No text was sent, no call was placed, and the production database was not
opened. The check used a temporary SQLite file. Demo venues stayed off.
`RALLY_GEOAPIFY_API_KEY` was empty.

## What was blocking it

`build_service(...).search_fn` raised `PlacesError: Geoapify API key is missing`
before any lookup. That happened for `Midtown, New York`, for a missing
location, and for `Midtown` with no default city.

The restaurant reply then said:

`An Italian Table near Midtown, New York for dinner — fits Midtown, New York. not a booking, just a rec.`

`An Italian Table` is not a searched venue. The stall proposal instead said
it could not search.

## Public fallback

With no Geoapify key, search geocodes through public Nominatim and reads
`amenity=restaurant` within 3 km from public Overpass. The request uses
`User-Agent: RallyVenueLookup/1.0 (+https://rallyplans.vercel.app)`. It does
not send an API key and it does not open the owner browser profile.

A venue is kept only when that OpenStreetMap element has a `name` and
`addr:street`. Housenumber, city, and state are included only when those
tags are present. Cuisine comes only from the `cuisine` tag. Elements
missing a name or a street are dropped. Results are ordered by distance and
capped at 20. Each search charges two units of the existing place quota
before either request. A transport or HTTP failure raises `PlacesError`.

`source` is `openstreetmap`. A proposal credits
`https://www.openstreetmap.org/copyright`. It does not say `Demo venue data`.
The labeled Midtown fixture still runs only when demo mode and demo venues
are both on. A configured Geoapify key still uses Geoapify only.

## Evidence

`python -m pytest tests/test_places.py tests/test_config.py tests/test_service.py tests/test_planning_bot_acceptance.py`

133 passed, 2 subtests passed.

The new tests failed first on `Geoapify API key is missing`, and the proposal
test failed on `I couldn't search for a venue right now`. They use a temp
database and a fake HTTP opener. They do not call Nominatim or Overpass.

A later read-only live search for `Midtown, New York` on a temp database
returned 10 venues, all `source=openstreetmap`. The nearest five were:

| Name | Address from OpenStreetMap tags |
| --- | --- |
| Tony's | 147 West 43rd Street, New York, NY |
| Hard Rock Cafe | 1501 Broadway, New York |
| Junior's | 1515 Broadway |
| Pera | 303 Madison Avenue |
| The Heavenly Burger | 291 Madison Avenue |

Hard Rock Cafe's street matched an earlier Overpass read of the same area.
The restaurant reply was:

`Tony's near Midtown, New York for dinner — Midtown, New York. not a booking, just a rec.`

One earlier Overpass read during a test-patch mistake returned HTTP 504.
The live check after that succeeded. No phone number was stored or shown.

## Restaurant reply

`_recommend_restaurant` names a place only when search returns it. A provider
error says venue lookup is unavailable. An empty result, or a result set
whose names and cuisine tags all conflict with a stated diet or an excluded
cuisine, asks which cuisine to try. A missing area asks which area to use
and does not call search. A diet note is repeated only when the chosen
venue's own tags include `vegetarian` or `vegan`. The explicit demo fixture
(`source=demo`) is still named and labeled `demo venue data`.

`Reply 'Book it' for the demo reservation` on a stall proposal is the legacy
labeled mock booking in the local reservation simulator. It is separate from
the Vapi restaurant-call path. Neither this lookup nor that mock line is a
production booking, and a search result is not a free table.

## Still required

- Nominatim and Overpass have to answer. Their published use expects a low rate and an identifying User-Agent. Rally's place cap still applies.
- OpenStreetMap rows with no `addr:street` are omitted, so a mapped restaurant can be absent.
- Geoapify remains unset. This path does not add Geoapify attribution.
- The restaurant phone path is unchanged: public page, then Browser Use, then the local reader, then an authorized Vapi dial. This lookup does not dial.
