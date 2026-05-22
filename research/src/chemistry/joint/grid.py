"""Bransen 5x5 position responsibility grid.

We map PFF positionGroupType (and a few additional codes used in metadata)
to (row, col) on the grid in Table 2 of the paper. row 0 is the most
attacking line, row 4 is the back line.

Layout (row, col):
    row 0 (forwards):  (0,0) LWF, _, (0,2) ST, _, (0,4) RWF
    row 1 (att mids):  _, (1,1) LAM, (1,2) AM, (1,3) RAM, _
    row 2 (mids):      (2,0) LW, (2,1) LCM, _, (2,3) RCM, (2,4) RW
    row 3 (def mids):  (3,0) LWB, (3,1) LDM, (3,2) DM, (3,3) RDM, (3,4) RWB
    row 4 (defenders): (4,0) LB, (4,1) LCB, (4,2) CB, (4,3) RCB, (4,4) RB

Goalkeepers sit "behind" the back line at (5, 2).
"""
from __future__ import annotations

import math

# Mapping for PFF positionGroupType values seen in WC22:
#   GK, LB, LCB, MCB, RCB, RB, LWB, RWB, CM, AM, LW, RW, CF
# Plus extra slots we may encounter from rosters: LAM/RAM/CAM, ST, LDM/RDM/DM, LWF/RWF, LCM/RCM, LF/RF, CDM
PFF_TO_GRID: dict[str, tuple[int, int]] = {
    # Forwards
    "CF": (0, 2),
    "ST": (0, 2),
    "LWF": (0, 0),
    "RWF": (0, 4),
    "LF": (0, 1),
    "RF": (0, 3),
    "SS": (1, 2),
    # Attacking mids
    "AM": (1, 2),
    "CAM": (1, 2),
    "LAM": (1, 1),
    "RAM": (1, 3),
    # Wingers (line of 3)
    "LW": (2, 0),
    "RW": (2, 4),
    "LM": (2, 1),
    "RM": (2, 3),
    # Central / box-to-box mids
    "CM": (2, 2),
    "LCM": (2, 1),
    "RCM": (2, 3),
    # Defensive mids
    "DM": (3, 2),
    "CDM": (3, 2),
    "LDM": (3, 1),
    "RDM": (3, 3),
    # Wingbacks
    "LWB": (3, 0),
    "RWB": (3, 4),
    # Defenders
    "CB": (4, 2),
    "MCB": (4, 2),
    "LCB": (4, 1),
    "RCB": (4, 3),
    "LB": (4, 0),
    "RB": (4, 4),
    # Goalkeeper
    "GK": (5, 2),
}


def grid_cell(pos: str | None) -> tuple[int, int]:
    if not pos:
        return (3, 2)  # default to DM if missing
    return PFF_TO_GRID.get(pos.upper(), (3, 2))


def grid_distance(pos_a: str | None, pos_b: str | None) -> float:
    a = grid_cell(pos_a)
    b = grid_cell(pos_b)
    return math.sqrt((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2)


def grid_role(pos: str | None) -> str:
    """Coarse role bucket: GK, DEF, MID, FWD."""
    r, _ = grid_cell(pos)
    if r == 5:
        return "GK"
    if r == 4:
        return "DEF"
    if r in (2, 3):
        return "MID"
    return "FWD"
