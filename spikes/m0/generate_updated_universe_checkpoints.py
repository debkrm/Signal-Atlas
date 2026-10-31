import datetime
from decimal import Decimal
import json
from pathlib import Path
from signal_atlas.universe import PointInTimeUniverseService, UniverseConfig
from signal_atlas.db.session import get_db

def main():
    service = PointInTimeUniverseService()
    cfg = UniverseConfig()
    
    print(f"Config identifier: {cfg.config_identifier}")
    print(f"min_turnover_completeness: {cfg.min_turnover_completeness}")
    print(f"adjustment_version: {cfg.adjustment_version}")
    print(f"raw_data_version: {cfg.raw_data_version}")
    
    out_dir = Path("data/universe_checkpoints")
    out_dir.mkdir(parents=True, exist_ok=True)
    
    for dt in (datetime.date(2023, 1, 2), datetime.date(2024, 10, 25)):
        print(f"\n--- Building universe for {dt} ---")
        snap = service.build_universe(dt, config=cfg, persist=True)
        print(f"Snapshot ID: {snap.snapshot_id}")
        print(f"Lookback window: {snap.lookback_start_date} to {snap.lookback_end_date} ({snap.lookback_sessions} sessions)")
        print(f"Evaluated: {snap.total_instruments_evaluated}")
        print(f"Eligible: {snap.eligible_count}")
        print(f"Excluded: {snap.excluded_count}")
        
        # Breakdown of exclusion reasons
        reason_counts = {}
        for m in snap.excluded_members:
            r = m.exclusion_reason.value if m.exclusion_reason else "UNKNOWN"
            reason_counts[r] = reason_counts.get(r, 0) + 1
        print("Exclusion breakdown:")
        for r, cnt in sorted(reason_counts.items(), key=lambda x: -x[1]):
            print(f"  {r}: {cnt}")
            
        # Top 10 eligible members
        print("Top 10 eligible by ADTV:")
        for m in snap.eligible_members[:10]:
            print(f"  Rank {m.rank:3d}: {m.symbol:12s} ({m.isin}) | Series: {m.series} | Obs: {m.observed_sessions_count}/{m.expected_lookback_sessions} ({(m.trading_completeness*100):.1f}%) | Valid Turnover: {m.valid_turnover_sessions_count} ({(m.turnover_data_completeness*100):.1f}%) | ADTV: INR {m.average_daily_turnover:,.2f}")
            
        # Check specific test instruments
        for check_sym in ("HDFC", "RELIANCE", "TCS", "MIRCELECTR", "360ONE", "IIFLWAM", "GVPTECH", "4THDIM"):
            m = None
            for cand in (snap.eligible_members + snap.excluded_members):
                if cand.symbol == check_sym:
                    m = cand
                    break
            if m:
                status = "ELIGIBLE (Rank " + str(m.rank) + ")" if m.is_eligible else f"EXCLUDED ({m.exclusion_reason})"
                print(f"  Spotcheck {check_sym:10s}: {status} | Series: {m.series} | ADTV: INR {m.average_daily_turnover or 0:,.2f}")

        # Export checkpoint json
        checkpoint_path = out_dir / f"universe_{dt.isoformat()}_{cfg.config_identifier}.json"
        with open(checkpoint_path, "w", encoding="utf-8") as f:
            f.write(snap.model_dump_json(indent=2))
        print(f"Exported checkpoint to {checkpoint_path}")

        # Export eligible members CSV
        csv_path = out_dir / f"universe_{dt.isoformat()}_{cfg.config_identifier}_eligible.csv"
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            import csv
            writer = csv.writer(f)
            writer.writerow([
                "rank", "symbol", "isin", "series", "observed_sessions", "expected_sessions",
                "trading_completeness", "valid_turnover_sessions", "turnover_completeness",
                "adtv_inr", "median_turnover_inr", "latest_raw_close"
            ])
            for mem in snap.eligible_members:
                writer.writerow([
                    mem.rank, mem.symbol, mem.isin, mem.series, mem.observed_sessions_count,
                    mem.expected_lookback_sessions, mem.trading_completeness,
                    mem.valid_turnover_sessions_count, mem.turnover_data_completeness,
                    mem.average_daily_turnover, mem.median_daily_turnover, mem.latest_raw_close
                ])
        print(f"Exported eligible CSV to {csv_path}")

if __name__ == "__main__":
    main()
