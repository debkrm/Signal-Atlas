import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple
from pydantic import BaseModel

from signal_atlas.ingestion.normalizer import NormalizedRecord


class ValidationIssue(BaseModel):
    severity: str  # "FATAL", "QUARANTINE", "WARNING", "INFO"
    rule: str
    message: str
    record_identifier: Optional[str] = None


class QuarantinedRecord(BaseModel):
    record: NormalizedRecord
    rule: str
    message: str
    row_number: Optional[int] = None
    raw_payload: Optional[Dict[str, Any]] = None


class ValidationResult(BaseModel):
    is_fatal: bool = False
    fatal_error: Optional[str] = None
    total_records: int = 0
    valid_count: int = 0
    quarantine_count: int = 0
    warning_count: int = 0
    issues: List[ValidationIssue] = []
    quarantined_records: List[QuarantinedRecord] = []

    def to_summary_dict(self) -> Dict[str, Any]:
        return {
            "total_records": self.total_records,
            "valid_count": self.valid_count,
            "quarantine_count": self.quarantine_count,
            "warning_count": self.warning_count,
            "is_fatal": self.is_fatal,
            "fatal_error": self.fatal_error,
            "issues_sample": [issue.model_dump() for issue in self.issues[:20]],
        }


class BatchValidator:
    """
    Validates normalized records against market-data integrity constraints:
    - Expected trade date verification
    - OHLC geometric consistency (low <= open/close <= high)
    - Positive price enforcement
    - ISIN and Symbol validity
    - In-batch duplicate detection
    - Suspicious price movement warnings
    """

    def validate_batch(
        self,
        records: List[NormalizedRecord],
        expected_date: datetime.date,
    ) -> Tuple[List[NormalizedRecord], ValidationResult]:
        """
        Validate all records in a batch.

        Returns:
            Tuple of (valid_records_to_persist, validation_result)
        """
        result = ValidationResult(total_records=len(records))

        if not records:
            result.is_fatal = True
            result.fatal_error = f"Empty batch for date {expected_date}"
            result.issues.append(
                ValidationIssue(
                    severity="FATAL",
                    rule="NON_EMPTY_BATCH",
                    message="No records present in parsed batch",
                )
            )
            return [], result

        valid_records: List[NormalizedRecord] = []
        seen_keys = set()

        for rec in records:
            ident = f"{rec.symbol}:{rec.series}:{rec.isin}"

            def _record_quarantine(rule: str, msg: str):
                issue = ValidationIssue(
                    severity="QUARANTINE",
                    rule=rule,
                    message=msg,
                    record_identifier=ident,
                )
                result.quarantine_count += 1
                result.issues.append(issue)
                result.quarantined_records.append(
                    QuarantinedRecord(
                        record=rec,
                        rule=rule,
                        message=msg,
                        row_number=rec.source_row_number,
                        raw_payload=rec.raw_payload or rec.model_dump(mode="json"),
                    )
                )

            # 1. Date check (Fatal if mismatch)
            if rec.trade_date != expected_date:
                result.is_fatal = True
                result.fatal_error = (
                    f"Batch date mismatch: expected {expected_date}, found {rec.trade_date} for {ident}"
                )
                result.issues.append(
                    ValidationIssue(
                        severity="FATAL",
                        rule="DATE_MATCH",
                        message=f"Date mismatch: record date {rec.trade_date} != batch date {expected_date}",
                        record_identifier=ident,
                    )
                )
                return [], result

            # 2. Duplicate detection within batch
            key = (rec.symbol, rec.series, rec.isin)
            if key in seen_keys:
                _record_quarantine("DUPLICATE_RECORD", f"Duplicate entry in batch for {ident}")
                continue
            seen_keys.add(key)

            # 3. Identifier checks
            if not rec.symbol or not rec.series:
                _record_quarantine("MISSING_IDENTIFIER", f"Missing symbol or series for {ident}")
                continue

            if len(rec.isin) != 12:
                _record_quarantine("INVALID_ISIN", f"ISIN length is {len(rec.isin)} (expected 12) for {ident}")
                continue

            # 4. OHLC Price checks
            if rec.open <= Decimal("0") or rec.high <= Decimal("0") or rec.low <= Decimal("0") or rec.close <= Decimal("0"):
                _record_quarantine(
                    "NON_POSITIVE_PRICE",
                    f"Non-positive price detected (O={rec.open}, H={rec.high}, L={rec.low}, C={rec.close}) for {ident}",
                )
                continue

            if rec.low > rec.high:
                _record_quarantine("LOW_EXCEEDS_HIGH", f"Low price ({rec.low}) exceeds High price ({rec.high}) for {ident}")
                continue

            if not (rec.low <= rec.open <= rec.high):
                _record_quarantine("OPEN_OUT_OF_RANGE", f"Open ({rec.open}) outside [Low={rec.low}, High={rec.high}] for {ident}")
                continue

            if not (rec.low <= rec.close <= rec.high):
                _record_quarantine("CLOSE_OUT_OF_RANGE", f"Close ({rec.close}) outside [Low={rec.low}, High={rec.high}] for {ident}")
                continue

            # 5. Volume and Traded Value checks
            if rec.volume < 0 or rec.traded_value < Decimal("0"):
                _record_quarantine("NEGATIVE_VOLUME_OR_VALUE", f"Negative volume ({rec.volume}) or value ({rec.traded_value}) for {ident}")
                continue

            # 6. Warnings (Suspicious price movement > 50% from prev_close)
            if rec.prev_close > Decimal("0"):
                rel_change = abs(rec.close - rec.prev_close) / rec.prev_close
                if rel_change > Decimal("0.50"):
                    result.warning_count += 1
                    result.issues.append(
                        ValidationIssue(
                            severity="WARNING",
                            rule="LARGE_PRICE_MOVEMENT",
                            message=(
                                f"Large price movement {round(rel_change * 100, 1)}% "
                                f"(PrevClose={rec.prev_close}, Close={rec.close}) for {ident}"
                            ),
                            record_identifier=ident,
                        )
                    )

            valid_records.append(rec)

        result.valid_count = len(valid_records)
        return valid_records, result
