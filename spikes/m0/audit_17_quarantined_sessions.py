from signal_atlas.db.session import get_db
from signal_atlas.db.models import IngestionRun
from sqlalchemy import select

def inspect_quarantined():
    with get_db() as db:
        runs = db.execute(
            select(IngestionRun)
            .where(IngestionRun.status == "QUARANTINED")
            .order_by(IngestionRun.trade_date)
        ).scalars().all()

        print(f"Total QUARANTINED sessions in database: {len(runs)}")
        for r in runs:
            issues = r.validation_issues or {}
            print(f"\nDate: {r.trade_date} | Run ID: {r.run_id} | File: {r.file_name} | Quarantined Count: {issues.get('quarantine_count')} | Warnings: {issues.get('warning_count')}")
            for iss in issues.get("issues_sample", []):
                if iss.get("severity") == "QUARANTINE":
                    print(f"   -> [{iss.get('rule')}] {iss.get('message')}")

if __name__ == "__main__":
    inspect_quarantined()
