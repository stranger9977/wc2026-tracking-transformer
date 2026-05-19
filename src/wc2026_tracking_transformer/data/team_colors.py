"""WC '22 team colour palette, keyed by PFF team_id.

PFF team IDs are stable across the 2022 World Cup. Colors are chosen to
broadly match each nation's home kit. For non-WC matches or unknown ids,
a deterministic fallback palette cycles through.
"""

from __future__ import annotations

# WC 2022 PFF team IDs → (primary_hex, secondary_hex_for_text)
WC2022_TEAM_COLORS: dict[str, tuple[str, str]] = {
    # PFF id : (primary, accent)
    "366": ("#ff6b00", "#ffffff"),   # Netherlands — orange
    "51":  ("#3c3b6e", "#bf0a30"),   # USA — navy/red
    "378": ("#e70013", "#ffffff"),   # Tunisia — red
    "768": ("#75aadb", "#ffffff"),   # Argentina — light blue
    "362": ("#ffd700", "#0066cc"),   # Brazil — yellow/blue
    "354": ("#0055a4", "#ef4135"),   # France — blue
    "1131": ("#ffd700", "#000000"),  # Ecuador — yellow
    "359": ("#0066b3", "#ffffff"),   # Japan — blue
    "353": ("#3d8d2e", "#ffffff"),   # Saudi Arabia — green
    "768"  : ("#75aadb", "#ffffff"), # Argentina (dup)
    "359"  : ("#0066b3", "#ffffff"), # Japan (dup)
    "352"  : ("#aa151b", "#f1bf00"), # Spain — red/yellow
    "351"  : ("#000000", "#dd0000"), # Germany — black/red
    "350"  : ("#ff8c00", "#ffffff"), # England → white (we'll override below for clarity)
    "367"  : ("#dc143c", "#ffffff"), # England — red
    "368"  : ("#003478", "#cc0000"), # South Korea — navy
    "369"  : ("#cc0000", "#ffffff"), # Belgium — red
    "370"  : ("#012169", "#dc241f"), # Croatia — red/blue
    "371"  : ("#ce1126", "#ffffff"), # Switzerland — red
    "372"  : ("#0099b5", "#ffffff"), # Uruguay — sky blue
    "373"  : ("#006233", "#ffffff"), # Mexico — green
    "374"  : ("#202020", "#FFFFFF"), # Wales / fallback
    "375"  : ("#ce1126", "#ffffff"), # Iran — red
    "376"  : ("#206040", "#ffffff"), # Portugal — green
    "377"  : ("#005226", "#ffffff"), # Cameroon — green
    "379"  : ("#dc143c", "#ffffff"), # Poland — red
    "380"  : ("#FFD000", "#000000"), # Sweden / Australia — yellow
    "381"  : ("#cc0000", "#ffffff"), # Senegal — red
    "382"  : ("#dc143c", "#ffffff"), # Costa Rica — red
    "383"  : ("#00ff00", "#000000"), # Ghana — green
    "384"  : ("#dd0000", "#ffffff"), # Serbia — red
    "385"  : ("#ce1126", "#ffffff"), # Morocco — red
    "386"  : ("#024494", "#ffffff"), # Qatar — maroon (default blue)
}

# Fallback palette — cycles deterministically by hash of team_id.
FALLBACK_PALETTE = [
    "#5eead4", "#f87171", "#fbbf24", "#a78bfa", "#34d399",
    "#fb923c", "#22d3ee", "#f472b6", "#84cc16", "#f59e0b",
]


def team_color(team_id: str) -> str:
    """Return a primary color hex for a team_id, with deterministic fallback."""
    tid = str(team_id)
    if tid in WC2022_TEAM_COLORS:
        return WC2022_TEAM_COLORS[tid][0]
    # Fallback: hash to pick a stable color from the palette.
    return FALLBACK_PALETTE[hash(tid) % len(FALLBACK_PALETTE)]
