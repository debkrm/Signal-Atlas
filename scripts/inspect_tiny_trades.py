import csv

with open("reports/v2_baseline_trades.csv") as f:
    trades = list(csv.DictReader(f))

tiny = [t for t in trades if float(t["rupee_risk"]) < 2000.0]
print(f"Found {len(tiny)} tiny trades:")
for t in tiny:
    print(f"{t['symbol']:<12} {t['entry_date']} Qty:{t['quantity']:<5} PosVal:Rs.{float(t['position_value']):<10.2f} Risk:Rs.{float(t['rupee_risk']):<8.2f} Costs:Rs.{float(t['costs_rupees']):<6.2f} PnL:Rs.{float(t['net_pnl']):<8.2f} R:{t['realized_r']:<6} Exit:{t['exit_reason']}")

