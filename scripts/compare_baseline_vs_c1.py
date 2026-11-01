import csv

with open("experiments/registry.csv") as f:
    r = list(csv.DictReader(f))

# Baseline test folds (Trials 41-44)
b_folds = [row for row in r if row["stage"] == "WF_BASELINE_TEST" and int(row["trial_id"]) >= 41 and int(row["trial_id"]) <= 44]
# Grid 1 test folds (Trials 49-52: stop 1.5, target 2.0)
c1_folds = [row for row in r if row["stage"] == "GRID_SWEEP" and int(row["trial_id"]) >= 49 and int(row["trial_id"]) <= 52]

print("Baseline test folds (Trials 41-44):")
b_exps = []
for row in b_folds:
    print(f"  {row['fold_id']} {row['date_start']}->{row['date_end']} Trades:{row['total_trades']:<4} Exp:{row['expectancy_r']:<7} Win%:{row['win_rate_pct']:<6} NetRet:{row['total_return_pct']}%")
    b_exps.append(float(row["expectancy_r"]))
print(f"Mean Baseline Exp: {sum(b_exps)/len(b_exps):.4f} R")

print("\nCandidate 1 (stop 1.5, target 2.0) test folds (Trials 49-52):")
c1_exps = []
for row in c1_folds:
    print(f"  {row['fold_id']} {row['date_start']}->{row['date_end']} Trades:{row['total_trades']:<4} Exp:{row['expectancy_r']:<7} Win%:{row['win_rate_pct']:<6} NetRet:{row['total_return_pct']}%")
    c1_exps.append(float(row["expectancy_r"]))
print(f"Mean Candidate 1 Exp: {sum(c1_exps)/len(c1_exps):.4f} R")
