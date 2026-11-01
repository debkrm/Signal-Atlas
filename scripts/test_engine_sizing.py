import datetime
from decimal import Decimal
from signal_atlas.backtest.pipeline import load_development_dataset, FastSimulationRunner
from signal_atlas.strategy.trend_pullback import TrendPullbackParameters

dataset = load_development_dataset(end_date=datetime.date(2024, 12, 31), use_point_in_time_universe=True)
runner = FastSimulationRunner(dataset)
start_dt = datetime.date(2022, 1, 3)
end_dt = datetime.date(2024, 12, 31)

res = runner.run(
    params=TrendPullbackParameters(),
    start_date=start_dt,
    end_date=end_dt,
)
trades = res["trades"]
metrics = res["metrics"]
print("Current engine run:")
print(f"Total trades: {len(trades)}")
net_pnl = sum(t.net_pnl for t in trades)
sum_r = sum(t.realized_r_multiple for t in trades)
print(f"Net PnL: Rs. {net_pnl:.2f}")
print(f"Sum R: {sum_r:.2f}")
print(f"Expectancy R: {metrics['expectancy_r']:.4f}")
print(f"Net Profit Factor: {metrics['profit_factor']:.2f}")
print(f"Gross Profit Factor: {metrics['gross_profit_factor']:.2f}")
print(f"Max DD: {metrics['max_drawdown_pct']:.2f}%")
print(f"Net return: {metrics['net_return_pct']:.2f}%")

