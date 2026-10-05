# ADR 0001: Imagery wire contract

**Status:** Accepted, 2026-09-29. Amended 2026-10-02 (PR #844 review, before release): `layer_id` and `source` added; the flat tile fields removed.
**Scope:** the `imagery` value in `/api/chat` tool updates and in dashboard map-widget configs.

## Context

Imagery went over the wire as `ImageryState`: one flat model where almost every field was optional, shared by Planet and Sentinel-2. There was no wire contract. The model was dumped into untyped state and read field by field on both sides. Shared field names meant different things per provider: Planet's `mosaic_id` was made up, and the dates were a calendar month for Planet but the dates scenes were captured for Sentinel-2. When the shape changed in #800, the frontend broke, and the drift was only noticed in the browser.

## Decision

A discriminated union, `Imagery = PlanetImagery | Sentinel2Imagery` (on `provider`), built on an abstract `ImageryBase` with a `LayerPeriod`, an opaque `layer_id` and a `RasterSource` (`tiles`, `bounds`, `minzoom`, `maxzoom`). The backend is strict when it builds payloads. The published schema is tolerant. Everything lives in `src/shared/imagery`.

## Why

- **Two things, two types.** The providers share very little, and the fields they do share mean different things. One type with optionals couldn't enforce either shape. With specialists, every field is required, except `scenes`, which is required but can be `null` because old cached mosaics really have no scene statistics.
- **Consumers stay provider-agnostic (Liskov).** `ImageryBase` carries only what every reader needs: provider, period, areas, a layer id, a raster source, and `label()`. Readers use the base and never branch on `provider`; a specialist adds details by overriding `label()`.
- **The period is an object, and its dates are stored.** "When is this layer from" means a month for Planet and a search window for Sentinel-2, and the search window's end depends on the day the search ran. So each period computes `start`/`end` once, when it's built, rather than working them out later.
- **Strict producer, tolerant reader (robustness principle).** `extra="forbid"` makes drift fail on the backend, where the payload is built. The published schema leaves out `additionalProperties: false`, so adding a field never breaks the frontend.
- **Stable abstractions, unstable details.** `contract` (abstract, depended on) and `wire` (the union) are what consumers import. The specialists change more often, and a fitness function stops anything other than `wire` and each specialist's own provider from importing them. A union has to name its members, so this boundary is what keeps their coupling low.
- **`src/shared`, not `src/agent`.** The API and the agent both need the contract. The `src.agent.imagery` package pulls in boto3/pystac when imported, and the API shouldn't depend on the agent.
- **No lockstep deploys.** Stored payloads (checkpoints, widget configs) keep the shape they were written in, so readers try the contract first and fall back to legacy. That lets frontend and backend ship independently in an expand/contract rollout (`docs/imagery/rollout-plan.md`).

## Alternatives rejected

- **Keep one flat model and document which fields each provider uses:** nothing would enforce it, which is the problem we already had.
- **One state key per provider:** only one imagery layer is current at a time, and every reader would branch on the key.
- **A version field instead of the discriminator:** `provider` already decides the shape. Versions are tracked in the contract document.

- **The layer draws from one object, and names itself.** `source` has the keys of a MapLibre raster source, so the frontend passes it on as it is. That replaces Planet's flat bounds and zooms, and Sentinel-2's TileJSON round trip. `layer_id` replaces deriving an id from `mosaic_id` or the tile URL. It's required and opaque, so a replayed request updates its layer instead of adding a duplicate.

## Consequences

- The frontend must read both shapes until phase 4. Legacy payloads need a converter (phase 3).
- The specialists sit at D ≈ 0.67 from the main sequence. That's accepted, and contained by the import boundary.
- The Sentinel-2 end-of-window clamp exists twice (in the period and in the mosaic search), tied together by a consistency test.
- Known gap: on a mosaic cache hit, the Sentinel-2 period can extend past the mosaic's scenes (ticket filed).
