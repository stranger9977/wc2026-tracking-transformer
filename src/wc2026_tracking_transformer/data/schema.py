"""Soccer-specific token schema for the tracking transformer.

This is the soccer analogue of Sumer's NFL token spec
(`src/datasets.py::BDB2024_Dataset.transformer_transform_input_frame_df` in
the upstream repo). Architectural credit: SumerSports/SportsTrackingTransformer.
We define our own per-player feature set because soccer has different field
dimensions, player counts, and roles than NFL.

Key differences from NFL:
    * 22 outfield players + 2 goalkeepers + 1 ball  vs. 22 NFL players
      (NFL excluded the football; we include the ball as its own token because
       possession transitions are central to soccer tasks).
    * Pitch dimensions ~105 x 68 m (FIFA standard), versus 120 x 53.3 yards.
    * No analogue to "ball carrier" — replaced with `has_possession` flag for
      the player closest to the ball when in possession.
    * Role encoding is line-based (GK / DEF / MID / FWD) rather than O/D side.
"""

from dataclasses import dataclass

# Standard soccer matches have 11 players per side. We tokenize 22 outfield
# players + ball, with goalkeepers flagged via `is_goalkeeper`. Substitutions
# happen at the match level; per-frame the count is fixed at 22 + 1 ball.
NUM_PLAYERS_PER_SIDE = 11
NUM_PLAYERS_PER_FRAME = 22  # excludes ball
NUM_TOKENS_PER_FRAME = NUM_PLAYERS_PER_FRAME + 1  # +1 ball token

# Pitch dimensions in meters (FIFA / IFAB standard, World Cup conformant).
PITCH_LENGTH_M = 105.0
PITCH_WIDTH_M = 68.0

# Per-player feature vector. Mirrors the spirit of Sumer's 6-feature NFL spec
# (x_rel, y_rel, vx, vy, side, is_ball_carrier) but soccer-adapted.
#
# Coordinate convention: x along the long axis, y along the short axis, origin
# at pitch center. Positions normalized to attacking-left-to-right so the
# attacking team always moves +x. kloppy gives us this for free if we set the
# orientation flag at load time.
FRAME_FEATURE_COLUMNS: tuple[str, ...] = (
    "x_norm",            # position x normalized to [-1, 1] over PITCH_LENGTH_M
    "y_norm",            # position y normalized to [-1, 1] over PITCH_WIDTH_M
    "vx",                # velocity x in m/s
    "vy",                # velocity y in m/s
    "is_attacking_side", # +1 if player is on the team currently in possession, else -1
    "is_goalkeeper",     # 1 if GK, else 0
    "has_possession",    # 1 if this player is the nearest in-possession player to the ball, else 0
)

# Ball token has the same shape with most flags zeroed — see `pff_loader.py`.


@dataclass(frozen=True, slots=True)
class TrackingFrame:
    """A single tracking frame, normalized to model input shape.

    Attributes:
        match_id: PFF match identifier.
        period: 1 (first half), 2 (second half), 3/4 (ET), 5 (PK shootout — discarded).
        frame_id: Monotonic frame counter within the match.
        timestamp_ms: Milliseconds since kick-off (per period).
        players: Array of shape (NUM_PLAYERS_PER_FRAME, len(FRAME_FEATURE_COLUMNS)).
        ball: Array of shape (len(FRAME_FEATURE_COLUMNS),) — optional, may be None
              if the ball is off-frame / occluded.
        in_possession_team_id: PFF team id currently with possession (or None
              if contested / out of play).
    """

    match_id: str
    period: int
    frame_id: int
    timestamp_ms: int
    players: "object"  # np.ndarray; left as object to avoid numpy import in this header
    ball: "object | None"
    in_possession_team_id: str | None
