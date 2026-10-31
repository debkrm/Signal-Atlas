import json
from collections import defaultdict

with open('data/checkpoints/historical_split_bonus_sweep.json') as f:
    sweep = json.load(f)
with open('data/checkpoints/candidates_full_disposition_report.json') as f:
    disp = json.load(f)

cross_tab = defaultdict(lambda: defaultdict(int))
for s, d in zip(sweep, disp):
    isin_type = 'MULTI_ISIN' if s['multi_isin'] else 'SAME_ISIN'
    cat = d['disposition']
    cross_tab[cat][isin_type] += 1
    cross_tab[cat]['TOTAL'] += 1

print(f"| {'Disposition':<32} | {'MULTI_ISIN':<12} | {'SAME_ISIN':<12} | {'TOTAL':<8} |")
print("|" + "-"*34 + "|" + "-"*14 + "|" + "-"*14 + "|" + "-"*10 + "|")
total_multi = 0
total_same = 0
total_all = 0
for cat, counts in sorted(cross_tab.items(), key=lambda x: -x[1]['TOTAL']):
    m = counts['MULTI_ISIN']
    s = counts['SAME_ISIN']
    t = counts['TOTAL']
    total_multi += m
    total_same += s
    total_all += t
    print(f"| {cat:<32} | {m:<12} | {s:<12} | {t:<8} |")
print("|" + "-"*34 + "|" + "-"*14 + "|" + "-"*14 + "|" + "-"*10 + "|")
print(f"| {'TOTAL':<32} | {total_multi:<12} | {total_same:<12} | {total_all:<8} |")
