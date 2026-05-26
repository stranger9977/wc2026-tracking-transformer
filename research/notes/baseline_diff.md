# Attention baseline diff — top-20 leaderboards
Two views per ranking:

1. **Corpus sum** — pair attention summed across all 44 matches, same-team only, no minutes filter (raw `pair_attention` vs the ball-distance-baselined version).
2. **Per-team-relative lift** — what the site actually displays: `attention_per90 / team_baseline_per90`, where `team_baseline_per90` is the 75th-percentile pair of the team. This puts the top-20 in terms of "pairs the model attends to relative to their own team's typical pair."

**Corpus-sum view**
- Raw top-20: **20 GK pair(s)** out of 20
- Baselined top-20: **20 GK pair(s)** out of 20
- Pairs that dropped: **20 of 20**
- New arrivals: **20 of 20**

**Per-team lift view**
- Raw lift top-20: **20 GK pair(s)** out of 20
- Baselined lift top-20: **20 GK pair(s)** out of 20

## Top 20 — raw `pair_attention` (corpus sum)
| # | Team | Pair | Raw attn | GK? |
|---:|---|---|---:|:---:|
| 1 | France | Hugo Lloris + Kylian Mbappé | 19,910.57 | GK |
| 2 | Argentina | Emiliano Martínez + Lionel Messi | 18,269.86 | GK |
| 3 | Croatia | Ivan Perisic + Dominik Livakovic | 17,180.07 | GK |
| 4 | France | Hugo Lloris + Antoine Griezmann | 16,719.17 | GK |
| 5 | Croatia | Mateo Kovacic + Dominik Livakovic | 16,273.86 | GK |
| 6 | Croatia | Luka Modric + Dominik Livakovic | 15,821.01 | GK |
| 7 | Argentina | Emiliano Martínez + Alexis Mac Allister | 15,731.12 | GK |
| 8 | France | Hugo Lloris + Olivier Giroud | 15,481.52 | GK |
| 9 | Croatia | Josko Gvardiol + Dominik Livakovic | 15,460.66 | GK |
| 10 | Argentina | Emiliano Martínez + Rodrigo de Paul | 15,087.15 | GK |
| 11 | France | Hugo Lloris + Aurélien Tchouaméni | 15,029.58 | GK |
| 12 | Croatia | Andrej Kramaric + Dominik Livakovic | 14,988.37 | GK |
| 13 | Argentina | Nicolás Otamendi + Emiliano Martínez | 14,352.42 | GK |
| 14 | Argentina | Emiliano Martínez + Julian Alvarez | 14,340.17 | GK |
| 15 | France | Hugo Lloris + Ousmane Dembele | 13,981.35 | GK |
| 16 | Croatia | Dominik Livakovic + Josip Juranovic | 13,886.84 | GK |
| 17 | France | Hugo Lloris + Theo Hernandez | 13,850.42 | GK |
| 18 | France | Hugo Lloris + Adrien Rabiot | 13,847.28 | GK |
| 19 | Argentina | Emiliano Martínez + Enzo Fernandez | 13,379.96 | GK |
| 20 | Croatia | Dejan Lovren + Dominik Livakovic | 13,208.62 | GK |

## Top 20 — `pair_attention_baselined` (corpus sum, raw minus ball-distance baseline)
| # | Team | Pair | Baselined attn | GK? |
|---:|---|---|---:|:---:|
| 1 | Brazil | Alisson + Richarlison | 4,029.66 | GK |
| 2 | Spain | Unai Simon + Sergio Busquets | 3,625.76 | GK |
| 3 | Brazil | Alisson + Vinícius Junior | 3,476.36 | GK |
| 4 | Spain | Unai Simon + Pedri | 3,147.70 | GK |
| 5 | South Korea | Seun-gyu Kim + Gue-sung Cho | 3,087.62 | GK |
| 6 | Spain | Unai Simon + Dani Olmo | 3,007.28 | GK |
| 7 | Brazil | Alisson + Casemiro | 2,820.23 | GK |
| 8 | South Korea | Heung-min Son + Seun-gyu Kim | 2,800.31 | GK |
| 9 | Brazil | Alisson + Lucas Paquetá | 2,798.40 | GK |
| 10 | Spain | Rodri + Unai Simon | 2,747.33 | GK |
| 11 | Brazil | Alisson + Raphinha | 2,640.55 | GK |
| 12 | Spain | Unai Simon + Marco Asensio | 2,615.99 | GK |
| 13 | Spain | Unai Simon + Gavi | 2,575.21 | GK |
| 14 | Netherlands | Cody Gakpo + Andries Noppert | 2,476.81 | GK |
| 15 | Brazil | Alisson + Neymar | 2,428.20 | GK |
| 16 | Spain | Unai Simon + Ferran Torres | 2,293.37 | GK |
| 17 | Germany | Leroy Sané + Manuel Neuer | 2,278.26 | GK |
| 18 | Spain | Unai Simon + Nico Williams | 2,123.87 | GK |
| 19 | Germany | Manuel Neuer + Jamal Musiala | 2,114.79 | GK |
| 20 | Brazil | Alisson + Marquinhos | 2,110.60 | GK |

## Top 20 — site lift (raw `pair_attention`, per-team 75th-pctile normalization)
| # | Team | Pair | Lift | Value | GK? |
|---:|---|---|---:|---:|:---:|
| 1 | Cameroon | Eric Maxim Choupo-Moting + Devis Epassy | 5.55x | 5,878.63 | GK |
| 2 | South Korea | Heung-min Son + Seun-gyu Kim | 5.38x | 9,662.09 | GK |
| 3 | South Korea | Seun-gyu Kim + Gue-sung Cho | 5.25x | 9,434.21 | GK |
| 4 | Argentina | Emiliano Martínez + Lionel Messi | 5.22x | 18,269.86 | GK |
| 5 | Brazil | Alisson + Richarlison | 5.18x | 11,763.34 | GK |
| 6 | Japan | Daichi Kamada + Shuichi Gonda | 4.97x | 8,773.08 | GK |
| 7 | Japan | Hidemasa Morita + Shuichi Gonda | 4.85x | 8,557.64 | GK |
| 8 | Brazil | Alisson + Casemiro | 4.85x | 11,001.74 | GK |
| 9 | France | Hugo Lloris + Kylian Mbappé | 4.72x | 19,910.57 | GK |
| 10 | Brazil | Alisson + Vinícius Junior | 4.63x | 10,514.04 | GK |
| 11 | Brazil | Alisson + Marquinhos | 4.60x | 10,438.04 | GK |
| 12 | Morocco | Bono + Hakim Ziyech | 4.58x | 12,287.64 | GK |
| 13 | Portugal | Diogo Dalot + Diogo Costa | 4.57x | 8,052.14 | GK |
| 14 | Croatia | Ivan Perisic + Dominik Livakovic | 4.51x | 17,180.07 | GK |
| 15 | Argentina | Emiliano Martínez + Alexis Mac Allister | 4.50x | 15,731.12 | GK |
| 16 | South Korea | Moon-hwan Kim + Seun-gyu Kim | 4.49x | 8,068.39 | GK |
| 17 | Serbia | Aleksandar Mitrovic + Vanja Milinković-Savić | 4.43x | 8,473.82 | GK |
| 18 | Belgium | Kevin De Bruyne + Thibaut Courtois | 4.41x | 6,286.12 | GK |
| 19 | Spain | Unai Simon + Sergio Busquets | 4.36x | 10,323.79 | GK |
| 20 | Brazil | Alisson + Raphinha | 4.36x | 9,902.43 | GK |

## Top 20 — site lift (baselined `pair_attention_baselined`, per-team 75th-pctile normalization)
| # | Team | Pair | Lift | Value | GK? |
|---:|---|---|---:|---:|:---:|
| 1 | Brazil | Alisson + Richarlison | 271.88x | 4,029.66 | GK |
| 2 | Brazil | Alisson + Vinícius Junior | 234.55x | 3,476.36 | GK |
| 3 | South Korea | Seun-gyu Kim + Gue-sung Cho | 208.32x | 3,087.62 | GK |
| 4 | Brazil | Alisson + Casemiro | 190.28x | 2,820.23 | GK |
| 5 | South Korea | Heung-min Son + Seun-gyu Kim | 188.94x | 2,800.31 | GK |
| 6 | Brazil | Alisson + Lucas Paquetá | 188.81x | 2,798.40 | GK |
| 7 | Brazil | Alisson + Raphinha | 178.16x | 2,640.55 | GK |
| 8 | Netherlands | Cody Gakpo + Andries Noppert | 167.11x | 2,476.81 | GK |
| 9 | Brazil | Alisson + Neymar | 163.83x | 2,428.20 | GK |
| 10 | Brazil | Alisson + Marquinhos | 142.40x | 2,110.60 | GK |
| 11 | Netherlands | Denzel Dumfries + Andries Noppert | 140.13x | 2,076.86 | GK |
| 12 | Netherlands | Frenkie de Jong + Andries Noppert | 138.32x | 2,050.08 | GK |
| 13 | France | Hugo Lloris + Kylian Mbappé | 127.95x | 1,896.48 | GK |
| 14 | France | Hugo Lloris + Olivier Giroud | 125.35x | 1,857.93 | GK |
| 15 | South Korea | Moon-hwan Kim + Seun-gyu Kim | 123.11x | 1,824.65 | GK |
| 16 | Netherlands | Daley Blind + Andries Noppert | 122.86x | 1,820.98 | GK |
| 17 | South Korea | In-beom Hwang + Seun-gyu Kim | 118.03x | 1,749.31 | GK |
| 18 | Netherlands | Virgil van Dijk + Andries Noppert | 109.97x | 1,629.92 | GK |
| 19 | Brazil | Alisson + Thiago Silva | 107.30x | 1,590.37 | GK |
| 20 | France | Hugo Lloris + Antoine Griezmann | 106.92x | 1,584.69 | GK |

## Conditional (score-frame) analysis

The conditional pipeline (`analyze_attention_by_outcome.py`) uses `lift_score = attn_score_per_frame / attn_neutral_per_frame` — a within-pair ratio between two outcome buckets. Because the ball-distance baseline is roughly a per-frame additive shift that applies symmetrically to score-frames and neutral-frames at the same distance, it cancels out of the ratio to first order. The Morocco trio (Ziyech / Ounahi / En-Nesyri) remains the conditional leader (Ziyech+Ounahi 1.74x, En-Nesyri+Ounahi 1.72x) because the signal there is *within-pair distributional shift*, not absolute magnitude. The conditional extractor is out of scope for this patch, so the numbers in `research/notes/conditional_attention_findings.md` still stand.

## Shipped on 2026-05-26

- `research/data/attention_chemistry_baselined.parquet` is on disk (18,534
  rows, 44 matches, 10 columns including `pair_attention`,
  `pair_attention_expected`, `pair_attention_baselined`). 89 files in the
  shards dir broke down as 44 per-match parquets + 44 per-match
  `_globals.npz` + 1 `_global_bin_totals.parquet` — no duplicates, all
  matches covered exactly once.
- `research/site/data/attention_pairs.json` (300 rows) and
  `attention_groups.json` (310 groups) were re-rendered off the baselined
  parquet via `render_attention_figures.py` (which already prefers the
  baselined parquet when present).
- 31 per-team figures at `research/site/assets/figures/team_<id>_attention.png`
  were re-rendered from the same.

## Per-bin global baseline (final)

| bin | range (m) | n (pair-frames) | mean attention |
| --- | --------- | --------------- | -------------- |
| 0 | 0–5    |  2.30M | 0.0635 |
| 1 | 5–10   | 11.56M | 0.0633 |
| 2 | 10–15  | 23.21M | 0.0663 |
| 3 | 15–20  | 31.52M | 0.0714 |
| 4 | 20–25  | 32.35M | 0.0784 |
| 5 | 25–30  | 28.19M | 0.0898 |
| 6 | 30–35  | 20.59M | 0.1020 |
| 7 | 35–40  | 13.28M | 0.1218 |
| 8 | 40–45  |  7.71M | 0.1412 |
| 9 | 45+    |  6.81M | 0.1637 |

Baseline grows monotonically with distance — pairs that drift far from the
ball (deep CBs in build-up, GKs vs the long ball) get a larger
expected-attention deduction.

## Morocco cross-reference

Same-team baselined leaderboard for Morocco still leads with Bono-anchored
pairs (Bono–En-Nesyri 3,800; Bono–Ziyech 3,217; Bono–Ounahi 2,490).
Off-off pairs in this raw-baselined view are noisy (Ziyech+Ounahi
unconditional sum is dominated by frames where neither was near the ball
and the baseline already accounts for proximity). The Ziyech+Ounahi/Amrabat
family does surface strongly in the outcome-conditional view in
`research/data/attention_by_outcome.parquet`:

| pair | attn_score_sum | n score-frames | mean per score-frame |
| ---- | ---: | ---: | ---: |
| Ziyech – Amrabat | 32.61 | 349 | 0.094 |
| Ziyech – Ounahi  | 28.85 | 252 | 0.114 |
| Ziyech – Mazraoui | 24.43 | 209 | 0.117 |
| Saïss – Ziyech | 26.11 | 254 | 0.103 |
| Boufal – En-Nesyri | 22.11 | 218 | 0.101 |
| Hakimi – Ziyech | 17.78 | 259 | 0.069 |

Consistent with the "within-pair distributional shift" interpretation
above — these pairs aren't outliers in absolute attention but their
attention is concentrated on the moments where Morocco threatened to score.
