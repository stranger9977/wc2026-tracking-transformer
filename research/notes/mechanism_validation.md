# Mechanism validation against AW-JOI

**Question:** does the dataset surface, on the labelled Whiteboard clips, examples where the affected pair's AW-JOI is elevated inside the mechanism's window vs the rest of the clip?

- Metric: AW-JOI per frame = `attn_ball→p(t) * attn_ball→q(t) * max(ΔP_score(t), 0)`. In-window = ±10 frames around the move's `peak_d_net_frame` (≈ ±2 s at 5 Hz); baseline = rest of the clip.
- Affected pair = the move's shifted player + the same-team non-GK teammate with the highest joint ball-attention in the window.
- `lift = mean(in-window) / mean(baseline)`. >1 means the pair is more ball-coupled-and-value-creating when the mechanism plays out than the average frame of the surrounding clip.

**Headline:** 6 of the 9 open-play mechanisms have at least one labelled example with AW-JOI lift >1 over the clip baseline. The 3 corner-kick mechanisms (Meat Wall, Near-Post Flick-On, Short-Corner Overload) have no Whiteboard clip yet — none of the 5 featured plays are corners.

## Per-example evidence

| mechanism | clip | shifted → partner | AW-JOI in-window | AW-JOI baseline | lift |
|---|---|---|---:|---:|---:|
| Gegenpressing Swarm | argentina-france-mbappe-volley | Lionel Messi → Rodrigo de Paul | 1.24e-04 | 7.59e-05 | 1.63× |
| Gegenpressing Swarm | japan-spain-doan | Shogo Taniguchi → Junya Ito | 2.88e-04 | 4.02e-05 | 7.16× |
| Rest-Defense Anchoring | netherlands-usa-memphis | Virgil van Dijk → Jurrien Timber | 1.14e-04 | 7.32e-05 | 1.55× |
| The Blind Pass / Scan-and-Release | netherlands-usa-memphis | Cody Gakpo → Memphis Depay | 2.28e-04 | 2.34e-05 | 9.76× |
| The Decoy Run | argentina-france-di-maria | Nicolas Tagliafico → Alexis Mac Allister | 7.04e-05 | 5.36e-05 | 1.31× |
| The Decoy Run | argentina-france-mbappe-volley | Raphael Varane → Dayot Upamecano | 1.23e-04 | 7.30e-05 | 1.69× |
| The Decoy Run | japan-spain-doan | Alvaro Morata → Dani Olmo | 3.25e-05 | 1.12e-04 | 0.29× |
| The Decoy Run | argentina-croatia-julian | Nicolas Tagliafico → Nahuel Molina | 1.38e-04 | 3.32e-05 | 4.15× |
| The Pin (Fixing the Defender) | argentina-france-di-maria | Nicolas Tagliafico → Cristian Romero | 1.44e-04 | 4.63e-05 | 3.10× |
| The Pin (Fixing the Defender) | argentina-france-mbappe-volley | Dayot Upamecano → Kylian Mbappé | 7.51e-05 | 4.88e-05 | 1.54× |
| The Pin (Fixing the Defender) | argentina-croatia-julian | Nicolas Tagliafico → Nahuel Molina | 1.32e-04 | 3.52e-05 | 3.74× |
| The Third-Man Triangle | argentina-france-di-maria | Nahuel Molina → Alexis Mac Allister | 7.04e-05 | 7.27e-05 | 0.97× |
| The Third-Man Triangle | argentina-france-di-maria | Julian Alvarez → Lionel Messi | 4.94e-05 | 4.36e-05 | 1.13× |
| The Third-Man Triangle | netherlands-usa-memphis | Memphis Depay → Jurrien Timber | 1.07e-04 | 5.12e-05 | 2.09× |
| The Third-Man Triangle | netherlands-usa-memphis | Frenkie de Jong → Jurrien Timber | 8.37e-05 | 2.79e-05 | 3.00× |

## Per-mechanism reading

### Gegenpressing Swarm

**Chemistry-positive in the data.** 2 labelled example(s); 2/2 with in-window AW-JOI exceeding clip baseline. Mean in-window AW-JOI 2.06e-04 vs baseline 5.80e-05.
- *argentina-france-mbappe-volley* — Lionel Messi → Rodrigo de Paul: in-window 1.24e-04, baseline 7.59e-05 (1.63×).
- *japan-spain-doan* — Shogo Taniguchi → Junya Ito: in-window 2.88e-04, baseline 4.02e-05 (7.16×).

### Near-Post Flick-On

**Coming soon.** This is a corner-kick mechanism. None of the 5 currently featured Whiteboard plays are corners, so we have no labelled example to validate against AW-JOI yet. Future work: select a corner clip per team that uses this routine (Arsenal's Jover-era for *meat wall* is the canonical out-of-tournament reference; for WC '22 candidates, England's near-post deliveries and Spain's short-corner routines are the leading targets).

### Positional Rotations

**No labelled example in the current 5 featured clips.** The Whiteboard candidates ranker did not surface a top-7 move tagged with this mechanism for any of these plays. Not a negative result — just absent coverage.

### Rest-Defense Anchoring

**Chemistry-positive in the data.** 1 labelled example(s); 1/1 with in-window AW-JOI exceeding clip baseline. Mean in-window AW-JOI 1.14e-04 vs baseline 7.32e-05.
- *netherlands-usa-memphis* — Virgil van Dijk → Jurrien Timber: in-window 1.14e-04, baseline 7.32e-05 (1.55×).

### Short-Corner Overload

**Coming soon.** This is a corner-kick mechanism. None of the 5 currently featured Whiteboard plays are corners, so we have no labelled example to validate against AW-JOI yet. Future work: select a corner clip per team that uses this routine (Arsenal's Jover-era for *meat wall* is the canonical out-of-tournament reference; for WC '22 candidates, England's near-post deliveries and Spain's short-corner routines are the leading targets).

### The Blind Pass / Scan-and-Release

**Chemistry-positive in the data.** 1 labelled example(s); 1/1 with in-window AW-JOI exceeding clip baseline. Mean in-window AW-JOI 2.28e-04 vs baseline 2.34e-05.
- *netherlands-usa-memphis* — Cody Gakpo → Memphis Depay: in-window 2.28e-04, baseline 2.34e-05 (9.76×).

### The Decoy Run

**Chemistry-positive in the data.** 4 labelled example(s); 3/4 with in-window AW-JOI exceeding clip baseline. Mean in-window AW-JOI 9.09e-05 vs baseline 6.80e-05.
- *argentina-france-di-maria* — Nicolas Tagliafico → Alexis Mac Allister: in-window 7.04e-05, baseline 5.36e-05 (1.31×).
- *argentina-france-mbappe-volley* — Raphael Varane → Dayot Upamecano: in-window 1.23e-04, baseline 7.30e-05 (1.69×).
- *japan-spain-doan* — Alvaro Morata → Dani Olmo: in-window 3.25e-05, baseline 1.12e-04 (0.29×).
- *argentina-croatia-julian* — Nicolas Tagliafico → Nahuel Molina: in-window 1.38e-04, baseline 3.32e-05 (4.15×).

### The Meat Wall

**Coming soon.** This is a corner-kick mechanism. None of the 5 currently featured Whiteboard plays are corners, so we have no labelled example to validate against AW-JOI yet. Future work: select a corner clip per team that uses this routine (Arsenal's Jover-era for *meat wall* is the canonical out-of-tournament reference; for WC '22 candidates, England's near-post deliveries and Spain's short-corner routines are the leading targets).

### The Overlap / Underlap Handoff

**No labelled example in the current 5 featured clips.** The Whiteboard candidates ranker did not surface a top-7 move tagged with this mechanism for any of these plays. Not a negative result — just absent coverage.

### The Pin (Fixing the Defender)

**Chemistry-positive in the data.** 3 labelled example(s); 3/3 with in-window AW-JOI exceeding clip baseline. Mean in-window AW-JOI 1.17e-04 vs baseline 4.34e-05.
- *argentina-france-di-maria* — Nicolas Tagliafico → Cristian Romero: in-window 1.44e-04, baseline 4.63e-05 (3.10×).
- *argentina-france-mbappe-volley* — Dayot Upamecano → Kylian Mbappé: in-window 7.51e-05, baseline 4.88e-05 (1.54×).
- *argentina-croatia-julian* — Nicolas Tagliafico → Nahuel Molina: in-window 1.32e-04, baseline 3.52e-05 (3.74×).

### The Press Trap (De Zerbi Bait)

**No labelled example in the current 5 featured clips.** The Whiteboard candidates ranker did not surface a top-7 move tagged with this mechanism for any of these plays. Not a negative result — just absent coverage.

### The Third-Man Triangle

**Chemistry-positive in the data.** 4 labelled example(s); 3/4 with in-window AW-JOI exceeding clip baseline. Mean in-window AW-JOI 7.77e-05 vs baseline 4.89e-05.
- *argentina-france-di-maria* — Nahuel Molina → Alexis Mac Allister: in-window 7.04e-05, baseline 7.27e-05 (0.97×).
- *argentina-france-di-maria* — Julian Alvarez → Lionel Messi: in-window 4.94e-05, baseline 4.36e-05 (1.13×).
- *netherlands-usa-memphis* — Memphis Depay → Jurrien Timber: in-window 1.07e-04, baseline 5.12e-05 (2.09×).
- *netherlands-usa-memphis* — Frenkie de Jong → Jurrien Timber: in-window 8.37e-05, baseline 2.79e-05 (3.00×).

## Caveats

- Sample size is tiny: 5 clips, 13 mechanism-tagged moves. This is a *structure check* — does the metric move in the expected direction on labelled examples? — not a population-level effect.
- The baseline (rest of the clip) includes both build-up frames and dead-ball frames; some clips have very low overall p_score volatility, which inflates lift ratios when the in-window contains the only meaningful ΔP_score spike.
- The partner is chosen *post-hoc* as the highest-coupled same-team teammate in the window, which biases toward finding non-zero in-window AW-JOI. The interesting comparison is in-window vs the same pair's baseline across the same clip — that is what the lift column reports.
- Corner-kick mechanisms cannot be validated until a corner clip is featured.
