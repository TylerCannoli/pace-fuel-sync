# P.A.C.E. Fuel Sync

![Weekly Fuel Price Sync](https://github.com/TylerCannoli/pace-fuel-sync/actions/workflows/fuel_update.yml/badge.svg)

A small, unattended data pipeline that keeps the [P.A.C.E. (Predictive Accessorial Cost Engine)](https://github.com/Spring-ISYS-2026-Alpha-Team/Accessorial_Cost_Detection_Engine) database current with the latest U.S. diesel price — no human in the loop.

Every Monday a GitHub Actions job pulls the weekly National Diesel Average from the U.S. Energy Information Administration (EIA) API and writes it to a Supabase (Postgres) table that the P.A.C.E. risk models read from.

```
 GitHub Actions (cron, Mon 00:00 UTC)
          │
          ▼
  cron_fuel_sync.py ──► EIA v2 API  (weekly diesel, U.S. national)
          │
          ▼
  Supabase / Postgres  ──►  fuel_prices table  ──►  P.A.C.E. models & dashboard
```

## Why it exists

Fuel cost feeds directly into accessorial and freight-cost predictions. Updating it by hand meant stale numbers and silent drift. This job makes the update scheduled, repeatable, and observable: every run is logged in the Actions tab, and failures show up as a red badge instead of quietly bad data.

## Design choices

- **Runs anywhere.** One standalone script — works as a GitHub Action, a cron job on a VM, or locally. No framework, two dependencies.
- **No secrets in code.** All credentials come from environment variables / GitHub Secrets.
- **Fails loudly and specifically.** Missing config is caught before any network call; EIA rate limits (429), bad keys (403), empty responses, and failed inserts each produce their own clear message.
- **Meaningful exit codes** so a scheduler or monitor can tell failure types apart:

  | Code | Meaning |
  |------|---------|
  | `0` | Success |
  | `1` | Runtime failure (network, rate limit, no data, insert failed) |
  | `2` | Configuration error (missing environment variables) |

- **Bounded runtime.** Request timeout of 15 s and a 5-minute job timeout, so a hung API can't stall the runner.

## Setup

1. Get a free EIA API key at <https://www.eia.gov/opendata/>.
2. Create a `fuel_prices` table in Supabase with at least a `price_per_gal` (numeric) column.
3. Add these repository secrets (**Settings → Secrets and variables → Actions**):

   | Secret | Value |
   |--------|-------|
   | `SUPABASE_URL` | `https://<project>.supabase.co` |
   | `SUPABASE_KEY` | Service-role key (server-side only) |
   | `EIA_API_KEY` | Your EIA key |

4. The workflow runs weekly on its own. To trigger it now: **Actions → Weekly Fuel Price Sync → Run workflow**.

### Run locally

```bash
pip install -r requirements.txt
export SUPABASE_URL=... SUPABASE_KEY=... EIA_API_KEY=...
python cron_fuel_sync.py
```

Example output:

```
[START] P.A.C.E Fuel Sync — 2026-03-16 00:00 UTC
[EIA]  Latest diesel price: $3.847/gal  (period: 2026-03-09)
[OK] Inserted fuel_prices row #42 — $3.847/gal  (EIA week of 2026-03-09)
[DONE] Fuel sync complete.
```

## Next steps

- Store the EIA reporting period alongside the price and upsert on it, so a re-run in the same week can't create a duplicate row.
- Add retries with backoff for transient network errors.
- Add a small test suite with a mocked EIA response, run on every push.

## Files

| File | Purpose |
|------|---------|
| `cron_fuel_sync.py` | Fetch → validate → insert |
| `.github/workflows/fuel_update.yml` | Weekly schedule + manual trigger |
| `requirements.txt` | `supabase`, `requests` |
