import datetime
from decimal import Decimal
import numpy as np

from signal_atlas.backtest.engine import BacktestEngine, BacktestEngineConfig, EntryVariant
from signal_atlas.backtest.pipeline import FastSimulationRunner, load_development_dataset
from signal_atlas.strategy.trend_pullback import TrendPullbackParameters

dataset = load_development_dataset(end_date=datetime.date(2024, 12, 31), use_point_in_time_universe=True)

# Test with live RiskEngine behavior: reject if open risk exceeded
# We can subclass or test directly
class EquivalenceTestEngine(BacktestEngine):
    pass

runner = FastSimulationRunner(dataset)

# Let's inspect the trades when partial tiny slicing is disabled
trades = runner.run(
    params=TrendPullbackParameters(),
    start_date=datetime.date(2022, 1, 3),
    end_date=datetime.date(2024, 12, 31),
    entry_variant=EntryVariant.A,
)["trades"]

print(f"Total current trades: {len(trades)}")
r_all = [float(t.realized_r_multiple) for t in trades]
pnl_all = [float(t.net_pnl) for t in trades]
risk_all = [float(t.initial_risk_per_share * Decimal(t.quantity)) for t in trades]

print(f"Current: mean R = {np.mean(r_all):.4f} R | Net PnL = Rs. {sum(pnl_all):,.2f}")
print(f"Current: mean Risk = Rs. {np.mean(risk_all):,.2f} | Sum(PnL)/Sum(R) = Rs. {sum(pnl_all)/sum(r_all):.2f}")
