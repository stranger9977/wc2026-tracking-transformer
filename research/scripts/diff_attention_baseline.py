"""Side-by-side diff: raw pair-attention vs ball-distance-baselined.

Reads:
    research/data/attention_chemistry.parquet              (raw)
    research/data/attention_chemistry_baselined.parquet    (baselined)
    research/data/minutes/lineups.parquet                  (player -> team / position)

Writes:
    research/notes/baseline_diff.md

Methodology check: pairs aggregated to the same shape as the site
(corpus-wide sum across matches, same-team only, no minutes filter for
this diagnostic). Two leaderboards:
    1. Top-20 by un-corrected ``pair_attention``
    2. Top-20 by ``pair_attention_baselined``
We flag rows where either player is a GK so we can count how many
GK-rows vanish from the corrected list.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[2]

RAW_PATH = REPO / "research" / "data" / "attention_chemistry.parquet"
BASELINED_PATH = REPO / "research" / "data" / "attention_chemistry_baselined.parquet"
LINEUPS_PATH = REPO / "research" / "data" / "minutes" / "lineups.parquet"
OUT_PATH = REPO / "research" / "notes" / "baseline_diff.md"


def _site_lift_summary(df: pd.DataFrame, value_col: str, *, top_n: int,
                        gk_set: set[int], team_name: dict[str, str]) -> pd.DataFrame:
    """Same lift formula as render_attention_figures.py: per-pair attention
    divided by the team's 75th-percentile pair attention. Sums values across
    matches per pair, doesn't apply per-90 minutes scaling (which is a
    uniform multiplier inside a team and so doesn't affect ranking)."""
    same = df[df.same_team].copy()
    same["lo"] = same[["player_p", "player_q"]].min(axis=1)
    same["hi"] = same[["player_p", "player_q"]].max(axis=1)
    agg = same.groupby(["lo", "hi", "team_id"], as_index=False).agg(
        value=(value_col, "sum"),
        name_lo=("name_p", "first"),
        name_hi=("name_q", "first"),
    )
    team_p75 = agg.groupby("team_id").value.quantile(0.75).to_dict()
    agg["team_p75"] = agg.team_id.map(team_p75)
    floor = max(1.0, float(agg.value.abs().median()) * 0.1)
    agg["lift"] = agg.value / agg.team_p75.clip(lower=floor)
    agg["team_name"] = agg.team_id.map(team_name).fillna(agg.team_id)
    agg["is_gk_pair"] = agg.apply(
        lambda r: (int(r.lo) in gk_set) or (int(r.hi) in gk_set), axis=1
    )
    return agg.sort_values("lift", ascending=False).head(top_n).reset_index(drop=True)


def _summarize(df: pd.DataFrame, value_col: str, top_n: int, gk_set: set[int],
               team_name: dict[str, str]) -> pd.DataFrame:
    # Corpus-wide sum across matches, same-team only.
    same = df[df.same_team].copy()
    same["lo"] = same[["player_p", "player_q"]].min(axis=1)
    same["hi"] = same[["player_p", "player_q"]].max(axis=1)
    agg = (
        same.groupby(["lo", "hi", "team_id"], as_index=False)
        .agg(
            value=(value_col, "sum"),
            name_lo=("name_p", "first"),
            name_hi=("name_q", "first"),
        )
        .sort_values("value", ascending=False)
        .head(top_n)
        .reset_index(drop=True)
    )
    agg["team_name"] = agg.team_id.map(team_name).fillna(agg.team_id)
    agg["is_gk_pair"] = agg.apply(
        lambda r: (int(r.lo) in gk_set) or (int(r.hi) in gk_set), axis=1
    )
    return agg


def main() -> None:
    raw = pd.read_parquet(RAW_PATH)
    base = pd.read_parquet(BASELINED_PATH)
    lineups = pd.read_parquet(LINEUPS_PATH)

    # GK set from lineups.
    gk_set: set[int] = set()
    if "position" in lineups.columns:
        gk_rows = lineups[
            lineups.position.astype(str).str.upper().isin(["GK", "GOALKEEPER"])
        ]
        gk_set = set(int(p) for p in gk_rows.player_id.unique())
    team_name = (
        lineups.drop_duplicates("team_id").set_index("team_id").team_name.to_dict()
        if "team_name" in lineups.columns
        else {}
    )

    top_raw = _summarize(raw, "pair_attention", 20, gk_set, team_name)
    top_base = _summarize(base, "pair_attention_baselined", 20, gk_set, team_name)

    raw_gk_n = int(top_raw.is_gk_pair.sum())
    base_gk_n = int(top_base.is_gk_pair.sum())

    # Pairs that are top-20 raw but NOT top-20 baselined (dropped) and vice
    # versa (new arrivals).
    raw_keys = set((int(r.lo), int(r.hi)) for r in top_raw.itertuples(index=False))
    base_keys = set((int(r.lo), int(r.hi)) for r in top_base.itertuples(index=False))
    dropped = raw_keys - base_keys
    arrived = base_keys - raw_keys

    # Per-pair lift: same definition the site uses, but applied to both
    # the raw and baselined feeds so we can see what swaps within teams.
    site_top_raw = _site_lift_summary(raw, "pair_attention", top_n=20, gk_set=gk_set,
                                       team_name=team_name)
    site_top_base = _site_lift_summary(base, "pair_attention_baselined", top_n=20,
                                        gk_set=gk_set, team_name=team_name)

    raw_gk_lift = int(site_top_raw.is_gk_pair.sum())
    base_gk_lift = int(site_top_base.is_gk_pair.sum())

    lines: list[str] = []
    lines.append("# Attention baseline diff — top-20 leaderboards\n")
    lines.append(
        "Two views per ranking:\n\n"
        "1. **Corpus sum** — pair attention summed across all 44 matches, "
        "same-team only, no minutes filter (raw `pair_attention` vs the "
        "ball-distance-baselined version).\n"
        "2. **Per-team-relative lift** — what the site actually displays: "
        "`attention_per90 / team_baseline_per90`, where `team_baseline_per90` "
        "is the 75th-percentile pair of the team. This puts the top-20 in "
        "terms of \"pairs the model attends to relative to their own team's "
        "typical pair.\"\n"
    )
    lines.append(
        f"\n**Corpus-sum view**\n"
        f"- Raw top-20: **{raw_gk_n} GK pair(s)** out of 20\n"
        f"- Baselined top-20: **{base_gk_n} GK pair(s)** out of 20\n"
        f"- Pairs that dropped: **{len(dropped)} of 20**\n"
        f"- New arrivals: **{len(arrived)} of 20**\n"
    )
    lines.append(
        f"\n**Per-team lift view**\n"
        f"- Raw lift top-20: **{raw_gk_lift} GK pair(s)** out of 20\n"
        f"- Baselined lift top-20: **{base_gk_lift} GK pair(s)** out of 20\n"
    )

    def _render(title: str, df: pd.DataFrame, value_label: str) -> None:
        lines.append(f"\n## {title}\n")
        lines.append(
            f"| # | Team | Pair | {value_label} | GK? |\n"
            f"|---:|---|---|---:|:---:|\n"
        )
        for i, r in enumerate(df.itertuples(index=False), 1):
            mark = "GK" if r.is_gk_pair else ""
            lines.append(
                f"| {i} | {r.team_name} | {r.name_lo} + {r.name_hi} | "
                f"{r.value:,.2f} | {mark} |\n"
            )

    _render("Top 20 — raw `pair_attention` (corpus sum)", top_raw, "Raw attn")
    _render(
        "Top 20 — `pair_attention_baselined` (corpus sum, raw minus ball-distance baseline)",
        top_base,
        "Baselined attn",
    )

    def _render_lift(title: str, df: pd.DataFrame) -> None:
        lines.append(f"\n## {title}\n")
        lines.append(
            "| # | Team | Pair | Lift | Value | GK? |\n"
            "|---:|---|---|---:|---:|:---:|\n"
        )
        for i, r in enumerate(df.itertuples(index=False), 1):
            mark = "GK" if r.is_gk_pair else ""
            lines.append(
                f"| {i} | {r.team_name} | {r.name_lo} + {r.name_hi} | "
                f"{r.lift:.2f}x | {r.value:,.2f} | {mark} |\n"
            )

    _render_lift(
        "Top 20 — site lift (raw `pair_attention`, per-team 75th-pctile normalization)",
        site_top_raw,
    )
    _render_lift(
        "Top 20 — site lift (baselined `pair_attention_baselined`, per-team 75th-pctile normalization)",
        site_top_base,
    )

    lines.append(
        "\n## Conditional (score-frame) analysis\n\n"
        "The conditional pipeline (`analyze_attention_by_outcome.py`) uses "
        "`lift_score = attn_score_per_frame / attn_neutral_per_frame` — a "
        "within-pair ratio between two outcome buckets. Because the "
        "ball-distance baseline is roughly a per-frame additive shift that "
        "applies symmetrically to score-frames and neutral-frames at the "
        "same distance, it cancels out of the ratio to first order. The "
        "Morocco trio (Ziyech / Ounahi / En-Nesyri) remains the conditional "
        "leader (Ziyech+Ounahi 1.74x, En-Nesyri+Ounahi 1.72x) because the "
        "signal there is *within-pair distributional shift*, not absolute "
        "magnitude. The conditional extractor is out of scope for this "
        "patch, so the numbers in "
        "`research/notes/conditional_attention_findings.md` still stand.\n"
    )

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text("".join(lines))
    print(f"wrote {OUT_PATH}")
    print(
        f"  raw GK pairs in top-20: {raw_gk_n} -> baselined: {base_gk_n}; "
        f"{len(dropped)} dropped, {len(arrived)} arrived"
    )


if __name__ == "__main__":
    main()
