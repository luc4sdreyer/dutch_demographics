# Dutch municipal crime map

A reliable, comparable crime measure across Dutch municipalities, with an
interactive choropleth to explore it.

**🗺️ Live map: https://luc4sdreyer.github.io/dutch_demographics/**

## Why these offences

Homicide is the usual "reliable because near-completely recorded" benchmark, but
it is too rare to be stable at municipal level. Instead this project uses
**insurance-driven, high-reporting property crime** as a proxy — reporting rates
are high (insurers require a police report), so recording bias is low, and volume
is high enough to be stable:

- **Primary:** residential burglary — *Diefstal/inbraak woning* (`1.1.1`)
- **Secondary:** motor-vehicle theft — *Diefstal van motorvoertuigen* (`1.2.2`)

Offences are grouped by a **reliability tier** so the measure's trustworthiness
is explicit in the UI:

| Tier | Offences | Rationale |
|---|---|---|
| **High** | dwelling / shed / business burglary, motor-vehicle theft | Insurance/registration-driven, ~90% reported (verified against CBS Veiligheidsmonitor): low recording bias, stable volume |
| **Moderate** | bike & moped theft, theft-from-vehicle, assault, threat, vandalism | Usable volume, but a large share goes unreported (bike theft ~15%, vandalism ~18%, assault ~50%), so levels are less comparable between places |
| **Enforcement-driven** | drug offences, weapons | Track police activity, not underlying crime — shown as a deliberate contrast |
| **Registered, incl. attempts — not the homicide rate** | murder & manslaughter | Counts registered offences (~2,500/yr), dominated by *attempts* — roughly **20× actual homicides** (~125 deaths/yr, ~0.7/100k, matching UNODC). Do not read as the homicide rate. Also too sparse for annual municipal comparison. Included only with a strong caveat |

**Deliberately excluded:** street robbery, robbery and sexual offences (too rare
*and* poorly reported), and fraud/cybercrime (location assigned too fuzzily to be
spatially meaningful).

## Data sources (CBS OData)

| Table | Host | Use |
|---|---|---|
| **47018NED** | `dataderden.cbs.nl` | Police registered crime, detailed offence hierarchy, municipal, 2012–present (absolute counts) |
| **70072ned** | `opendata.cbs.nl` | Average population per municipality/year (rate denominator) |

> **Note:** the headline StatLine table `83648NED` uses a coarse post-2022
> taxonomy with **no** dwelling-burglary breakdown, so it cannot serve this
> project. `47018NED` is the only current table with the needed granularity.

Boundaries: CBS municipal boundaries (2024) via
[cartomap](https://cartomap.github.io/nl/) as WGS84 GeoJSON.

2023 is the most recent definitive year; **2024 and 2025 are provisional**.

## Scripts (Python, only dependency: `requests`)

```bash
python3 cbs_burglary.py [municipality]      # one municipality: burglary + vehicle
                                            #   theft time series (default Utrecht)
python3 cbs_ranking.py  [offence] [--min-pop N]   # national ranking -> CSV
python3 build_data.py                       # build web/data.json for the map
```

`cbs_ranking.py` averages the most recent 3 definitive years (2021–2023) to
suppress provisional-year noise; `--min-pop 10000` drops tiny, statistically
fragile municipalities.

## Web map (`web/`)

Self-contained static site — no backend. All views are computed client-side
from `web/data.json`. Filters:

1. **Year** — pick a single year
2. **Average** — mean over a year range
3. **Delta** — change between two years (diverging colour scale)
4. **Measure** — absolute count vs. per 100,000 inhabitants

Run locally (a server is required — the page uses `fetch`):

```bash
cd web && python3 -m http.server 8000
# open http://localhost:8000
```

Deployable as-is to GitHub Pages (serve the `web/` directory).

To refresh the data, re-run `python3 build_data.py` and redeploy.

### Caveats

- Small municipalities are noisy even over multi-year windows; prefer a
  population floor for rankings.
- Deltas across municipal reorganisations mix boundary changes with real change.
