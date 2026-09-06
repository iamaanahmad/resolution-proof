# Resolution Proof

Resolution Proof checks one caller-supplied public JSON source for a decisive market result.

It returns one of four explicit states:

- `READY`: the selected scalar is decisive.
- `WAIT`: the source does not publish a decisive value yet.
- `AMBIGUOUS`: the selected value cannot support one decision.
- `BLOCKED`: the source could not be checked safely.

The released play is public at [iamaanahmad/resolution-proof@0.1.0](https://play.modiqo.ai/iamaanahmad/resolution-proof@0.1.0).

## Run the released play

Rote 0.80.0 and Python 3.9 or newer are required.

```bash
rote play run iamaanahmad/resolution-proof@0.1.0 \
  market_question='Is the USGS GeoJSON feed structurally available?' \
  resolution_rule='Resolve YES when the caller-supplied USGS source reports FeatureCollection.' \
  source_url='https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_hour.geojson' \
  json_pointer='/type' \
  expected_value='FeatureCollection'
```

The play records the rule but does not interpret its prose.
The caller must supply the correct rule, source, JSON Pointer, and expected value.
The play does not claim that a source is official.

## Safety

The default run is read-only.
Remote sources must use public HTTPS.
Private and loopback network targets are rejected.
Responses larger than 1 MiB are rejected.
Optional receipts use mode `0600` and stay in the local workspace.

## Judge proof

The pinned public release passed every required state on September 6, 2026.

| Response | Case | Result | Verified | Evidence |
|---|---|---|---|---|
| `@4` | Deterministic match | `READY` | `true` | Actual value `YES` matched `YES`. |
| `@8` | Missing pointer | `WAIT` | `true` | `/resolution/missing` returned no value. |
| `@12` | Collection pointer | `AMBIGUOUS` | `true` | `/resolution` selected an object. |
| `@16` | Invalid host | `BLOCKED` | `true` | The host did not resolve. |
| `@20` | Live USGS run 1 | `READY` | `true` | `/type` returned `FeatureCollection`. |
| `@24` | Live USGS run 2 | `READY` | `true` | The result and source digest matched run 1. |

Both live runs returned this source digest:

```text
824ca583d90b6a8e6dec0a4be0db75a917680cfe0bad1474208ba78c666d6600
```

The invalid host produced `BLOCKED` before the corrected USGS source produced `READY` twice.
An official Rote pending-play anchor records this correction in workspace `dag-resolution-proof-93db2e50`.

Release identity:

| Field | Value |
|---|---|
| Play ID | `9b00081c-62fa-49a8-a0a5-9712225d1992` |
| Version ID | `6faeb5c5-ab23-4b12-b7af-0e364ef2af9f` |
| Content hash | `e303537dbe2259e7558fae9357f1a3464b6c45c4633d1751e004c296b9060a26` |
| Package digest | `installed-package-sha256-v1:67adcf450f1d1f5731cde857ea8893c61a2a97f68680d4707ea60d7611265b11` |

Live public data can change after this proof.
The play does not determine whether a source or rule is authoritative.

## Source layout

- `main.ts` defines the Rote play and its presentation output.
- `deps.toml` declares the Python runtime requirement.
- `resources/resolution_proof.py` validates, fetches, evaluates, and verifies results.
- `resources/fixtures/` contains deterministic public judge fixtures.
