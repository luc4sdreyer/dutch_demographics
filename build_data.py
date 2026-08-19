#!/usr/bin/env python3
"""Build web/data.json for the choropleth: counts + population per
municipality per year, for a curated set of reliable, insurance-driven
offences.

Sources (see cbs_burglary.py for rationale):
  47018NED @ dataderden.cbs.nl  -- police detailed offences, municipal, absolute
  70072ned @ opendata.cbs.nl    -- average population per municipality/year

Output shape (web/data.json):
  {
    "offences":    {"1.1.1": "Diefstal/inbraak woning", ...},
    "years":       [2012, ..., 2025],
    "provisional": [2024, 2025],
    "population":  {"GM0344": {"2012": 345000, ...}, ...},
    "counts":      {"1.1.1": {"GM0344": {"2012": 681, ...}, ...}, ...}
  }

Population is offence-independent, so it is stored once. The web app computes
every view (single year, multi-year average, delta, absolute vs per-1,000)
from these two tables client-side.
"""

import json
import os
import requests

DERDEN = "https://dataderden.cbs.nl/ODataApi/OData/47018NED"
OPEN = "https://opendata.cbs.nl/ODataApi/OData/70072ned"
OUT = os.path.join(os.path.dirname(__file__), "web", "data.json")

# Curated reliable offences (insurance-driven, high reporting), by title
# substring. Order controls the dropdown order in the UI.
OFFENCE_NEEDLES = [
    "diefstal/inbraak woning",            # 1.1.1 primary
    "diefstal van motorvoertuigen",       # 1.2.2 secondary
    "diefstal/inbraak box",               # 1.1.2
    "diefstal uit/vanaf motorvoertuigen",  # 1.2.1
    "diefstal/inbraak bedrijven",         # 2.5.1
]

PROVISIONAL = [2024, 2025]


def odata(base, resource, params=None):
    params = dict(params or {})
    params.setdefault("$format", "json")
    r = requests.get(f"{base}/{resource}", params=params, timeout=120)
    r.raise_for_status()
    return r.json()["value"]


def resolve_offences():
    """Map each needle to its exact SoortMisdrijf key, keeping title."""
    soorten = odata(DERDEN, "SoortMisdrijf")
    out = {}  # key -> (code_label, title)
    for needle in OFFENCE_NEEDLES:
        hits = [s for s in soorten if needle in s["Title"].strip().lower()]
        if not hits:
            print(f"WARNING: no offence matched {needle!r}")
            continue
        s = hits[0]
        code = s["Key"].strip()          # e.g. "1.1.1"
        title = s["Title"].strip()
        # Title already begins with the code; strip it for a clean label.
        label = title[len(code):].strip() if title.startswith(code) else title
        out[s["Key"]] = (code, label)
    return out


def annual_years():
    periods = odata(DERDEN, "Perioden")
    return [int(p["Key"][:4]) for p in periods if p["Key"].endswith("JJ00")]


def or_periods(field, years):
    return "(" + " or ".join(f"{field} eq '{y}JJ00'" for y in years) + ")"


def fetch_counts(soort_keys, years):
    """counts[code][gm][year] = int."""
    counts = {}
    for soort_key in soort_keys:
        rows = odata(DERDEN, "TypedDataSet", {
            "$filter": f"SoortMisdrijf eq '{soort_key}' and "
                       f"startswith(WijkenEnBuurten,'GM') and "
                       f"{or_periods('Perioden', years)}",
            "$select": "WijkenEnBuurten,Perioden,GeregistreerdeMisdrijven_1",
        })
        code = soort_key.strip()
        table = {}
        for r in rows:
            v = r.get("GeregistreerdeMisdrijven_1")
            if v is None:
                continue
            gm = r["WijkenEnBuurten"].strip()
            table.setdefault(gm, {})[r["Perioden"][:4]] = v
        counts[code] = table
        print(f"  {code}: {sum(len(v) for v in table.values())} data points")
    return counts


def fetch_population(years):
    """population[gm][year] = int (average pop, falling back to 1-Jan total).

    70072ned spans 1995-now with every historical municipality, so an
    all-years query trips CBS's 10k-record guard. Page it one year at a time.
    """
    pop = {}
    for y in years:
        rows = odata(OPEN, "TypedDataSet", {
            "$filter": f"startswith(RegioS,'GM') and Perioden eq '{y}JJ00'",
            "$select": "RegioS,Perioden,GemiddeldAantalInwoners_51,TotaleBevolking_1",
        })
        for r in rows:
            v = r.get("GemiddeldAantalInwoners_51") or r.get("TotaleBevolking_1")
            if v is None:
                continue
            pop.setdefault(r["RegioS"].strip(), {})[str(y)] = round(v)
    return pop


def main():
    print("Resolving offences...")
    offences = resolve_offences()
    years = annual_years()
    print(f"Years: {years[0]}-{years[-1]}")

    print("Fetching population...")
    population = fetch_population(years)
    print(f"  {len(population)} municipalities")

    print("Fetching crime counts...")
    counts = fetch_counts(list(offences), years)

    payload = {
        "offences": {code: label for code, label in offences.values()},
        "years": years,
        "provisional": PROVISIONAL,
        "population": population,
        "counts": counts,
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(payload, f, separators=(",", ":"))
    print(f"\nWrote {OUT} ({os.path.getsize(OUT):,} bytes)")


if __name__ == "__main__":
    main()
