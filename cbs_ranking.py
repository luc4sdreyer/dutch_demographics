#!/usr/bin/env python3
"""National municipality ranking on a reliable crime measure.

Ranks all Dutch municipalities by residential burglary (default) or another
insurance-driven offence, as a rate per 1,000 inhabitants, averaged over the
most recent DEFINITIVE 3 years to suppress provisional-year noise.

Rate = (mean absolute count over window) / (mean population over window) * 1000.

Sources (see cbs_burglary.py for the full rationale):
  47018NED @ dataderden.cbs.nl  -- police detailed offences, municipal, absolute
  70072ned @ opendata.cbs.nl    -- average population per municipality/year

Usage:
    python3 cbs_ranking.py [offence-substring] [--min-pop N]
    python3 cbs_ranking.py "diefstal van motorvoertuigen"
    python3 cbs_ranking.py --min-pop 10000        # drop tiny, noisy municipalities
Writes the full sorted table to <offence>_ranking.csv and prints top/bottom 15.
"""

import argparse
import csv
import re
import sys
import requests

DERDEN = "https://dataderden.cbs.nl/ODataApi/OData/47018NED"
OPEN = "https://opendata.cbs.nl/ODataApi/OData/70072ned"

PROVISIONAL = {"2024", "2025"}   # not yet definitive at CBS
WINDOW = 3                       # number of definitive years to average
DEFAULT_OFFENCE = "diefstal/inbraak woning"


def odata(base, resource, params=None):
    params = dict(params or {})
    params.setdefault("$format", "json")
    r = requests.get(f"{base}/{resource}", params=params, timeout=120)
    r.raise_for_status()
    return r.json()["value"]


def resolve_offence(needle):
    soorten = odata(DERDEN, "SoortMisdrijf")
    hits = [s for s in soorten if needle.lower() in s["Title"].strip().lower()]
    if not hits:
        sys.exit(f"No offence matched {needle!r}.")
    if len(hits) > 1:
        print(f"Ambiguous offence {needle!r}:")
        for s in hits:
            print(f"  {s['Key'].strip()} | {s['Title'].strip()}")
        print(f"Using first: {hits[0]['Title'].strip()}\n")
    return hits[0]["Key"], hits[0]["Title"].strip()


def definitive_years():
    periods = odata(DERDEN, "Perioden")
    annual = [p["Key"][:4] for p in periods if p["Key"].endswith("JJ00")]
    definitive = [y for y in annual if y not in PROVISIONAL]
    return definitive[-WINDOW:]


def region_names():
    regs = odata(DERDEN, "WijkenEnBuurten", {"$select": "Key,Title"})
    return {r["Key"].strip(): r["Title"].strip()
            for r in regs if r["Key"].strip().startswith("GM")}


def or_periods(field, years):
    return "(" + " or ".join(f"{field} eq '{y}JJ00'" for y in years) + ")"


def counts_by_gm(soort_key, years):
    """{gm_code: [count per year]} for one offence across the window."""
    rows = odata(DERDEN, "TypedDataSet", {
        "$filter": f"SoortMisdrijf eq '{soort_key}' and "
                   f"startswith(WijkenEnBuurten,'GM') and {or_periods('Perioden', years)}",
        "$select": "WijkenEnBuurten,Perioden,GeregistreerdeMisdrijven_1",
    })
    out = {}
    for r in rows:
        gm = r["WijkenEnBuurten"].strip()
        out.setdefault(gm, {})[r["Perioden"][:4]] = r.get("GeregistreerdeMisdrijven_1")
    return out


def pop_by_gm(years):
    rows = odata(OPEN, "TypedDataSet", {
        "$filter": f"startswith(RegioS,'GM') and {or_periods('Perioden', years)}",
        "$select": "RegioS,Perioden,GemiddeldAantalInwoners_51,TotaleBevolking_1",
    })
    out = {}
    for r in rows:
        gm = r["RegioS"].strip()
        pop = r.get("GemiddeldAantalInwoners_51") or r.get("TotaleBevolking_1")
        if pop:
            out.setdefault(gm, {})[r["Perioden"][:4]] = pop
    return out


def mean(vals):
    vals = [v for v in vals if v is not None]
    return sum(vals) / len(vals) if vals else None


def main():
    ap = argparse.ArgumentParser(description="Rank Dutch municipalities on a crime rate.")
    ap.add_argument("offence", nargs="?", default=DEFAULT_OFFENCE,
                    help="offence-title substring (default: dwelling burglary)")
    ap.add_argument("--min-pop", type=int, default=0, metavar="N",
                    help="exclude municipalities below N mean inhabitants "
                         "(e.g. 10000 to drop tiny, noisy ones)")
    args = ap.parse_args()

    soort_key, soort_title = resolve_offence(args.offence)
    years = definitive_years()
    names = region_names()
    counts = counts_by_gm(soort_key, years)
    pops = pop_by_gm(years)

    rows = []
    excluded = 0
    for gm, name in names.items():
        c = mean([counts.get(gm, {}).get(y) for y in years])
        p = mean([pops.get(gm, {}).get(y) for y in years])
        if c is None or not p:
            continue
        if p < args.min_pop:
            excluded += 1
            continue
        rows.append({
            "gm": gm, "municipality": name,
            "mean_count": round(c, 1), "mean_pop": round(p),
            "rate_per_1000": round(c / p * 1000, 3),
        })
    rows.sort(key=lambda r: r["rate_per_1000"], reverse=True)
    for i, r in enumerate(rows, 1):
        r["rank"] = i

    slug = re.sub(r"[^a-z0-9]+", "_", soort_title.lower()).strip("_")
    suffix = f"_minpop{args.min_pop}" if args.min_pop else ""
    fn = f"{slug}_ranking{suffix}.csv"
    with open(fn, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["rank", "gm", "municipality",
                                          "mean_count", "mean_pop", "rate_per_1000"])
        w.writeheader()
        w.writerows(rows)

    print(f"Offence: {soort_title}  ({soort_key.strip()})")
    print(f"Measure: rate per 1,000 inhabitants, mean of {years[0]}-{years[-1]} "
          f"(definitive years)")
    floor_note = (f"; excluded {excluded} below {args.min_pop:,} inhabitants"
                  if args.min_pop else "")
    print(f"Ranked {len(rows)} municipalities{floor_note} -> {fn}\n")

    def show(title, sub):
        print(title)
        print(f"  {'#':>3}  {'municipality':<24}{'rate/1000':>10}{'mean/yr':>9}")
        for r in sub:
            print(f"  {r['rank']:>3}  {r['municipality']:<24}"
                  f"{r['rate_per_1000']:>10.2f}{r['mean_count']:>9.0f}")
        print()

    show(f"TOP 15 (highest burglary rate):", rows[:15])
    show(f"BOTTOM 15 (lowest):", rows[-15:])


if __name__ == "__main__":
    main()
