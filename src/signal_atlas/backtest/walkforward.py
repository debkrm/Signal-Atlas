"""
walkforward.py - Walk-Forward Evaluation & Parameter Grid Tuning Protocol.

Executes Phase 6 of backtest_and_tuning_plan.md:
- 4 Expanding-Window Folds over Development Set (2022-01-03 to 2024-12-31):
    Fold 1: Train 2022-01 to 2022-12 | Test 2023-01 to 2023-06
    Fold 2: Train 2022-01 to 2023-06 | Test 2023-07 to 2023-12
    Fold 3: Train 2022-01 to 2023-12 | Test 2024-01 to 2024-06
    Fold 4: Train 2022-01 to 2024-06 | Test 2024-07 to 2024-12
- Tier 1 Parameter Tuning:
    * ATR stop multiplier: 1.5, 2.0, 2.5
    * Target R multiple: 1.5, 2.0, 2.5
    * Pullback proximity to EMA20: 0.02, 0.03, 0.04, 0.05
    * RSI band: [35, 65], [40, 60], [45, 55]
    * Time stop: 10, 15, 20 sessions
- Selection Criteria:
    * Net positive expectancy in >= 3 of 4 test folds.
    * >= 30 trades per test fold.
    * Robust plateau test: neighbors retain >= 70% expectancy.
    * If tuned does not reliably beat baseline, keep baseline.
- Audit Trail:
    * Logs every configuration run to experiments/registry.csv.
"""

import csv
import datetime
from decimal import Decimal
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple
import numpy as np

from signal_atlas.backtest.engine import BacktestEngine, BacktestEngineConfig
from signal_atlas.backtest.metrics import calculate_comprehensive_metrics
from signal_atlas.backtest.models import PositionRecord
from signal_atlas.quality.adjustment import AdjustedPriceRecord
from signal_atlas.strategy.trend_pullback import TrendPullbackParameters, TrendPullbackStrategy


class WalkForwardFold:
    def __init__(
        self,
        fold_id: int,
        train_start: datetime.date,
        train_end: datetime.date,
        test_start: datetime.date,
        test_end: datetime.date,
    ):
        self.fold_id = fold_id
        self.train_start = train_start
        self.train_end = train_end
        self.test_start = test_start
        self.test_end = test_end


DEV_FOLDS = [
    WalkForwardFold(
        fold_id=1,
        train_start=datetime.date(2022, 1, 3),
        train_end=datetime.date(2022, 12, 30),
        test_start=datetime.date(2023, 1, 2),
        test_end=datetime.date(2023, 6, 30),
    ),
    WalkForwardFold(
        fold_id=2,
        train_start=datetime.date(2022, 1, 3),
        train_end=datetime.date(2023, 6, 30),
        test_start=datetime.date(2023, 7, 3),
        test_end=datetime.date(2023, 12, 29),
    ),
    WalkForwardFold(
        fold_id=3,
        train_start=datetime.date(2022, 1, 3),
        train_end=datetime.date(2023, 12, 29),
        test_start=datetime.date(2024, 1, 1),
        test_end=datetime.date(2024, 6, 28),
    ),
    WalkForwardFold(
        fold_id=4,
        train_start=datetime.date(2022, 1, 3),
        train_end=datetime.date(2024, 6, 28),
        test_start=datetime.date(2024, 7, 1),
        test_end=datetime.date(2024, 12, 31),
    ),
]


class ExperimentRegistry:
    """Appends all backtest trials to experiments/registry.csv."""

    def __init__(self, csv_path: Path = Path("experiments/registry.csv")):
        self.csv_path = csv_path
        self.csv_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.csv_path.exists():
            with open(self.csv_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow([
                    "trial_id",
                    "timestamp",
                    "strategy_version",
                    "stage",
                    "parameters_json",
                    "config_hash",
                    "fold_id",
                    "fold_type",
                    "date_start",
                    "date_end",
                    "total_trades",
                    "win_rate_pct",
                    "expectancy_r",
                    "profit_factor",
                    "max_drawdown_pct",
                    "total_return_pct",
                ])

    def get_next_trial_id(self) -> int:
        if not self.csv_path.exists():
            return 1
        max_id = 0
        try:
            with open(self.csv_path, "r", encoding="utf-8") as f:
                reader = csv.reader(f)
                header = next(reader, None)
                for row in reader:
                    if row and row[0].isdigit():
                        max_id = max(max_id, int(row[0]))
        except Exception:
            return 1
        return max_id + 1

    def log_trial(
        self,
        trial_id: Optional[int],
        stage: str,
        params: Dict[str, Any],
        fold_id: str,
        fold_type: str,
        start_date: datetime.date,
        end_date: datetime.date,
        metrics: Dict[str, Any],
    ) -> int:
        tid = trial_id if trial_id is not None else self.get_next_trial_id()
        params_str = json.dumps(params, sort_keys=True, default=str)
        cfg_hash = hashlib.sha256(params_str.encode()).hexdigest()[:12]
        with open(self.csv_path, "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                tid,
                datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "v1.0",
                stage,
                params_str,
                cfg_hash,
                fold_id,
                fold_type,
                start_date.isoformat(),
                end_date.isoformat(),
                metrics.get("total_trades", 0),
                metrics.get("win_rate_pct", 0.0),
                metrics.get("expectancy_r", 0.0),
                metrics.get("profit_factor", 0.0),
                metrics.get("max_drawdown_pct", 0.0),
                metrics.get("total_return_pct", 0.0),
            ])
        return tid


# -----------------------------------------------------------------------------
# TASK 7 / D6, D9: Decoupled 6-Point Parameter Grid
# -----------------------------------------------------------------------------
PARAM_GRID = [
    {"stop_atr_multiplier": Decimal("1.5"), "target_r_multiple": Decimal("1.5")},
    {"stop_atr_multiplier": Decimal("1.5"), "target_r_multiple": Decimal("2.0")},
    {"stop_atr_multiplier": Decimal("1.5"), "target_r_multiple": Decimal("2.5")},
    {"stop_atr_multiplier": Decimal("2.0"), "target_r_multiple": Decimal("1.5")},
    {"stop_atr_multiplier": Decimal("2.0"), "target_r_multiple": Decimal("2.0")},
    {"stop_atr_multiplier": Decimal("2.0"), "target_r_multiple": Decimal("2.5")},
]

VALID_GRID_KEYS = {"stop_atr_multiplier", "target_r_multiple"}


def apply_grid_params(
    base_params: TrendPullbackParameters,
    grid_point: Dict[str, Any],
) -> TrendPullbackParameters:
    """
    Explicitly maps grid parameters to TrendPullbackParameters fields.
    Fails loudly with ValueError on unknown keys (Task 7 / D9).
    """
    for k in grid_point:
        if k not in VALID_GRID_KEYS:
            raise ValueError(f"Unknown tuning parameter key: {k!r}. Allowed keys: {VALID_GRID_KEYS}")

    update_dict: Dict[str, Any] = {}
    if "stop_atr_multiplier" in grid_point:
        update_dict["stop_atr_multiplier"] = Decimal(str(grid_point["stop_atr_multiplier"]))
    if "target_r_multiple" in grid_point:
        update_dict["target_r_multiple"] = Decimal(str(grid_point["target_r_multiple"]))

    return base_params.model_copy(update=update_dict)


def get_grid_neighbors(grid_idx: int) -> List[int]:
    """Returns indices of adjacent neighbors on the 2x3 parameter grid."""
    # Grid shape: 2 rows (stop_atr 1.5, 2.0) x 3 cols (target_r 1.5, 2.0, 2.5)
    row = grid_idx // 3
    col = grid_idx % 3
    neighbor_indices = []
    # Up/down
    if row > 0:
        neighbor_indices.append((row - 1) * 3 + col)
    if row < 1:
        neighbor_indices.append((row + 1) * 3 + col)
    # Left/right
    if col > 0:
        neighbor_indices.append(row * 3 + (col - 1))
    if col < 2:
        neighbor_indices.append(row * 3 + (col + 1))
    return neighbor_indices


# -----------------------------------------------------------------------------
# TASK 8 / D6, D10: Objective Pre-Registered Selection Protocol
# -----------------------------------------------------------------------------
def evaluate_tuning_candidate(
    candidate_idx: int,
    candidate_fold_metrics: List[Dict[str, Any]],
    candidate_trades: List[PositionRecord],
    baseline_fold_metrics: List[Dict[str, Any]],
    baseline_trades: List[PositionRecord],
    all_grid_fold_expectancies: List[float],
) -> Dict[str, Any]:
    """
    Evaluates a candidate parameter set against the 4 pre-registered criteria:
    1. Out-of-fold expectancy > baseline out-of-fold expectancy in at least 3 of 4 folds.
    2. Out-of-fold trade count >= 30 in all 4 folds.
    3. Parameter plateau check: adjacent grid points have expectancy within 30% of candidate.
    4. Out-of-fold bootstrap CI of delta (candidate - baseline) excludes zero at 90% confidence.
    """
    # 1. Fold-by-fold expectancy check
    folds_beating_baseline = 0
    fold_trade_counts = []
    for c_m, b_m in zip(candidate_fold_metrics, baseline_fold_metrics):
        c_exp = c_m.get("expectancy_r", 0.0)
        b_exp = b_m.get("expectancy_r", 0.0)
        if c_exp > b_exp:
            folds_beating_baseline += 1
        fold_trade_counts.append(c_m.get("total_trades", 0))

    cond1_folds_pass = folds_beating_baseline >= 3
    cond2_trade_counts_pass = all(tc >= 30 for tc in fold_trade_counts)

    # 3. Plateau check against adjacent neighbors
    candidate_exp = all_grid_fold_expectancies[candidate_idx]
    neighbor_idxs = get_grid_neighbors(candidate_idx)
    plateau_pass = True
    plateau_details = []
    for n_idx in neighbor_idxs:
        n_exp = all_grid_fold_expectancies[n_idx]
        plateau_details.append({"neighbor_idx": n_idx, "expectancy": n_exp})
        if candidate_exp > 0:
            if n_exp < (candidate_exp * 0.70):
                plateau_pass = False

    # 4. Bootstrap CI of delta (candidate minus baseline) at 90% confidence
    c_r = np.array([float(t.realized_r_multiple) for t in candidate_trades]) if candidate_trades else np.array([0.0])
    b_r = np.array([float(t.realized_r_multiple) for t in baseline_trades]) if baseline_trades else np.array([0.0])

    rng = np.random.default_rng(42)
    n_boot = 1000
    boot_diffs = np.empty(n_boot)
    for b in range(n_boot):
        c_sample = rng.choice(c_r, size=len(c_r), replace=True)
        b_sample = rng.choice(b_r, size=len(b_r), replace=True)
        boot_diffs[b] = np.mean(c_sample) - np.mean(b_sample)

    ci_lower = round(float(np.percentile(boot_diffs, 5.0)), 4)
    ci_upper = round(float(np.percentile(boot_diffs, 95.0)), 4)
    cond4_ci_excludes_zero = ci_lower > 0.0

    all_conditions_met = (
        cond1_folds_pass
        and cond2_trade_counts_pass
        and plateau_pass
        and cond4_ci_excludes_zero
    )

    return {
        "candidate_idx": candidate_idx,
        "grid_params": PARAM_GRID[candidate_idx],
        "folds_beating_baseline": folds_beating_baseline,
        "cond1_folds_pass": cond1_folds_pass,
        "fold_trade_counts": fold_trade_counts,
        "cond2_trade_counts_pass": cond2_trade_counts_pass,
        "candidate_expectancy": candidate_exp,
        "neighbor_expectancies": plateau_details,
        "cond3_plateau_pass": plateau_pass,
        "ci_lower_90": ci_lower,
        "ci_upper_90": ci_upper,
        "cond4_ci_excludes_zero": cond4_ci_excludes_zero,
        "all_conditions_met": all_conditions_met,
    }
