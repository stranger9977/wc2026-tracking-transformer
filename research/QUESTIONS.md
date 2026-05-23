# Running questions / things to validate

Things I notice while building that don't quite make sense, or that the user should
weigh in on. Each is a stand-alone item with the file/line it lives at.

## Open

1. **xT-regression vs VAEP target.** Tracking transformer currently predicts
   `max(xT) in next K seconds`, which is forward-looking by construction. For
   frame-by-frame chemistry we'd want the credit-assignment target to either be
   the *delta* in expected goal probability between consecutive frames, or a
   short-horizon VAEP equivalent. Need to decide which.

2. **VAEP look-ahead window.** `vaep/features.py::LOOK_AHEAD = 10` actions.
   Decroos used 10 but with full league data; for a 64-match tournament that's
   probably long enough to be noisy. Worth ablating to 5 or to "next-shot" once
   we have club data to combine with.

3. **PFF set-piece handling.** Corners, free-kicks, throw-ins all currently get
   VAEP credit via the same model. The paper kept them in. But the per-pair
   "goals together" count gives a lot of weight to set-piece scorers
   (Lewandowski, Cristiano on penalties). Worth a separate column?

4. **Player matching across data sources.** PFF uses integer player_ids. StatsBomb
   uses different ids. Going to need a name-based join with manual override for
   diacritics / nicknames. Track confidence per match.

5. **xT pre-2022 grid stability.** Karun's xT grid was published from EPL 2015-16.
   Applying it to WC22 (different competition, different style) introduces some
   bias. Worth flagging on the methodology page.

6. **Per-pair "goals together" definition.** Currently any same-team buildup
   pair within 5 actions of a goal gets a +1. That can double-count: a goal
   with both a sequence of 5 same-team passes ends up crediting C(5, 2) = 10
   pairs. Consider weighting by number of touches each player had in the
   buildup, or restricting to assist + scorer + previous passer.

## Resolved

(none yet)
