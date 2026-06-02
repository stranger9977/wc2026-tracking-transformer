import numpy as np
import pandas as pd
from xg.site_data import build_team_xg_table, residualize


def test_residualize_removes_linear_control():
    # y = 2*c exactly; residual on [c] must be ~0
    frame = pd.DataFrame({"c": [1.0, 2.0, 3.0, 4.0], "y": [2.0, 4.0, 6.0, 8.0]})
    r = residualize(frame, "y", ["c"])
    assert np.allclose(r.to_numpy(), 0.0, atol=1e-9)
    assert list(r.index) == [0, 1, 2, 3]


def test_residualize_drops_rows_missing_control_or_col():
    frame = pd.DataFrame({"c": [1.0, np.nan, 3.0], "y": [1.0, 2.0, np.nan]})
    r = residualize(frame, "y", ["c"])
    assert list(r.index) == [0]  # rows 1 (missing c) and 2 (missing y) dropped


def test_build_team_xg_table_shapes(tmp_path):
    # two teams, one game -> opponent FIFA is the other team's overall
    pq = tmp_path / "tm.parquet"
    pd.DataFrame({
        "game_id": [1, 1], "team_id": ["A", "B"], "team_name": ["Aland", "Bland"],
        "sb_xg_for": [1.5, 0.5], "sb_xg_against": [0.5, 1.5],
        "goals_for": [1, 0], "goals_against": [0, 1],
        "model_xg_for_peak": [0.1, 0.1], "model_xg_against_peak": [0.1, 0.1],
        "model_xg_for_sum": [0.1, 0.1], "model_xg_against_sum": [0.1, 0.1],
        "model_xg_for_integral": [0.1, 0.1], "model_xg_against_integral": [0.1, 0.1],
    }).to_parquet(pq)
    cj = tmp_path / "chem.json"
    cj.write_text(pd.DataFrame({
        "team_id": ["A", "B"], "team_name": ["Aland", "Bland"],
        "overall": [80, 70], "mean_caps": [40, 30],
        "n_strong_def": [10, 4], "mean_aw_joi90_all": [0.3, 0.2], "stage_int": [8, 2],
    }).to_json(orient="records"))
    t = build_team_xg_table(str(pq), str(cj))
    assert set(t["team_id"]) == {"A", "B"}
    a = t.set_index("team_id").loc["A"]
    assert a["games"] == 1 and abs(a["xga_pm"] - 0.5) < 1e-9
    assert a["opp_fifa"] == 70 and bool(a["is_semifinalist"]) is True
    assert bool(t.set_index("team_id").loc["B"]["is_semifinalist"]) is False
