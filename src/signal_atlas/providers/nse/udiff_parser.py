import io
import zipfile
from typing import Any, Dict, List, Union
import pandas as pd


class ParserError(Exception):
    """Raised when parsing fails due to invalid archive structure or missing required columns."""
    pass


REQUIRED_UDIFF_COLUMNS = {
    "TradDt",
    "BizDt",
    "Sgmt",
    "FinInstrmTp",
    "TckrSymb",
    "SctySrs",
    "ISIN",
    "OpnPric",
    "HghPric",
    "LwPric",
    "ClsPric",
    "PrvsClsgPric",
    "TtlTradgVol",
    "TtlTrfVal",
}

PARSER_VERSION = "udiff_v1"


class UDiFFParser:
    """
    Parses NSE CM-UDiFF Common Bhavcopy archives.
    Validates presence of required exchange fields.
    """

    def parse_archive(self, file_or_bytes: Union[bytes, io.BytesIO, str]) -> List[Dict[str, Any]]:
        """
        Unpack ZIP archive and parse the contained CSV file.

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
                raise ParserError("No CSV file found inside Bhavcopy ZIP archive.")

            csv_filename = csv_files[0]
            with z.open(csv_filename) as f:
                try:
                    df = pd.read_csv(f, dtype=str, keep_default_na=False)
                except Exception as e:
                    raise ParserError(f"Failed to read CSV content from {csv_filename}: {e}") from e

        # Strip whitespace from column names
        df.columns = [str(col).strip() for col in df.columns]

        missing_cols = REQUIRED_UDIFF_COLUMNS - set(df.columns)
        if missing_cols:
            raise ParserError(
                f"CM-UDiFF format validation failed: missing required columns {sorted(missing_cols)}"
            )

        # Convert to records
        records = df.to_dict(orient="records")
        return records
