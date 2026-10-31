import io
import zipfile
from typing import Any, Dict, List, Union
import pandas as pd

from signal_atlas.providers.nse.udiff_parser import ParserError

LEGACY_REQUIRED_COLUMNS = {
    "SYMBOL",
    "SERIES",
    "OPEN",
    "HIGH",
    "LOW",
    "CLOSE",
    "LAST",
    "PREVCLOSE",
    "TOTTRDQTY",
    "TOTTRDVAL",
    "TIMESTAMP",
    "TOTALTRADES",
    "ISIN",
}

LEGACY_PARSER_VERSION = "legacy_v1"


class LegacyBhavcopyParser:
    """
    Parses historical NSE Legacy Bhavcopy archives (pre-July 8, 2024).
    Handles trailing comma artifacts and preserves literal 'NA' security series.
    """

    def parse_archive(self, file_or_bytes: Union[bytes, io.BytesIO, str]) -> List[Dict[str, Any]]:
        """
        Unpack ZIP archive and parse the legacy Bhavcopy CSV file.

        Args:
            file_or_bytes: Raw bytes or path to the ZIP archive.

        Returns:
            List of raw record dictionaries.

        Raises:
            ParserError: If ZIP is corrupted or required columns are missing.
        """
        try:
            if isinstance(file_or_bytes, bytes):
                z = zipfile.ZipFile(io.BytesIO(file_or_bytes))
            else:
                z = zipfile.ZipFile(file_or_bytes)
        except zipfile.BadZipFile as e:
            raise ParserError(f"Corrupted or invalid ZIP archive: {e}") from e

        with z:
            csv_files = [name for name in z.namelist() if name.lower().endswith(".csv")]
            if not csv_files:
                raise ParserError("No CSV file found inside Legacy Bhavcopy ZIP archive.")

            csv_filename = csv_files[0]
            with z.open(csv_filename) as f:
                try:
                    df = pd.read_csv(f, dtype=str, keep_default_na=False)
                except Exception as e:
                    raise ParserError(f"Failed to read CSV content from {csv_filename}: {e}") from e

        # Strip whitespace from column names
        df.columns = [str(col).strip() for col in df.columns]

        # Safely remove trailing unnamed columns from legacy CSVs
        unnamed_cols = [c for c in df.columns if c.startswith("Unnamed:")]
        if unnamed_cols:
            df = df.drop(columns=unnamed_cols)

        missing_cols = LEGACY_REQUIRED_COLUMNS - set(df.columns)
        if missing_cols:
            raise ParserError(
                f"Legacy Bhavcopy format validation failed: missing required columns {sorted(missing_cols)}"
            )

        records = df.to_dict(orient="records")
        return records
