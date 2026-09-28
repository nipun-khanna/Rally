# Public venue discovery when Geoapify is unset

Implemented in `app/places.py`, the `search()` branch in `app/config.py`, and the proposal credit in `app/orchestrator.py`. Check results are in `docs/venue-demo-check.md`.

**Goal:** The old planner search returns real public venues for a named area when `RALLY_GEOAPIFY_API_KEY` is empty and demo venues are off.

**Architecture:** Keep Geoapify when a key is set, and keep the Midtown demo fixture only when demo venues are explicitly on. Otherwise `search()` geocodes with public Nominatim and reads `amenity=restaurant` from public Overpass, both inside `app/places.py`. Skip any element that has no name or no street address. Do not invent a name, address, cuisine, phone, opening, or booking. `source` is `openstreetmap`. The proposal line credits OpenStreetMap instead of saying the venue is demo data.

**Checked on 2026-09-27:** Temp-db `build_service` with demo flags off raises `PlacesError: Geoapify API key is missing` for Midtown, for a missing location, and for a city-only `Midtown`. `_recommend_restaurant` then replies `An Italian Table near Midtown, New York`. A read-only Nominatim lookup resolved Midtown. A read-only Overpass lookup returned named restaurants; Little Alley, Hard Rock Cafe, and Carbone included street addresses, and some nodes did not.

## Files

- Modify: `app/places.py` — public geocode and restaurant search
- Modify: `app/config.py` `search()` only — call that path when the Geoapify key is empty
- Modify: `app/orchestrator.py` attribution only — OSM source is not labeled demo venue data
- Test: `tests/test_places.py`
- Doc: `docs/venue-demo-check.md`

Do not edit the browser agent or runtime, `app/main.py`, recovery, or `tasks/todo.md`.

## Behavior

- Demo venues still return the labeled fixture and do not call the network.
- A Geoapify key still uses Geoapify only.
- No key: require a location, append `RALLY_DEFAULT_CITY` when the text has no comma, and reject an unclear city before any HTTP call.
- Charge two place-quota units before the public calls, matching geocode plus search. Stop with `Free place-search budget reached` and do not call the network when the cap cannot cover both.
- Nominatim then Overpass, 3 km, restaurants only, User-Agent `RallyVenueLookup/1.0 (+https://rallyplans.vercel.app)`. No API key and no owner browser profile.
- Keep a venue only when OSM provides `name` and `addr:street` (optional housenumber, city, state). Cuisine only from the `cuisine` tag. Order by distance. Cap at 20.
- HTTP, timeout, and malformed payloads raise `PlacesError`. An empty addressed set returns `[]`.
- Restaurant reply uses the returned name. It does not claim a booking.
- Proposal text for `source=openstreetmap` credits OpenStreetMap and does not say `Demo venue data`.

## Restaurant reply

`_recommend_restaurant` does not invent `An Italian Table` or `Green Table`. Those names appear only when search returns them. The explicit demo fixture is labeled `demo venue data`. A known diet or excluded-cuisine conflict is not recommended, and a diet is not claimed unless the venue tags say `vegetarian` or `vegan`.

`Reply 'Book it' for the demo reservation` remains the legacy local mock. It is not the Vapi restaurant-call path and it is not a production booking.

## Left outside this change

Calendar, the mock reservation simulator, and the dashboard are unchanged. `recover_pending` is unchanged by this reply fix.
