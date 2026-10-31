#!/usr/bin/env python3
"""
ingest_missing_6_dates.py - Download and ingest genuine NSE Bhavcopies
for the 6 dates previously populated with mock test data in October 2024.
"""

import datetime
from signal_atlas.ingestion.pipeline import IngestionPipeline

def ingest_missing():
    target_dates = [
        datetime.date(2024, 10, 7),
        datetime.date(2024, 10, 8),
        datetime.date(2024, 10, 9),
        datetime.date(2024, 10, 10),
        datetime.date(2024, 10, 11),
        datetime.date(2024, 10, 24),
    ]

    pipeline = IngestionPipeline()
    for d in target_dates:
        print(f"\nProcessing {d} with force=True...")
        res = pipeline.ingest_date(d, force=True)
        print(f"Result for {d}: {res}")

if __name__ == "__main__":
    ingest_missing()
