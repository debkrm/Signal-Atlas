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

    def log_trial(
        self,
        trial_id: int,
        stage: str,
        params: Dict[str, Any],
        fold_id: str,
        fold_type: str,
        start_date: datetime.date,
        end_date: datetime.date,
        metrics: Dict[str, Any],
    ) -> None:
        params_str = json.dumps(params, sort_keys=True, default=str)
        cfg_hash = hashlib.sha256(params_str.encode()).hexdigest()[:12]
        with open(self.csv_path, "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                trial_id,
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
