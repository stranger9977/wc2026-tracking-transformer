"""Build a cross-World-Cup "History Index" from Wikipedia squad pages.

Question this answers: does *shared club history* correlate with how far a team
goes at a World Cup? (No tracking data — purely squad composition vs finish.)

History Index (per squad), computed identically for every WC:
    history_share = share of squad players whose tournament-time club also has
                    >=1 teammate in the same national squad.
    history_count = raw count of those players.
    largest_bloc  = size of the biggest single-club group of teammates
                    (e.g. Germany 2014 had 7 Bayern players).

Source: en.wikipedia.org "<year> FIFA World Cup squads" pages, which list every
player with the club they were at during the tournament. Club strings are only
ever compared *within a single squad*, so cross-year club spelling drift does not
matter.

Finishes (stage reached) come from the existing fifa_multi_year.json (the same
FIFA-rated team set the FIFA-Overall-vs-finish scatter already plots). History
index is computed for all 32 participants per year and written out; the finish is
attached where we have it (else null), so the front-end plots the same dot set as
the sibling chart.

Output: research/site/data/history_index_multi_year.json
"""
from __future__ import annotations

import json
import re
import sys
import time
import urllib.parse
import urllib.request
from collections import Counter
from io import StringIO
from pathlib import Path

import pandas as pd
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[2]
FIFA_MULTI = ROOT / "research" / "site" / "data" / "fifa_multi_year.json"
OUT = ROOT / "research" / "site" / "data" / "history_index_multi_year.json"

YEARS = [2006, 2010, 2014, 2018, 2022]
UA = "wc2026-tracking-transformer research scraper (contact: nickgurol@gmail.com)"

# Wikipedia squad-page heading -> fifa_multi_year.json team vocabulary.
TEAM_ALIASES = {
    "United States": "USA",
    "Korea Republic": "South Korea",
    "IR Iran": "Iran",
    "China PR": "China",
}

STAGE_LABEL = {2: "Group", 4: "R16", 5: "QF", 6: "Semi", 7: "Final", 8: "Winner"}

# Complete knockout results per WC (R16 onward). Every participant not listed here
# exited at the group stage (stage_int=2). Stage of a team = the round in which it
# was eliminated: 4=lost R16, 5=lost QF, 6=lost semi, 7=runner-up, 8=winner.
# Validated against fifa_multi_year.json finishes where the two overlap (see main()).
KNOCKOUT = {
    2006: {
        "Italy": 8, "France": 7,
        "Germany": 6, "Portugal": 6,
        "Argentina": 5, "Ukraine": 5, "England": 5, "Brazil": 5,
        "Sweden": 4, "Mexico": 4, "Ecuador": 4, "Netherlands": 4,
        "Australia": 4, "Switzerland": 4, "Ghana": 4, "Spain": 4,
    },
    2010: {
        "Spain": 8, "Netherlands": 7,
        "Germany": 6, "Uruguay": 6,
        "Argentina": 5, "Paraguay": 5, "Ghana": 5, "Brazil": 5,
        "South Korea": 4, "USA": 4, "England": 4, "Mexico": 4,
        "Slovakia": 4, "Chile": 4, "Japan": 4, "Portugal": 4,
    },
    2014: {
        "Germany": 8, "Argentina": 7,
        "Netherlands": 6, "Brazil": 6,
        "France": 5, "Belgium": 5, "Costa Rica": 5, "Colombia": 5,
        "Chile": 4, "Uruguay": 4, "Mexico": 4, "Greece": 4,
        "Nigeria": 4, "Algeria": 4, "Switzerland": 4, "USA": 4,
    },
    2018: {
        "France": 8, "Croatia": 7,
        "Belgium": 6, "England": 6,
        "Uruguay": 5, "Brazil": 5, "Russia": 5, "Sweden": 5,
        "Argentina": 4, "Portugal": 4, "Mexico": 4, "Japan": 4,
        "Denmark": 4, "Spain": 4, "Switzerland": 4, "Colombia": 4,
    },
    2022: {
        "Argentina": 8, "France": 7,
        "Croatia": 6, "Morocco": 6,
        "Netherlands": 5, "Portugal": 5, "England": 5, "Brazil": 5,
        "USA": 4, "Australia": 4, "Poland": 4, "Senegal": 4,
        "Japan": 4, "South Korea": 4, "Spain": 4, "Switzerland": 4,
    },
}


def fetch_squad_html(year: int) -> str:
    page = f"{year}_FIFA_World_Cup_squads"
    api = (
        "https://en.wikipedia.org/w/api.php?action=parse&format=json"
        "&formatversion=2&prop=text&page=" + urllib.parse.quote(page)
    )
    req = urllib.request.Request(api, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data["parse"]["text"]


def heading_text(el) -> str:
    # Modern WP wraps <h3 id="Germany">Germany</h3> inside .mw-heading.
    txt = el.get_text(" ", strip=True)
    # Strip trailing "[edit]" artifacts (shouldn't appear via API, but be safe).
    return re.sub(r"\[\s*edit\s*\]", "", txt).strip()


def is_squad_table(table) -> tuple[bool, int | None]:
    """A squad table has a header with Player + Club and ~23-26 player rows.
    Returns (is_squad, club_col_index)."""
    head = table.find("tr")
    if head is None:
        return False, None
    headers = [th.get_text(" ", strip=True).lower() for th in head.find_all(["th", "td"])]
    if not any("player" in h for h in headers) or not any("club" == h or h.startswith("club") for h in headers):
        return False, None
    club_idx = next((i for i, h in enumerate(headers) if h == "club" or h.startswith("club")), None)
    body_rows = [tr for tr in table.find_all("tr")[1:] if tr.find_all(["td"])]
    if not (18 <= len(body_rows) <= 30):
        return False, None
    return True, club_idx


def parse_squad_clubs(table) -> list[str]:
    """Return the club string for each player row in this squad table."""
    df = pd.read_html(StringIO(str(table)))[0]
    # Flatten any multiindex columns.
    df.columns = [
        " ".join(str(c) for c in col).strip() if isinstance(col, tuple) else str(col)
        for col in df.columns
    ]
    club_col = next((c for c in df.columns if c.strip().lower().endswith("club") or c.strip().lower() == "club"), None)
    if club_col is None:
        club_col = next((c for c in df.columns if "club" in c.lower()), None)
    if club_col is None:
        return []
    clubs = []
    for v in df[club_col].tolist():
        s = str(v).strip()
        if not s or s.lower() == "nan":
            continue
        # Strip a leading country name that read_html sometimes prepends from the flag.
        clubs.append(s)
    return clubs


def squads_for_year(year: int) -> dict[str, list[str]]:
    html = fetch_squad_html(year)
    soup = BeautifulSoup(html, "lxml")
    out: dict[str, list[str]] = {}
    current_team: str | None = None
    # Walk the document in order; track the most recent h3/h4 heading as the team.
    for el in soup.find_all(["h2", "h3", "h4", "table"]):
        if el.name in ("h2", "h3", "h4"):
            current_team = heading_text(el)
            continue
        # el is a table
        if "wikitable" not in (el.get("class") or []) and "sortable" not in (el.get("class") or []):
            # squad tables on these pages are wikitable; skip non-wikitables
            if not el.find("tr"):
                continue
        ok, _ = is_squad_table(el)
        if not ok or current_team is None:
            continue
        clubs = parse_squad_clubs(el)
        if len(clubs) < 18:
            continue
        team = TEAM_ALIASES.get(current_team, current_team)
        # Some pages repeat a team name in stats sections; keep the first squad table.
        if team not in out:
            out[team] = clubs
    return out


def history_index(clubs: list[str]) -> dict:
    n = len(clubs)
    counts = Counter(clubs)
    shared = sum(c for club, c in counts.items() if c >= 2)
    largest_club, largest_bloc = counts.most_common(1)[0]
    return {
        "squad_size": n,
        "history_count": shared,
        "history_share": round(100.0 * shared / n, 1) if n else 0.0,
        "largest_bloc": largest_bloc,
        "largest_bloc_club": largest_club if largest_bloc >= 2 else None,
        "n_clubs": len(counts),
    }


def main():
    # fifa_multi_year finishes are used only to *validate* our complete encoding.
    ref = json.load(open(FIFA_MULTI))["rows"]
    ref_stage = {(r["team"], r["year"]): int(r["stage_int"]) for r in ref}

    rows = []
    mismatches = []
    for year in YEARS:
        print(f"[fetch] {year} …", flush=True)
        squads = squads_for_year(year)
        print(f"  parsed {len(squads)} squads")
        ko = KNOCKOUT[year]
        for team, clubs in sorted(squads.items()):
            hi = history_index(clubs)
            stage_int = ko.get(team, 2)  # not in knockout table -> group stage
            row = {
                "team": team,
                "year": year,
                **hi,
                "stage_int": stage_int,
                "stage_label": STAGE_LABEL[stage_int],
            }
            rows.append(row)
            # Cross-check against fifa_multi_year where it has an opinion.
            # (fifa_multi_year encodes Group as 1; we use 2 to match the chart axis
            #  and the WC22 team_chemistry_vs_paper convention — treat them as equal.)
            r = ref_stage.get((team, year))
            r_norm = 2 if r == 1 else r
            if r is not None and r_norm != stage_int:
                mismatches.append((year, team, "ours", stage_int, "fifa_multi", r))
        time.sleep(1.0)  # be polite to the API

    if mismatches:
        print("\n!!! FINISH MISMATCHES vs fifa_multi_year (investigate) !!!")
        for m in mismatches:
            print("   ", m)
    else:
        print("\n[validate] all finishes agree with fifa_multi_year overlaps ✓")

    # Coverage / sanity report.
    print("\n=== per-year coverage (stage distribution) ===")
    for year in YEARS:
        yr = [r for r in rows if r["year"] == year]
        dist = Counter(r["stage_label"] for r in yr)
        print(f"{year}: {len(yr)} squads — " + ", ".join(f"{k}={dist[k]}" for k in ["Winner","Final","Semi","QF","R16","Group"]))

    print("\n=== canonical-example spot check (history_share, largest bloc) ===")
    for key in [("Spain", 2010), ("Germany", 2014), ("Italy", 2006),
                ("France", 2018), ("Argentina", 2022), ("Croatia", 2018)]:
        m = next((r for r in rows if (r["team"], r["year"]) == key), None)
        if m:
            print(f"  {key[0]} '{str(key[1])[2:]}: share={m['history_share']}%  "
                  f"count={m['history_count']}/{m['squad_size']}  "
                  f"bloc={m['largest_bloc']} ({m['largest_bloc_club']})  finish={m['stage_label']}")

    meta = {
        "source": "en.wikipedia.org '<year> FIFA World Cup squads' (player club at tournament)",
        "metric": "history_share = % of squad players whose tournament club has >=1 teammate in the squad",
        "years_covered": YEARS,
        "finishes_from": "complete 32-team knockout results per WC, cross-validated against fifa_multi_year.json overlaps",
        "stage_encoding": STAGE_LABEL,
        "notes": "Club strings compared only within a squad. history_count/largest_bloc also provided.",
    }
    OUT.write_text(json.dumps({"_meta": meta, "rows": rows}, indent=2))
    print(f"\n[write] {OUT}  ({len(rows)} rows)")


if __name__ == "__main__":
    sys.exit(main())
