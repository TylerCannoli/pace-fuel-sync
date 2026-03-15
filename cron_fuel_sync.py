"""
cron_fuel_sync.py
-----------------
Standalone script — safe to run as a cron job, GitHub Action, or locally.

Fetches the latest National Diesel Average from the EIA v2 API and inserts
the result into the Supabase `fuel_prices` table.

Configuration (all via environment variables — never hard-coded):
    SUPABASE_URL   — e.g. https://<project>.supabase.co
    SUPABASE_KEY   — service-role key (bypasses RLS)
    EIA_API_KEY    — free key from https://www.eia.gov/opendata/

Exit codes:
    0  — success
    1  — recoverable / expected failure (rate-limit, no data)
    2  — configuration error (missing env vars)
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone

import requests
from supabase import create_client


# ── Configuration ─────────────────────────────────────────────────────────────

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").strip()
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "").strip()
EIA_API_KEY  = os.environ.get("EIA_API_KEY", "").strip()

# EIA v2 endpoint — weekly US national retail diesel (EPD2D / NUS)
EIA_URL = (
    "https://api.eia.gov/v2/petroleum/pri/gnd/data/"
    "?api_key={key}"
    "&frequency=weekly"
    "&data[0]=value"
    "&facets[product][]=EPD2D"
    "&facets[duoarea][]=NUS"
    "&sort[0][column]=period"
    "&sort[0][direction]=desc"
    "&offset=0&length=1"
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _check_env() -> None:
    """Abort early with a clear message if any required variable is missing."""
    missing = [
        name for name, val in [
            ("SUPABASE_URL", SUPABASE_URL),
            ("SUPABASE_KEY", SUPABASE_KEY),
            ("EIA_API_KEY",  EIA_API_KEY),
        ]
        if not val
    ]
    if missing:
        print(
            f"[ERROR] Missing required environment variable(s): {', '.join(missing)}\n"
            "Set them as GitHub Secrets (or export them locally) before running.",
            file=sys.stderr,
        )
        sys.exit(2)


def fetch_diesel_price(api_key: str) -> tuple[float, str]:
    """
    Fetch the most recent weekly National Diesel Average from EIA.

    Returns
    -------
    (price_per_gal, period)   e.g.  (3.847, "2025-03-10")
    """
    url  = EIA_URL.format(key=api_key)
    resp = requests.get(url, timeout=15)

    if resp.status_code == 429:
        raise RuntimeError(
            "EIA rate limit reached (429). "
            "Wait before retrying or upgrade to a production API key."
        )
    if resp.status_code == 403:
        raise RuntimeError(
            "EIA API key rejected (403). "
            "Verify EIA_API_KEY is correct at https://www.eia.gov/opendata/"
        )

    resp.raise_for_status()

    data = resp.json()
    rows = data.get("response", {}).get("data", [])

    if not rows:
        raise RuntimeError(
            "EIA returned an empty data set. "
            "The series may have changed — check the EIA v2 API docs."
        )

    price  = float(rows[0]["value"])
    period = str(rows[0]["period"])
    return price, period


def insert_fuel_price(price: float, period: str) -> None:
    """Insert one row into fuel_prices using the service-role key."""
    sb = create_client(SUPABASE_URL, SUPABASE_KEY)

    res = (
        sb.table("fuel_prices")
        .insert({"price_per_gal": price})
        .execute()
    )

    if not res.data:
        raise RuntimeError(
            "Supabase insert returned no data. "
            "Check table permissions and that the service-role key is correct."
        )

    row_id = res.data[0].get("id", "?")
    print(
        f"[OK] Inserted fuel_prices row #{row_id} — "
        f"${price:.3f}/gal  (EIA week of {period})"
    )


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    print(f"[START] P.A.C.E Fuel Sync — {now}")

    _check_env()

    # 1. Fetch from EIA
    try:
        price, period = fetch_diesel_price(EIA_API_KEY)
        print(f"[EIA]  Latest diesel price: ${price:.3f}/gal  (period: {period})")
    except RuntimeError as exc:
        print(f"[WARN] {exc}", file=sys.stderr)
        sys.exit(1)
    except requests.RequestException as exc:
        print(f"[ERROR] Network error contacting EIA: {exc}", file=sys.stderr)
        sys.exit(1)

    # 2. Write to Supabase
    try:
        insert_fuel_price(price, period)
    except RuntimeError as exc:
        print(f"[ERROR] Supabase insert failed: {exc}", file=sys.stderr)
        sys.exit(1)
    except Exception as exc:
        print(f"[ERROR] Unexpected error: {exc}", file=sys.stderr)
        sys.exit(1)

    print("[DONE] Fuel sync complete.")


if __name__ == "__main__":
    main()
