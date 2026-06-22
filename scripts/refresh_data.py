#!/usr/bin/env python3
"""
Fetches deal data from HubSpot and updates docs/data/kpi-data.json.
Requires: HUBSPOT_TOKEN environment variable (private app token).
"""

import os
import json
import urllib.request
import urllib.parse
from datetime import datetime, timezone, timedelta

HUBSPOT_TOKEN = os.environ["HUBSPOT_TOKEN"]
OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "..", "docs", "data", "kpi-data.json")

HEADERS = {
    "Authorization": f"Bearer {HUBSPOT_TOKEN}",
    "Content-Type": "application/json",
}

DAYS_BACK = 90  # fetch 90 days so all period windows (7/14/30) are covered


def hs_post(url, payload):
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, headers=HEADERS, method="POST")
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def fetch_all_deals():
    """Paginate through all deals created in the last DAYS_BACK days."""
    since_ts = int((datetime.now(timezone.utc) - timedelta(days=DAYS_BACK)).timestamp() * 1000)
    url = "https://api.hubapi.com/crm/v3/objects/deals/search"
    deals = []
    after = None

    while True:
        payload = {
            "filterGroups": [{
                "filters": [{
                    "propertyName": "createdate",
                    "operator": "GTE",
                    "value": str(since_ts),
                }]
            }],
            "properties": ["dealname", "dealstage", "createdate", "closedate", "hs_lastmodifieddate"],
            "limit": 100,
        }
        if after:
            payload["after"] = after

        result = hs_post(url, payload)
        deals.extend(result.get("results", []))
        print(f"  Fetched {len(deals)} deals so far...")

        paging = result.get("paging", {})
        after = paging.get("next", {}).get("after")
        if not after:
            break

    return deals


def classify(deal):
    name = (deal.get("properties", {}).get("dealname") or "").lower()
    if "rundot" in name:
        return "rundot"
    if "tridot" in name:
        return "tridot"
    return None


def compute_kpis(deals, days_back):
    since = datetime.now(timezone.utc) - timedelta(days=days_back)
    since_ts = since.timestamp() * 1000

    tridot = {"signups": 0, "paid": 0, "cancelled": 0}
    rundot = {"signups": 0, "paid": 0, "cancelled": 0}

    for deal in deals:
        props = deal.get("properties", {})
        created_ts = float(props.get("createdate") or 0)
        if created_ts < since_ts:
            continue

        app = classify(deal)
        if not app:
            continue

        bucket = tridot if app == "tridot" else rundot
        stage = props.get("dealstage", "")

        bucket["signups"] += 1
        if stage == "decisionmakerboughtin":
            bucket["paid"] += 1
        elif stage == "closedlost":
            bucket["cancelled"] += 1

    return tridot, rundot


def main():
    print(f"Fetching deals from the last {DAYS_BACK} days...")
    deals = fetch_all_deals()
    print(f"Total deals fetched: {len(deals)}")

    now = datetime.now(timezone.utc)
    oldest = min(
        (float(d["properties"].get("createdate") or 0) for d in deals),
        default=0,
    )
    data_from = datetime.fromtimestamp(oldest / 1000, tz=timezone.utc).strftime("%Y-%m-%d") if oldest else "N/A"
    data_through = now.strftime("%Y-%m-%d")

    actual_days = (now - datetime.fromtimestamp(oldest / 1000, tz=timezone.utc)).days if oldest else 0

    periods = {}
    for days in [7, 14, 30]:
        td, rd = compute_kpis(deals, days)
        periods[str(days)] = {
            "tridot": td,
            "rundot": rd,
            "deal_count": sum(td.values()) // 3 + sum(rd.values()) // 3,
            "hasFullData": actual_days >= days,
            "daysBack": actual_days,
        }

    output = {
        "periods": periods,
        "fetchedAt": now.isoformat(),
        "dataFrom": data_from,
        "dataThrough": data_through,
        "totalDealsInCache": len(deals),
    }

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(output, f, indent=2)

    print(f"Saved KPI data to {OUTPUT_PATH}")
    for days, p in output["periods"].items():
        print(f"  {days}d → TriDot: {p['tridot']} | RunDot: {p['rundot']}")


if __name__ == "__main__":
    main()
