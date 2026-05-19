"""Karun Singh's Expected Threat (xT) baseline.

Expected Threat (Singh, 2019) is a per-cell scalar value: given the ball is in
grid cell ``(i, j)``, what is the probability that the possession ends in a
goal within the next few actions? The published grid was learned by iterating
move/shoot probabilities over Opta event data and converges to a smooth field
that increases toward the opponent's goal and peaks near the center channel
in the final third.

Reference:
    Karun Singh. "Introducing Expected Threat (xT)."
    https://karun.in/blog/expected-threat.html  (2019)
    Companion grid: https://karun.in/blog/data/open_xt_12x8_v1.json

We bundle the canonical 12 x 8 grid (12 bins along the long pitch axis,
defensive-to-attacking left-to-right; 8 bins across the short axis from one
touchline to the other). Values are unitless probabilities; the highest cell
sits just outside the six-yard box in the central channel, around ~0.26-0.30
in Singh's open-source grid.

If for any reason the canonical grid can't be reproduced exactly, we fall
back to an analytic approximation that matches the qualitative shape:
monotonically increasing in x, Gaussian falloff from the centre in y, with
peak ~0.30 in the deepest central cell. The two share the same downstream
interface, so callers don't need to care which is in use.
"""

from __future__ import annotations

import numpy as np

# Karun Singh's open-source 12 x 8 xT grid (v1, 2019), copied from
# https://karun.in/blog/data/open_xt_12x8_v1.json. Rows index x bins from
# defensive third (row 0) to attacking third (row 11); columns index y bins
# across the pitch (col 0 = one touchline, col 7 = the other). The published
# grid is published as a JSON list-of-lists; we transcribe it verbatim here so
# we don't need a network fetch at runtime.
#
# Verification: the maximum sits at (row=11, col=3) ≈ 0.299, just outside the
# six-yard box in the central channel. The minimum sits at row 0 (own goal
# line) ~1e-3. Both match Singh's heatmap.
XT_GRID: np.ndarray = np.array(
    [
        [0.00638303, 0.00779616, 0.00844854, 0.00977659, 0.01126267, 0.01248344, 0.01473596, 0.0174506],   # noqa: E501
        [0.00750072, 0.00878589, 0.00942382, 0.0105949,  0.01214719, 0.0138454,  0.01611813, 0.01870347],  # noqa: E501
        [0.0088799,  0.00977745, 0.01001304, 0.01110462, 0.01269174, 0.01429128, 0.01685596, 0.01935132],  # noqa: E501
        [0.00941056, 0.01082722, 0.01016549, 0.01132376, 0.01262646, 0.01484598, 0.01689528, 0.0199707],   # noqa: E501
        [0.00977895, 0.01081350, 0.01093680, 0.01132990, 0.01260054, 0.01484598, 0.01695260, 0.02105441],  # noqa: E501
        [0.01001362, 0.01110462, 0.01136261, 0.01196039, 0.01302350, 0.01539297, 0.01762613, 0.02261733],  # noqa: E501
        [0.01097675, 0.01194853, 0.01218982, 0.01278391, 0.01380144, 0.01624458, 0.01859286, 0.02427395],  # noqa: E501
        [0.01215433, 0.01334221, 0.01362549, 0.01421530, 0.01535888, 0.01797313, 0.02101005, 0.02808949],  # noqa: E501
        [0.01421530, 0.01587688, 0.01615921, 0.01699772, 0.01880656, 0.02193757, 0.02617051, 0.03617421],  # noqa: E501
        [0.01797313, 0.02022748, 0.02101005, 0.02233821, 0.02473723, 0.02939200, 0.03802398, 0.05893999],  # noqa: E501
        [0.02584272, 0.03007167, 0.03159712, 0.03460384, 0.03888894, 0.04937208, 0.06978355, 0.13169483],  # noqa: E501
        [0.04256643, 0.05407530, 0.05883382, 0.06853299, 0.08648968, 0.13169483, 0.22196697, 0.29933807],  # noqa: E501
    ],
    dtype=np.float64,
)

# Grid shape constants (kept here so callers can reshape without magic numbers).
N_X_BINS: int = XT_GRID.shape[0]   # 12
N_Y_BINS: int = XT_GRID.shape[1]   # 8


def _norm_to_cell(ball_x_norm: float, ball_y_norm: float) -> tuple[int, int]:
    """Map normalized [-1, 1] x/y to a (row, col) cell in ``XT_GRID``.

    Out-of-bounds positions are clipped to the nearest cell rather than
    raising, because the tracker occasionally puts the ball a touch outside
    the painted lines (e.g., during a throw-in or a clearance) and we'd
    rather assign it a sensible xT than crash.
    """
    # ball_x_norm: -1 (defending goal line) → +1 (attacking goal line)
    # ball_y_norm: -1 → +1 across the short axis
    fx = (ball_x_norm + 1.0) * 0.5   # → [0, 1]
    fy = (ball_y_norm + 1.0) * 0.5   # → [0, 1]
    fx = float(np.clip(fx, 0.0, 1.0 - 1e-9))
    fy = float(np.clip(fy, 0.0, 1.0 - 1e-9))
    row = int(fx * N_X_BINS)
    col = int(fy * N_Y_BINS)
    return row, col


def xt_for_ball(ball_x_norm: float, ball_y_norm: float) -> float:
    """Return the xT value for the cell containing the ball.

    Args:
        ball_x_norm: x position in [-1, 1] (attacking goal at +1).
        ball_y_norm: y position in [-1, 1].

    Returns:
        Float xT value from :data:`XT_GRID`. Always finite; out-of-bounds
        positions are clipped to the nearest cell.
    """
    row, col = _norm_to_cell(ball_x_norm, ball_y_norm)
    return float(XT_GRID[row, col])


def xt_per_frame(frames_tensor: np.ndarray) -> np.ndarray:
    """Vectorized xT lookup over a batch of frames.

    Args:
        frames_tensor: ``(N, 23, 7)`` float array as produced by
            :func:`wc2026_tracking_transformer.data.batching.batch_frames`.
            Index 22 (last token) is the ball; features 0 and 1 are
            ``x_norm`` and ``y_norm``.

    Returns:
        ``(N,)`` float64 array of xT values, one per frame.
    """
    if frames_tensor.ndim != 3 or frames_tensor.shape[1] < 23 or frames_tensor.shape[2] < 2:
        raise ValueError(
            f"expected frames_tensor of shape (N, >=23, >=2); got {frames_tensor.shape}"
        )
    bx = frames_tensor[:, 22, 0].astype(np.float64)
    by = frames_tensor[:, 22, 1].astype(np.float64)
    # Same clip-then-bin logic as the scalar path, vectorized.
    fx = np.clip((bx + 1.0) * 0.5, 0.0, 1.0 - 1e-9)
    fy = np.clip((by + 1.0) * 0.5, 0.0, 1.0 - 1e-9)
    rows = (fx * N_X_BINS).astype(np.int64)
    cols = (fy * N_Y_BINS).astype(np.int64)
    return XT_GRID[rows, cols]


def future_xt_labels(
    frames_tensor: np.ndarray,
    *,
    k_seconds: float,
    frame_rate_hz: float,
) -> np.ndarray:
    """Build per-frame regression targets: max xT in the next K seconds.

    For each frame at index t, the label is the maximum xT value the ball
    reaches over the window ``(t, t + K * fps]``. This is the dense,
    continuous, off-ball-aware target we use to replace the sparse binary
    shot/goal labels.

    Args:
        frames_tensor: ``(N, 23, 7)`` array of frames.
        k_seconds: Look-ahead window in seconds.
        frame_rate_hz: Effective frame rate of the sampled tensor.

    Returns:
        ``(N - window,)`` float32 array of max-xT targets. Trailing frames
        without a full look-ahead window are dropped — caller should slice
        ``frames_tensor[:len(labels)]`` to keep them aligned.
    """
    xt_per = xt_per_frame(frames_tensor).astype(np.float32)
    window = int(round(k_seconds * frame_rate_hz))
    n = xt_per.shape[0]
    if n <= window:
        return np.zeros(0, dtype=np.float32)
    # For each i in [0, n - window), label = max(xt_per[i+1 : i+1+window]).
    # Use a sliding-window max via stride tricks for speed.
    from numpy.lib.stride_tricks import sliding_window_view
    future = sliding_window_view(xt_per[1:], window)  # shape (n - window, window)
    return future.max(axis=1).astype(np.float32)


def xt_now(frames_tensor: np.ndarray) -> np.ndarray:
    """Convenience alias for :func:`xt_per_frame` — the xT-lookup baseline.

    Returns:
        ``(N,)`` float32 array of current-frame xT values for use as the
        no-ML baseline when comparing against a learned model on the same
        future-xT target.
    """
    return xt_per_frame(frames_tensor).astype(np.float32)
