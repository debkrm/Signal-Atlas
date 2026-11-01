"""
generate_validation_report.py - Executes Phase 1 Data Validation and writes reports/data_validation.md.
"""

import os
from signal_atlas.backtest.data_checks import DataValidationRunner


def main() -> None:
    runner = DataValidationRunner()
    report = runner.run_all_checks()

    print("Overall Status:", report["overall_status"])
    for k, v in report["checks"].items():
        print(f"[{v['status']}] {v['name']}: {v['notes']}")

    os.makedirs("reports", exist_ok=True)
    report_path = os.path.join("reports", "data_validation.md")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("# Phase 1: Data Validation Report\n\n")
        f.write(f"**Executed At:** `{report['executed_at']}`  \n")
        f.write(f"**Development Dataset Range:** `{report['dev_start_date']}` to `{report['dev_end_date']}`  \n")
        f.write(f"**Overall Gate Status:** **`{report['overall_status']}`**  \n\n")
        f.write("---\n\n")
        f.write("## Validation Gates Summary\n\n")
        f.write("| Check | Status | Verification Summary |\n")
        f.write("|:---|:---:|:---|\n")
        for k, v in report["checks"].items():
            status_badge = "✅ PASS" if v["status"] == "PASS" else "❌ FAIL"
            f.write(f"| {v['name']} | {status_badge} | {v.get('notes', '-')} |\n")
        f.write("\n---\n\n")
        f.write("## Detailed Verification Results\n\n")
        for k, v in report["checks"].items():
            f.write(f"### {v['name']}\n")
            f.write(f"- **Gate Outcome:** `{v['status']}`\n")
            for prop, val in v.items():
                if prop not in ("name", "status"):
                    f.write(f"- **{prop}:** `{val}`\n")
            f.write("\n")

    print(f"Report written successfully to: {report_path}")


if __name__ == "__main__":
    main()
