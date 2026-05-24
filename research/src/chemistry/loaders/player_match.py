"""Cross-source player matching: PFF ↔ StatsBomb (or any other source).

Match strategy
--------------
1. Manual override map (loaded from research/data/manual_player_overrides.json).
2. Exact normalized-name match → confidence 1.0.
3. Word-subset (PFF short name ⊆ SB long name) → 0.92.
4. Last-name + first-initial → 0.85.
5. Pure last-name (only if unique) → 0.7.
6. Reverse word-subset (SB short ⊆ PFF long) → 0.85.
7. Fuzzy fallback using difflib.SequenceMatcher (stdlib, no new dep).
   Compares each unmatched PFF name to every SB name, accepts the best
   candidate only if the ratio ≥ 0.85 AND the runner-up trails by ≥ 0.05.
   Confidence = the ratio. Stdlib-only — no `python-Levenshtein`.

The result is a DataFrame: pff_player_id, statsbomb_player_id, name_pff, name_sb,
strategy, confidence.
"""
from __future__ import annotations

import json
import re
import unicodedata
from collections import defaultdict
from difflib import SequenceMatcher
from pathlib import Path

import pandas as pd


# Threshold for the fuzzy fallback. 0.85 = ~85% character similarity after
# normalization. Set high to avoid false positives between e.g. "Pedro" vs
# "Pedri" or two unrelated short names that happen to share characters.
_FUZZY_THRESHOLD = 0.85
# Require the best candidate to beat the runner-up by this margin so a single
# clear winner is needed; otherwise the match is ambiguous and we skip.
_FUZZY_MARGIN = 0.05


def _load_manual_overrides() -> dict[str, str]:
    """Load PFF→SB name overrides from data/manual_player_overrides.json.

    Returns an empty dict if the file is missing. The JSON shape is
    `{"overrides": {"PFF Name": "Canonical SB Name", ...}}`.
    """
    here = Path(__file__).resolve()
    # research/src/chemistry/loaders/player_match.py → research/data/...
    repo_data = here.parents[3] / "data" / "manual_player_overrides.json"
    if not repo_data.exists():
        return {}
    try:
        raw = json.loads(repo_data.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    return dict(raw.get("overrides", {}))


# Loaded once at module import; refresh by re-importing if the file changes.
MANUAL_OVERRIDES: dict[str, str] = _load_manual_overrides()


def normalize_name(name: str) -> str:
    """Lowercase + strip diacritics + drop punctuation/spaces."""
    if not name:
        return ""
    s = unicodedata.normalize("NFKD", str(name))
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = s.lower()
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def last_name_key(name: str) -> str:
    parts = normalize_name(name).split()
    return parts[-1] if parts else ""


def first_initial(name: str) -> str:
    parts = normalize_name(name).split()
    return parts[0][:1] if parts else ""


def _fuzzy_best(pff_norm: str, sb_index: list[tuple[int, str, str]]) -> tuple[int, str, float] | None:
    """Find the single best SequenceMatcher match for `pff_norm`.

    sb_index: list of (sb_id, original_name, normalized_name).
    Returns (sb_id, sb_name, ratio) iff:
      - top ratio ≥ _FUZZY_THRESHOLD
      - margin over runner-up ≥ _FUZZY_MARGIN (unambiguous winner)
    Otherwise None.
    """
    if not pff_norm or len(pff_norm) < 4:
        return None
    # Pre-filter to candidates sharing at least the first letter — speeds up
    # the O(N) loop on the unmatched residual without affecting accuracy.
    first = pff_norm[0]
    sm = SequenceMatcher(autojunk=False)
    sm.set_seq2(pff_norm)
    top: tuple[float, int, str] | None = None
    runner: float = 0.0
    for sid, raw_name, sb_norm in sb_index:
        if not sb_norm or sb_norm[0] != first:
            # quick reject on first letter
            # (Latin-script names where unicodedata normalization preserves first letter)
            continue
        sm.set_seq1(sb_norm)
        # quick_ratio is an upper bound; fall through to ratio only when promising
        if sm.quick_ratio() < _FUZZY_THRESHOLD:
            continue
        r = sm.ratio()
        if top is None or r > top[0]:
            if top is not None:
                runner = top[0]
            top = (r, sid, raw_name)
        elif r > runner:
            runner = r
    if top is None or top[0] < _FUZZY_THRESHOLD:
        return None
    if top[0] - runner < _FUZZY_MARGIN:
        return None
    return top[1], top[2], top[0]


def build_player_match(
    pff_players: pd.DataFrame,
    sb_players: pd.DataFrame,
) -> pd.DataFrame:
    """Match every PFF player to a StatsBomb player by name.

    pff_players: columns (pff_player_id, name)
    sb_players: columns (statsbomb_player_id, name)
    """
    # Build normalized indices on the SB side
    sb_by_norm: dict[str, list[tuple[int, str]]] = defaultdict(list)
    sb_by_last: dict[str, list[tuple[int, str]]] = defaultdict(list)
    sb_by_last_initial: dict[tuple[str, str], list[tuple[int, str]]] = defaultdict(list)
    # Word-set index: every SB player indexed by every word in their normalized
    # name. Lets us match the PFF short form "Lionel Messi" to SB's full legal
    # name "Lionel Andrés Messi Cuccittini" when {lionel, messi} ⊆ {lionel,
    # andres, messi, cuccittini}.
    sb_full: list[tuple[int, str, frozenset[str]]] = []
    # Flat (sid, raw_name, norm_name) list for the fuzzy fallback.
    sb_flat: list[tuple[int, str, str]] = []
    for r in sb_players.itertuples():
        norm = normalize_name(r.name)
        sb_by_norm[norm].append((int(r.statsbomb_player_id), r.name))
        ln = last_name_key(r.name)
        sb_by_last[ln].append((int(r.statsbomb_player_id), r.name))
        fi = first_initial(r.name)
        if ln and fi:
            sb_by_last_initial[(ln, fi)].append((int(r.statsbomb_player_id), r.name))
        words = frozenset(w for w in norm.split() if len(w) >= 2)
        if words:
            sb_full.append((int(r.statsbomb_player_id), r.name, words))
        sb_flat.append((int(r.statsbomb_player_id), r.name, norm))

    out: list[dict] = []
    for r in pff_players.itertuples():
        pff_id = int(r.pff_player_id)
        pff_name = r.name
        # 1. Manual override
        override = MANUAL_OVERRIDES.get(pff_name)
        if override:
            cands = sb_by_norm.get(normalize_name(override), [])
            if cands:
                sid, sname = cands[0]
                out.append({"pff_player_id": pff_id, "statsbomb_player_id": sid,
                            "name_pff": pff_name, "name_sb": sname,
                            "strategy": "override", "confidence": 0.95})
                continue
        # 2. Exact normalized
        norm = normalize_name(pff_name)
        cands = sb_by_norm.get(norm, [])
        if len(cands) == 1:
            sid, sname = cands[0]
            out.append({"pff_player_id": pff_id, "statsbomb_player_id": sid,
                        "name_pff": pff_name, "name_sb": sname,
                        "strategy": "exact", "confidence": 1.0})
            continue
        # 3. Word-subset: PFF name's words ⊆ SB name's words. This catches the
        # "Lionel Messi" → "Lionel Andrés Messi Cuccittini" pattern (PFF
        # publishes short common names; SB publishes legal full names).
        pff_words = frozenset(w for w in norm.split() if len(w) >= 2)
        if len(pff_words) >= 2:
            cands = [(sid, sname) for sid, sname, sw in sb_full if pff_words.issubset(sw)]
            if len(cands) == 1:
                sid, sname = cands[0]
                out.append({"pff_player_id": pff_id, "statsbomb_player_id": sid,
                            "name_pff": pff_name, "name_sb": sname,
                            "strategy": "word_subset", "confidence": 0.92})
                continue
        # 4. Last + first initial
        ln = last_name_key(pff_name); fi = first_initial(pff_name)
        cands = sb_by_last_initial.get((ln, fi), [])
        if len(cands) == 1:
            sid, sname = cands[0]
            out.append({"pff_player_id": pff_id, "statsbomb_player_id": sid,
                        "name_pff": pff_name, "name_sb": sname,
                        "strategy": "last+initial", "confidence": 0.85})
            continue
        # 5. Pure last name (unique)
        cands = sb_by_last.get(ln, [])
        if len(cands) == 1:
            sid, sname = cands[0]
            out.append({"pff_player_id": pff_id, "statsbomb_player_id": sid,
                        "name_pff": pff_name, "name_sb": sname,
                        "strategy": "last_only", "confidence": 0.7})
            continue
        # 6. Reverse word-subset: SB short name ⊆ PFF long name.
        if len(pff_words) >= 2:
            cands = [(sid, sname) for sid, sname, sw in sb_full
                     if len(sw) >= 2 and sw.issubset(pff_words)]
            if len(cands) == 1:
                sid, sname = cands[0]
                out.append({"pff_player_id": pff_id, "statsbomb_player_id": sid,
                            "name_pff": pff_name, "name_sb": sname,
                            "strategy": "reverse_word_subset", "confidence": 0.85})
                continue
        # 7. Fuzzy fallback (SequenceMatcher).
        hit = _fuzzy_best(norm, sb_flat)
        if hit is not None:
            sid, sname, ratio = hit
            out.append({"pff_player_id": pff_id, "statsbomb_player_id": sid,
                        "name_pff": pff_name, "name_sb": sname,
                        "strategy": "fuzzy", "confidence": round(float(ratio), 3)})
            continue

    return pd.DataFrame(out)
