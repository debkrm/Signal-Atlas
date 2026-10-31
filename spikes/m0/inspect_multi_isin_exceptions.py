import json

def inspect_exceptions():
    with open("data/checkpoints/isin_identity_mappings_audit.json", "r", encoding="utf-8") as f:
        records = json.load(f)

    print("=== ISSUER CHANGE / MERGER / NON-SAME-PREFIX CASES ===")
    for r in records:
        if not r["same_issuer_prefix"] or r["decision"] == "PREDECESSOR_SUCCESSOR":
            print(json.dumps(r, indent=2))

    print("\n=== UNUSUAL PRICE RATIO CASES (ratio > 12 or < 0.7 or ratio between 2.5 and 3.5) ===")
    for r in records:
        ratio = r.get("observed_price_ratio")
        if ratio and (ratio > 12.0 or ratio < 0.7 or (2.5 <= ratio <= 3.8)):
            print(f"Company: {r['company_name']}, Symbol: {r['symbols']}, Old: {r['old_isin']} -> New: {r['new_isin']}, Ratio: {ratio}, Old close: {r['old_close']}, New close: {r['new_close']}")

if __name__ == "__main__":
    inspect_exceptions()
