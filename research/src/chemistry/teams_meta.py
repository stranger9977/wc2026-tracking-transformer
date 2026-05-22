"""Team metadata — flag codes for the 32 WC22 squads.

`flagcdn.com` serves PNG flags at `https://flagcdn.com/<size>/<code>.png`.
England/Wales/Scotland use sub-codes (gb-eng, gb-wls, gb-sct).
"""
from __future__ import annotations

# Maps PFF team_name → flagcdn code (lowercase, hyphen).
NAME_TO_FLAG: dict[str, str] = {
    "Argentina": "ar",
    "Australia": "au",
    "Belgium": "be",
    "Brazil": "br",
    "Cameroon": "cm",
    "Canada": "ca",
    "Costa Rica": "cr",
    "Croatia": "hr",
    "Denmark": "dk",
    "Ecuador": "ec",
    "England": "gb-eng",
    "France": "fr",
    "Germany": "de",
    "Ghana": "gh",
    "Iran": "ir",
    "Iran, Islamic Republic of": "ir",
    "Japan": "jp",
    "Mexico": "mx",
    "Morocco": "ma",
    "Netherlands": "nl",
    "Poland": "pl",
    "Portugal": "pt",
    "Qatar": "qa",
    "Saudi Arabia": "sa",
    "Senegal": "sn",
    "Serbia": "rs",
    "South Korea": "kr",
    "Korea Republic": "kr",
    "Korea, Republic of": "kr",
    "Spain": "es",
    "Switzerland": "ch",
    "Tunisia": "tn",
    "United States": "us",
    "United States of America": "us",
    "Uruguay": "uy",
    "Wales": "gb-wls",
}


def flag_code(team_name: str | None) -> str | None:
    if not team_name:
        return None
    return NAME_TO_FLAG.get(team_name)
