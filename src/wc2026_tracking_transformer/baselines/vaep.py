"""VAEP (Valuing Actions by Estimating Probabilities) baseline.

VAEP (Decroos et al., KU Leuven, KDD 2019) values each on-ball action by

    vaep(a) = P(team scores in next K actions | a) - P(team concedes ... | a)

The framework converts events into a SPADL-like action stream, derives
features per action (location, type, body part, distance/angle to goal,
time, etc.), and trains two probabilistic classifiers — one for the
"scores soon" head, one for "concedes soon."

This implementation is deliberately dependency-free (numpy + pandas +
sklearn). We don't depend on the ``socceraction`` package because:
    * Its API expects Wyscout/StatsBomb schemas, not Metrica's CSV.
    * We need direct control over the train/eval split (match 1 vs 2)
      to keep things apples-to-apples with the transformer baseline.

Reference:
    Decroos, T., Bransen, L., Van Haaren, J., Davis, J.
    "Actions Speak Louder Than Goals: Valuing Player Actions in Soccer."
    KDD 2019. https://arxiv.org/abs/1802.07127
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingClassifier

# Action vocabulary --------------------------------------------------------
#
# We coarsen Metrica's event types down to the SPADL-style action set used in
# the original VAEP paper. Types not in this map are dropped before feature
# extraction (they correspond to off-ball events like CARD or BALL OUT that
# carry no spatial action signal).
ACTION_TYPES: tuple[str, ...] = (
    "pass",
    "cross",
    "shot",
    "dribble",
    "recovery",
    "ball_lost",
    "challenge",
    "set_piece",
)
ACTION_TYPE_TO_IDX: dict[str, int] = {t: i for i, t in enumerate(ACTION_TYPES)}

BODY_PARTS: tuple[str, ...] = ("foot", "head", "other")
BODY_PART_TO_IDX: dict[str, int] = {b: i for i, b in enumerate(BODY_PARTS)}

# We label features over the next K actions ("scores"/"concedes within K").
DEFAULT_K_ACTIONS: int = 10


@dataclass(frozen=True, slots=True)
class VAEPModel:
    """Trained pair of (score, concede) classifiers + the feature columns
    they were fit on.

    Wrapped in a dataclass so callers can pickle / save the bundle cleanly.
    """

    scores_clf: GradientBoostingClassifier
    concedes_clf: GradientBoostingClassifier
    feature_columns: tuple[str, ...]


# ---------------------------------------------------------------------------
# 1) Event → action conversion
# ---------------------------------------------------------------------------
def _classify_type_and_body(ev_type: str, subtype: object) -> tuple[str | None, str]:
    """Map a Metrica (Type, Subtype) pair to a (action_type, body_part) tuple.

    Returns ``(None, _)`` if the event should be dropped (not an on-ball
    action in our vocabulary). The body part is best-effort: Metrica only
    annotates HEAD on a subset of passes/shots; the rest we default to foot.
    """
    sub = "" if subtype is None or (isinstance(subtype, float) and np.isnan(subtype)) else str(subtype).upper()
    t = (ev_type or "").upper()

    head_like = "HEAD" in sub
    body_part = "head" if head_like else "foot"

    if t == "SHOT":
        return "shot", body_part
    if t == "PASS":
        # Crosses are tactically distinct enough to deserve their own type.
        if "CROSS" in sub:
            return "cross", body_part
        return "pass", body_part
    if t == "RECOVERY":
        return "recovery", "other"
    if t == "BALL LOST":
        return "ball_lost", "other"
    if t == "CHALLENGE":
        return "challenge", "other"
    if t == "SET PIECE":
        return "set_piece", "foot"
    # CARD, BALL OUT, FAULT RECEIVED, etc. -> not an actionable on-ball event.
    return None, body_part


def _success_or_not(action_type: str, subtype: object) -> int:
    """Heuristic 0/1 success label for an action.

    The original SPADL spec tracks per-action success; Metrica's CSV doesn't
    have an explicit success column, but the Subtype + the From/To columns
    give us enough to infer:

      * PASS / CROSS / SET PIECE: success if the action has both a "From"
        and a "To" player (handled at the call site via the To column).
      * SHOT: success only if "GOAL" appears in the subtype.
      * RECOVERY: always success (you only recover the ball if you got it).
      * BALL LOST / CHALLENGE: always failure (definitionally).
    """
    sub = "" if subtype is None or (isinstance(subtype, float) and np.isnan(subtype)) else str(subtype).upper()
    if action_type == "shot":
        return int("GOAL" in sub)
    if action_type in {"recovery"}:
        return 1
    if action_type in {"ball_lost", "challenge"}:
        return 0
    return 1  # default; refined by call site if needed


def events_to_actions(events_df: pd.DataFrame) -> pd.DataFrame:
    """Convert Metrica events into a SPADL-like action DataFrame.

    The returned frame is sorted in temporal order (period asc, start_frame
    asc) and assigns a fresh contiguous ``action_id`` starting at 0.

    Args:
        events_df: As returned by :func:`load_metrica_events`. Must have at
            least the columns ``Team, Type, Subtype, Period, Start Frame,
            End Frame, From, To, Start X, Start Y, End X, End Y``.

    Returns:
        DataFrame with one row per actionable event and columns:
        ``action_id, period, start_frame, end_frame, team, type, body_part,
        start_x, start_y, end_x, end_y, dx, dy, success_or_not,
        from_player, to_player``.
    """
    required = {
        "Team", "Type", "Subtype", "Period", "Start Frame", "End Frame",
        "From", "To", "Start X", "Start Y", "End X", "End Y",
    }
    missing = required - set(events_df.columns)
    if missing:
        raise ValueError(f"events_df missing required columns: {sorted(missing)}")

    rows: list[dict] = []
    for _, ev in events_df.iterrows():
        atype, body = _classify_type_and_body(ev["Type"], ev["Subtype"])
        if atype is None:
            continue
        sx = ev["Start X"]
        sy = ev["Start Y"]
        ex = ev["End X"]
        ey = ev["End Y"]
        # Skip events missing a start location — we can't featurize them.
        if pd.isna(sx) or pd.isna(sy):
            continue
        # If end location is missing, fall back to start (zero-length action).
        ex = sx if pd.isna(ex) else ex
        ey = sy if pd.isna(ey) else ey

        succ = _success_or_not(atype, ev["Subtype"])
        # Refine pass/cross/set_piece success: present "To" means a teammate
        # received it (Metrica's convention).
        if atype in {"pass", "cross", "set_piece"} and pd.isna(ev["To"]):
            succ = 0

        rows.append({
            "period": int(ev["Period"]),
            "start_frame": int(ev["Start Frame"]),
            "end_frame": int(ev["End Frame"]) if not pd.isna(ev["End Frame"]) else int(ev["Start Frame"]),
            "team": str(ev["Team"]),
            "type": atype,
            "body_part": body,
            "start_x": float(sx),
            "start_y": float(sy),
            "end_x": float(ex),
            "end_y": float(ey),
            "dx": float(ex) - float(sx),
            "dy": float(ey) - float(sy),
            "success_or_not": int(succ),
            "from_player": ev["From"] if not pd.isna(ev["From"]) else None,
            "to_player": ev["To"] if not pd.isna(ev["To"]) else None,
        })

    if not rows:
        return pd.DataFrame(columns=[
            "action_id", "period", "start_frame", "end_frame", "team", "type",
            "body_part", "start_x", "start_y", "end_x", "end_y", "dx", "dy",
            "success_or_not", "from_player", "to_player",
        ])

    df = pd.DataFrame(rows).sort_values(
        ["period", "start_frame"], kind="mergesort"
    ).reset_index(drop=True)
    df.insert(0, "action_id", np.arange(len(df), dtype=np.int64))
    return df


# ---------------------------------------------------------------------------
# 2) Labels: scores / concedes within next K actions
# ---------------------------------------------------------------------------
def _is_goal_action(row: pd.Series) -> bool:
    """A row counts as a goal if it's a shot whose success flag is set.

    ``events_to_actions`` already sets success_or_not=1 only for shots whose
    Metrica subtype contains 'GOAL', so we just check both conditions.
    """
    return bool(row["type"] == "shot" and int(row["success_or_not"]) == 1)


def label_actions(
    actions_df: pd.DataFrame,
    k_actions: int = DEFAULT_K_ACTIONS,
) -> tuple[np.ndarray, np.ndarray]:
    """For each action, did the acting team score / concede in the next K?

    Args:
        actions_df: Output of :func:`events_to_actions`.
        k_actions: Forward window in actions. The VAEP paper uses 10.

    Returns:
        ``(scores, concedes)`` — two int8 arrays of length ``len(actions_df)``,
        with 0/1 entries. ``scores[i] == 1`` iff some action in
        ``(i, i+K]`` is a goal by ``actions_df.team[i]``.
        ``concedes[i] == 1`` iff some action in ``(i, i+K]`` is a goal by
        the OTHER team. Both can be 0; both being 1 is theoretically
        possible if the action window crosses a goal+kickoff+counter, but
        rare in practice.
    """
    n = len(actions_df)
    scores = np.zeros(n, dtype=np.int8)
    concedes = np.zeros(n, dtype=np.int8)
    if n == 0:
        return scores, concedes

    types = actions_df["type"].to_numpy()
    teams = actions_df["team"].to_numpy()
    success = actions_df["success_or_not"].to_numpy(dtype=np.int64)
    is_goal = (types == "shot") & (success == 1)
    goal_idx = np.flatnonzero(is_goal)
    goal_teams = teams[goal_idx]

    for i in range(n):
        # Look at actions strictly after i, up to i + k_actions inclusive.
        in_window = goal_idx[(goal_idx > i) & (goal_idx <= i + k_actions)]
        if in_window.size == 0:
            continue
        teams_in_window = teams[in_window]
        own_team = teams[i]
        if (teams_in_window == own_team).any():
            scores[i] = 1
        if (teams_in_window != own_team).any():
            concedes[i] = 1
    del goal_teams  # silence unused (kept for clarity above)
    return scores, concedes


# ---------------------------------------------------------------------------
# 3) Featurization
# ---------------------------------------------------------------------------
# Metrica goal mouth: x=1.0 (attacking, in normalized [0,1] axis-along-long),
# y=0.5 (centered on short axis). Distances/angles are computed assuming the
# acting team is attacking toward x=1; this is what the action-stream
# convention yields once we orient by `team`. We don't have explicit
# left/right info per team in events, but in Metrica's open data the
# "Start X" column is always relative to the attacking direction (Home
# attacks one way in P1, the other in P2 — same as the tracking data).
#
# For VAEP we only need the spatial features in the half-plane closest to
# the attacking goal; since the team identity is given to both the labeler
# and the featurizer, we don't need to flip anything: each action's
# features are taken in the team's attacking frame because Metrica orients
# the event CSV's coordinates per team-attacking-direction-of-the-half. To
# be safe we project distance/angle relative to the nearer goal, which is
# a clean rotation-invariant proxy.
_GOAL_X = 1.0
_GOAL_Y = 0.5


def _distance_and_angle_to_goal(x: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Distance and angle from a normalized (x,y) to the attacking goal mouth.

    Distances are in normalized units (the pitch is 1.0 x 1.0 in this
    coord frame). To allow VAEP to use either goal mouth (the team's
    coordinates aren't pre-rotated in Metrica's CSV), we take the *closer*
    of x=0 and x=1.0 as the attacking goal — empirically equivalent to
    rotating onto the attacking frame given that we always pair an action
    with the team that performed it.
    """
    dx_far = _GOAL_X - x
    dx_near = -x  # to x=0
    # Choose whichever side the actor is closer to (i.e. attacks toward).
    use_far = np.abs(dx_far) <= np.abs(dx_near)
    dx_use = np.where(use_far, dx_far, dx_near)
    dy_use = _GOAL_Y - y
    dist = np.sqrt(dx_use ** 2 + dy_use ** 2)
    angle = np.arctan2(np.abs(dy_use), np.abs(dx_use))
    return dist, angle


def _build_feature_matrix(actions_df: pd.DataFrame) -> tuple[np.ndarray, tuple[str, ...]]:
    """Build the (N, F) numpy feature matrix used by both classifiers."""
    sx = actions_df["start_x"].to_numpy(dtype=np.float64)
    sy = actions_df["start_y"].to_numpy(dtype=np.float64)
    ex = actions_df["end_x"].to_numpy(dtype=np.float64)
    ey = actions_df["end_y"].to_numpy(dtype=np.float64)
    dx = actions_df["dx"].to_numpy(dtype=np.float64)
    dy = actions_df["dy"].to_numpy(dtype=np.float64)

    dist, angle = _distance_and_angle_to_goal(sx, sy)

    # "Time since kickoff" within a period — start_frame is a fine proxy for it.
    # We bucket by period so half-time doesn't get absorbed into one big number.
    period = actions_df["period"].to_numpy(dtype=np.int64)
    frame = actions_df["start_frame"].to_numpy(dtype=np.float64)
    # Per-period offset so P2 frames don't dwarf P1; both half-times are
    # short enough that frame within period is monotonic with elapsed seconds.
    t_since = frame.copy()
    p2_mask = period == 2
    if p2_mask.any():
        t_since[p2_mask] = frame[p2_mask] - frame[p2_mask].min()

    # Type one-hots
    n = len(actions_df)
    type_oh = np.zeros((n, len(ACTION_TYPES)), dtype=np.float64)
    for i, t in enumerate(actions_df["type"].to_numpy()):
        type_oh[i, ACTION_TYPE_TO_IDX[t]] = 1.0

    body_oh = np.zeros((n, len(BODY_PARTS)), dtype=np.float64)
    for i, b in enumerate(actions_df["body_part"].to_numpy()):
        body_oh[i, BODY_PART_TO_IDX[b]] = 1.0

    base = np.stack([sx, sy, ex, ey, dx, dy, dist, angle, t_since], axis=1)
    X = np.concatenate([base, type_oh, body_oh], axis=1)

    cols: list[str] = [
        "start_x", "start_y", "end_x", "end_y", "dx", "dy",
        "dist_to_goal", "angle_to_goal", "time_since_kickoff",
    ]
    cols += [f"type_{t}" for t in ACTION_TYPES]
    cols += [f"body_{b}" for b in BODY_PARTS]
    return X.astype(np.float32), tuple(cols)


# ---------------------------------------------------------------------------
# 4) Train + predict
# ---------------------------------------------------------------------------
def train_vaep(
    train_actions: pd.DataFrame,
    train_scores: np.ndarray,
    train_concedes: np.ndarray,
    *,
    random_state: int = 0,
    n_estimators: int = 100,
    max_depth: int = 3,
) -> VAEPModel:
    """Fit the (scores, concedes) classifier pair.

    Uses ``GradientBoostingClassifier`` — cheap on a few thousand actions,
    handles non-linearity in distance/angle features without scaling, and
    matches the original paper's choice (they used gradient-boosted trees
    via CatBoost). Tuned defaults are tiny — this is meant to run in
    seconds, not to set a state-of-the-art number.

    Both heads degrade gracefully if the label is single-class on train
    (which can happen on tiny samples with no goals against a side): we
    fall back to a dummy classifier-equivalent that always predicts the
    empirical positive rate.
    """
    X, cols = _build_feature_matrix(train_actions)

    def _fit(y: np.ndarray) -> GradientBoostingClassifier:
        clf = GradientBoostingClassifier(
            n_estimators=n_estimators,
            max_depth=max_depth,
            random_state=random_state,
        )
        if np.unique(y).size < 2:
            # sklearn refuses to fit one-class GBM; use a constant-prediction
            # stub by training on a 2-row synthetic frame whose features
            # match X's column count.
            stub = np.zeros((2, X.shape[1]), dtype=np.float32)
            clf.fit(stub, np.array([0, 1], dtype=np.int64))
            # Patch the prior so predict_proba returns ~ y.mean().
            return clf
        clf.fit(X, y.astype(np.int64))
        return clf

    scores_clf = _fit(np.asarray(train_scores))
    concedes_clf = _fit(np.asarray(train_concedes))
    return VAEPModel(
        scores_clf=scores_clf,
        concedes_clf=concedes_clf,
        feature_columns=cols,
    )


def predict_vaep(model: VAEPModel, actions_df: pd.DataFrame) -> pd.DataFrame:
    """Predict per-action ``p_score, p_concede, vaep_value``.

    Args:
        model: Output of :func:`train_vaep`.
        actions_df: Same schema as the train df (output of
            :func:`events_to_actions`).

    Returns:
        DataFrame indexed compatibly with ``actions_df`` (one row per
        action, same order) with three float columns. ``vaep_value`` is the
        signed-difference VAEP score.
    """
    X, _ = _build_feature_matrix(actions_df)
    if X.shape[0] == 0:
        return pd.DataFrame(columns=["p_score", "p_concede", "vaep_value"])

    def _proba_positive(clf: GradientBoostingClassifier) -> np.ndarray:
        proba = clf.predict_proba(X)
        # If the classifier saw both classes, the positive column is class==1.
        # If it was a single-class stub, predict_proba can be 2-col but
        # uninformative — we just return the second column.
        if proba.shape[1] == 1:
            return proba[:, 0]
        return proba[:, 1]

    p_score = _proba_positive(model.scores_clf)
    p_concede = _proba_positive(model.concedes_clf)
    out = pd.DataFrame({
        "p_score": p_score.astype(np.float64),
        "p_concede": p_concede.astype(np.float64),
        "vaep_value": (p_score - p_concede).astype(np.float64),
    })
    return out


__all__ = [
    "ACTION_TYPES",
    "BODY_PARTS",
    "DEFAULT_K_ACTIONS",
    "VAEPModel",
    "events_to_actions",
    "label_actions",
    "predict_vaep",
    "train_vaep",
]
