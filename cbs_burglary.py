#!/usr/bin/env python3
"""Reliable per-municipality crime measure for the Netherlands.

Primary indicator:   residential burglary  (1.1.1 Diefstal/inbraak woning)
Secondary indicator: motor-vehicle theft   (1.2.2 Diefstal van motorvoertuigen)

Both are insurance-driven, high-reporting offences, so recording bias is low
(they behave like homicide on reliability, but with usable municipal volume).
Police-initiated categories (drugs, weapons, public order) are deliberately
excluded as headline measures because they track enforcement, not crime.

DATA SOURCE
-----------
CBS 'data derden' (police) table 47018NED on dataderden.cbs.nl. This is the
ONLY current CBS table that keeps the detailed offence hierarchy (incl.
"Diefstal/inbraak woning") at municipal level, 2012-present.

NB: the headline StatLine table 83648NED ("Geregistreerde criminaliteit;
soort misdrijf, regio", opendata.cbs.nl) uses the post-2022 coarse taxonomy
whose finest theft class is "Diefstal en inbraak zonder geweld" -- it has NO
dwelling-burglary breakdown, so it cannot serve this project.

Counts in 47018NED are absolute only (no built-in rate), so we normalize to a
per-100,000-inhabitants rate using average population (GemiddeldAantalInwoners)
from CBS regional core-figures table 70072ned.

Codes are discovered by name-matching, never hardcoded, so the script is
robust to CBS code changes.

Only dependency: requests.

Usage:
    python3 cbs_burglary.py [municipality]     # default: Utrecht
"""

import sys
import requests

DERDEN = "https://dataderden.cbs.nl/ODataApi/OData/47018NED"   # police crime, detailed
OPEN = "https://opendata.cbs.nl/ODataApi/OData/70072ned"       # regional core figures
N_YEARS = 5

# Offence names we look for (substring match against SoortMisdrijf titles).
OFFENCES = {
    "Residential burglary": "diefstal/inbraak woning",
    "Motor-vehicle theft": "diefstal van motorvoertuigen",
}


def odata(base, resource, params=None):
    """GET a CBS OData v3 resource and return its 'value' list."""
    params = dict(params or {})
    params.setdefault("$format", "json")
    r = requests.get(f"{base}/{resource}", params=params, timeout=60)
    r.raise_for_status()
    return r.json()["value"]


def resolve_region(name):
    """Resolve a municipality name to its padded GMxxxx key in 47018NED."""
    regions = odata(DERDEN, "WijkenEnBuurten")
    gm = [r for r in regions if r["Key"].strip().startswith("GM")]
    want = name.strip().lower()
    exact = [r for r in gm if r["Title"].strip().lower() == want]
    partial = [r for r in gm if want in r["Title"].strip().lower()]
    hits = exact or partial
    if not hits:
        sys.exit(f"No municipality matched {name!r}.")
    if len(hits) > 1:
        print(f"Ambiguous municipality {name!r}; matches:")
        for r in hits:
            print(f"  {r['Key'].strip()} | {r['Title'].strip()}")
        print(f"Using first: {hits[0]['Title'].strip()}\n")
    return hits[0]["Key"], hits[0]["Title"].strip()


def resolve_offences():
    """Resolve each wanted offence to its exact SoortMisdrijf key."""
    soorten = odata(DERDEN, "SoortMisdrijf")
    resolved = {}
    for label, needle in OFFENCES.items():
        hits = [s for s in soorten if needle in s["Title"].strip().lower()]
        if not hits:
            print(f"WARNING: no offence code matched {needle!r}; skipping.")
            continue
        if len(hits) > 1:
            print(f"Ambiguous offence for {label!r}:")
            for s in hits:
                print(f"  {s['Key'].strip()} | {s['Title'].strip()}")
        resolved[label] = (hits[0]["Key"], hits[0]["Title"].strip())
    return resolved


def recent_periods():
    """Return the last N_YEARS annual period keys (JJ00), oldest first."""
    periods = odata(DERDEN, "Perioden")
    annual = [p["Key"] for p in periods if p["Key"].endswith("JJ00")]
    return annual[-N_YEARS:]


def population_by_year(gm_key):
    """Average population per year for a GM key, from 70072ned. {year: pop}."""
    code = gm_key.strip()
    try:
        rows = odata(OPEN, "TypedDataSet", {
            "$filter": f"startswith(RegioS,'{code}')",
            "$select": "Perioden,GemiddeldAantalInwoners_51,TotaleBevolking_1",
        })
    except requests.HTTPError:
        return {}
    out = {}
    for row in rows:
        # Prefer the year's average population; for the newest (provisional)
        # year the average isn't computed yet, so fall back to 1-Jan total.
        pop = row.get("GemiddeldAantalInwoners_51") or row.get("TotaleBevolking_1")
        if pop:
            out[row["Perioden"][:4]] = pop
    return out


def crime_by_year(gm_key, soort_key, periods):
    """Absolute registered count per year for one region + offence. {year: n}."""
    rows = odata(DERDEN, "TypedDataSet", {
        "$filter": f"WijkenEnBuurten eq '{gm_key}' and SoortMisdrijf eq '{soort_key}'",
        "$select": "Perioden,GeregistreerdeMisdrijven_1",
    })
    wanted = set(periods)
    return {
        r["Perioden"][:4]: r.get("GeregistreerdeMisdrijven_1")
        for r in rows if r["Perioden"] in wanted
    }


PROVISIONAL = {"2024", "2025"}  # not yet definitive at CBS


def main():
    name = sys.argv[1] if len(sys.argv) > 1 else "Utrecht"
    gm_key, gm_name = resolve_region(name)
    offences = resolve_offences()
    periods = recent_periods()
    years = [p[:4] for p in periods]
    pop = population_by_year(gm_key)

    print(f"Municipality: {gm_name} ({gm_key.strip()})")
    print(f"Source: CBS 47018NED (police, detailed offences), "
          f"rate per 100,000 inhabitants via 70072ned")
    print(f"Years: {years[0]}-{years[-1]}  (* = provisional)\n")

    for label, (soort_key, soort_title) in offences.items():
        counts = crime_by_year(gm_key, soort_key, periods)
        print(f"{label}  [{soort_title}]")
        print(f"  {'year':<6}{'count':>8}{'per 100,000 inh.':>18}")
        for y in years:
            n = counts.get(y)
            p = pop.get(y)
            rate = f"{n / p * 1e5:.1f}" if (n is not None and p) else "n/a"
            star = "*" if y in PROVISIONAL else ""
            n_str = "n/a" if n is None else str(n)
            print(f"  {y + star:<6}{n_str:>8}{rate:>18}")
        print()


if __name__ == "__main__":
    main()
