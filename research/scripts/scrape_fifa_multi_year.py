"""Scrape national-team Overall ratings from fifaindex.com for multiple FIFA editions,
join with World Cup participation + finish stage, and write
research/site/data/fifa_multi_year.json.

fifaindex.com is fronted by Cloudflare; we use curl_cffi with chrome impersonation
to bypass. Polite >=1s delay between requests.
"""
from __future__ import annotations

import json
import time
import unicodedata
from datetime import date
from pathlib import Path

from bs4 import BeautifulSoup
from curl_cffi import requests

OUT_PATH = Path(__file__).resolve().parents[1] / "site" / "data" / "fifa_multi_year.json"

# WC year -> (edition slug for fifaindex URL, pretty edition label)
WC_TO_EDITION = {
    2006: ("fifa07", "FIFA 07"),
    2010: ("fifa11", "FIFA 11"),
    2014: ("fifa15", "FIFA 15"),
    2018: ("fifa19", "FIFA 19"),
    2022: ("fifa23", "FIFA 23"),
}

STAGE_LABELS = {1: "Group", 4: "R16", 5: "QF", 6: "Semi", 7: "Final", 8: "Winner"}


def norm(name: str) -> str:
    """Canonical key for matching fifaindex names to WC participant names."""
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    # strip annotations like "(National team)"
    s = s.split("(")[0].strip()
    # common aliases
    aliases = {
        "republic of ireland": "ireland",
        "ivory coast": "cote d'ivoire",
        "korea republic": "south korea",
        "korea dpr": "north korea",
        "czechia": "czech republic",
        "united states": "usa",
        "iran ir": "iran",
        "trinidad & tobago": "trinidad and tobago",
        "bosnia & herzegovina": "bosnia and herzegovina",
    }
    return aliases.get(s, s)


# --- World Cup participants + finishing stage (Wikipedia/FIFA official) ---
# Stage int: 1=Group, 4=R16, 5=QF, 6=Semi, 7=Final, 8=Winner
WC_RESULTS: dict[int, dict[str, int]] = {
    2006: {
        # Winner: Italy. Runner-up: France. 3rd: Germany. 4th: Portugal.
        "Italy": 8, "France": 7, "Germany": 6, "Portugal": 6,
        "Brazil": 5, "Argentina": 5, "England": 5, "Ukraine": 5,
        "Australia": 4, "Switzerland": 4, "Sweden": 4, "Ecuador": 4,
        "Ghana": 4, "Mexico": 4, "Netherlands": 4, "Spain": 4,
        # Group stage
        "Poland": 1, "Costa Rica": 1, "Croatia": 1, "Tunisia": 1,
        "Saudi Arabia": 1, "USA": 1, "Czech Republic": 1, "Iran": 1,
        "Angola": 1, "Paraguay": 1, "Trinidad and Tobago": 1, "Serbia and Montenegro": 1,
        "Ivory Coast": 1, "Togo": 1, "Japan": 1, "South Korea": 1,
    },
    2010: {
        # Winner: Spain. RU: Netherlands. 3rd: Germany. 4th: Uruguay.
        "Spain": 8, "Netherlands": 7, "Germany": 6, "Uruguay": 6,
        "Argentina": 5, "Brazil": 5, "Ghana": 5, "Paraguay": 5,
        "Chile": 4, "England": 4, "Japan": 4, "Mexico": 4,
        "Portugal": 4, "Slovakia": 4, "South Korea": 4, "USA": 4,
        "Algeria": 1, "Australia": 1, "Cameroon": 1, "Denmark": 1,
        "France": 1, "Greece": 1, "Honduras": 1, "Italy": 1,
        "Ivory Coast": 1, "New Zealand": 1, "Nigeria": 1, "North Korea": 1,
        "Serbia": 1, "Slovenia": 1, "South Africa": 1, "Switzerland": 1,
    },
    2014: {
        # Winner: Germany. RU: Argentina. 3rd: Netherlands. 4th: Brazil.
        "Germany": 8, "Argentina": 7, "Netherlands": 6, "Brazil": 6,
        "Colombia": 5, "Belgium": 5, "France": 5, "Costa Rica": 5,
        "Algeria": 4, "Chile": 4, "Greece": 4, "Mexico": 4,
        "Nigeria": 4, "Switzerland": 4, "USA": 4, "Uruguay": 4,
        "Australia": 1, "Bosnia and Herzegovina": 1, "Cameroon": 1, "Croatia": 1,
        "Ecuador": 1, "England": 1, "Ghana": 1, "Honduras": 1,
        "Iran": 1, "Italy": 1, "Ivory Coast": 1, "Japan": 1,
        "Portugal": 1, "Russia": 1, "South Korea": 1, "Spain": 1,
    },
    2018: {
        # Winner: France. RU: Croatia. 3rd: Belgium. 4th: England.
        "France": 8, "Croatia": 7, "Belgium": 6, "England": 6,
        "Uruguay": 5, "Brazil": 5, "Sweden": 5, "Russia": 5,
        "Argentina": 4, "Portugal": 4, "Mexico": 4, "Denmark": 4,
        "Spain": 4, "Switzerland": 4, "Colombia": 4, "Japan": 4,
        "Australia": 1, "Costa Rica": 1, "Egypt": 1, "Germany": 1,
        "Iceland": 1, "Iran": 1, "Morocco": 1, "Nigeria": 1,
        "Panama": 1, "Peru": 1, "Poland": 1, "Saudi Arabia": 1,
        "Senegal": 1, "Serbia": 1, "South Korea": 1, "Tunisia": 1,
    },
    2022: {
        # Winner: Argentina. RU: France. 3rd: Croatia. 4th: Morocco.
        "Argentina": 8, "France": 7, "Croatia": 6, "Morocco": 6,
        "Netherlands": 5, "Brazil": 5, "England": 5, "Portugal": 5,
        "Australia": 4, "Japan": 4, "Senegal": 4, "Poland": 4,
        "Spain": 4, "Switzerland": 4, "USA": 4, "South Korea": 4,
        "Belgium": 1, "Cameroon": 1, "Canada": 1, "Costa Rica": 1,
        "Denmark": 1, "Ecuador": 1, "Germany": 1, "Ghana": 1,
        "Iran": 1, "Mexico": 1, "Qatar": 1, "Saudi Arabia": 1,
        "Serbia": 1, "Tunisia": 1, "Uruguay": 1, "Wales": 1,
    },
}


def fetch_edition(slug: str, sleep_s: float = 1.2) -> dict[str, int]:
    """Return {normalized_team_name: overall} for a fifaindex edition national-teams listing.

    Paginates until the page repeats (the site clamps overflow to the last page).
    """
    seen_pages: set[str] = set()
    teams: dict[str, int] = {}
    page = 1
    while True:
        url = (
            f"https://www.fifaindex.com/teams/{slug}/?type=1"
            if page == 1
            else f"https://www.fifaindex.com/teams/{slug}/{page}/?type=1"
        )
        print(f"  GET {url}")
        r = requests.get(url, impersonate="chrome", timeout=30)
        if r.status_code != 200:
            print(f"    -> HTTP {r.status_code}, stopping")
            break
        soup = BeautifulSoup(r.text, "html.parser")
        table = soup.find("table")
        if not table:
            break
        rows = table.find_all("tr")[1:]
        if not rows:
            break
        # Build a signature of teams on this page; if we've seen it, we're past the end.
        names = [tr.find_all("td")[0].get_text(strip=True) for tr in rows]
        sig = "|".join(names)
        if sig in seen_pages:
            break
        seen_pages.add(sig)
        new_count = 0
        for tr in rows:
            cells = tr.find_all("td")
            if len(cells) < 3:
                continue
            name = cells[0].get_text(strip=True)
            try:
                ovr = int(cells[2].get_text(strip=True))
            except ValueError:
                continue
            key = norm(name)
            if key not in teams:
                teams[key] = ovr
                new_count += 1
        print(f"    page {page}: +{new_count} new (total {len(teams)})")
        if new_count == 0:
            break
        page += 1
        time.sleep(sleep_s)
    return teams


def main() -> None:
    rows: list[dict] = []
    coverage: dict[int, dict] = {}
    for wc_year, (slug, label) in WC_TO_EDITION.items():
        print(f"\n=== WC {wc_year} via {label} ({slug}) ===")
        ratings = fetch_edition(slug)
        participants = WC_RESULTS[wc_year]
        matched = 0
        missing: list[str] = []
        for team, stage_int in participants.items():
            ovr = ratings.get(norm(team))
            if ovr is None:
                missing.append(team)
                continue
            rows.append({
                "team": team,
                "year": wc_year,
                "fifa_edition": label,
                "overall": ovr,
                "stage_int": stage_int,
                "stage_label": STAGE_LABELS[stage_int],
            })
            matched += 1
        coverage[wc_year] = {
            "edition": label,
            "fifaindex_teams_scraped": len(ratings),
            "wc_participants": len(participants),
            "matched": matched,
            "missing": missing,
        }
        print(f"  -> matched {matched}/{len(participants)} participants; missing: {missing}")
        time.sleep(1.5)

    out = {
        "_meta": {
            "source": "fifaindex.com national teams (game-edition Overall closest to each WC kickoff)",
            "scraped_at": date.today().isoformat(),
            "years_covered": sorted(WC_TO_EDITION.keys()),
            "notes": (
                "Per-WC: used the FIFA-game edition that shipped immediately before the "
                "tournament (FIFA 23 for WC22, FIFA 19 for WC18, FIFA 15 for WC14, "
                "FIFA 11 for WC10, FIFA 07 for WC06). Stage encoding: 1=Group, 4=R16, "
                "5=QF, 6=Semi, 7=Final, 8=Winner. fifaindex's national-teams listing "
                "only includes a subset of FIFA federations per edition, so some WC "
                "participants (often AFC/CAF/CONMEBOL minnows) have no rating and are "
                "omitted rather than imputed."
            ),
            "coverage_by_year": coverage,
        },
        "rows": rows,
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(out, indent=2))
    print(f"\nWrote {len(rows)} rows -> {OUT_PATH}")


if __name__ == "__main__":
    main()
