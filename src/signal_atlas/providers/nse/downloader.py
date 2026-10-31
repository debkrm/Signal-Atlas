import datetime
import logging
import time
from pathlib import Path
from typing import List, Optional, Tuple
import requests

from signal_atlas.config import settings
from signal_atlas.ingestion.archiver import RawArchiver
from signal_atlas.providers.nse.calendar import (
    NSETradingCalendar,
    SPECIAL_WEEKEND_SESSIONS,
)

logger = logging.getLogger(__name__)

ZIP_MAGIC_BYTES = b"PK\x03\x04"
UDIFF_TRANSITION_DATE = datetime.date(2024, 7, 8)


class DownloaderError(Exception):
    """Base exception for downloader failures."""
    pass


class NonTradingDayError(DownloaderError):
    """Raised when date is a regular weekend."""
    pass


class ConfirmedHolidayError(DownloaderError):
    """Raised when date is confirmed as an official NSE exchange holiday."""
    pass


class ExpectedDataMissingError(DownloaderError):
    """Raised when an expected trading session returns HTTP 404 from all candidate URLs."""
    pass


# Backward-compatible alias
DataUnavailableError = ExpectedDataMissingError


class NSEDownloader:
    """
    Downloads NSE Bhavcopy archives across format eras:
    - Pre-July 8, 2024: Legacy Bhavcopy (cm<DD><MMM><YYYY>bhav.csv.zip)
    - Post-July 8, 2024: CM-UDiFF Common Bhavcopy (BhavCopy_NSE_CM_0_0_0_<YYYYMMDD>_F_0000.csv.zip)

    Features:
    - Checks local cache before network requests to avoid redundant traffic.
    - Authoritative calendar integration: recognizes confirmed holidays and special weekend trading sessions.
    - Distinguishes confirmed exchange holidays from unverified 404 missing data.
    - Polite request pacing and bounded retries.
    - Binary content integrity validation (ZIP magic bytes) & HTML guard.
    """

    def __init__(
        self,
        timeout: Optional[int] = None,
        delay: Optional[float] = None,
        archiver: Optional[RawArchiver] = None,
    ):
        self.timeout = timeout or settings.nse_timeout_seconds
        self.delay = delay if delay is not None else settings.nse_request_delay_seconds
        self.archiver = archiver or RawArchiver()
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": settings.user_agent,
                "Accept": "*/*",
                "Accept-Language": "en-US,en;q=0.9",
                "Referer": "https://www.nseindia.com/",
            }
        )

    def get_candidate_urls(self, trade_date: datetime.date) -> List[Tuple[str, str, str]]:
        """
        Return list of (era, filename, url) candidates for the given date.
        """
        dd = trade_date.strftime("%d")
        mmm = trade_date.strftime("%b").upper()
        yyyy = trade_date.strftime("%Y")
        yyyymmdd = trade_date.strftime("%Y%m%d")

        if trade_date >= UDIFF_TRANSITION_DATE:
            filename = f"BhavCopy_NSE_CM_0_0_0_{yyyymmdd}_F_0000.csv.zip"
            return [
                ("UDiFF", filename, f"https://nsearchives.nseindia.com/content/cm/{filename}"),
                ("UDiFF", filename, f"https://archives.nseindia.com/content/cm/{filename}"),
            ]
        else:
            filename = f"cm{dd}{mmm}{yyyy}bhav.csv.zip"
            return [
                (
                    "Legacy",
                    filename,
                    f"https://archives.nseindia.com/content/historical/EQUITIES/{yyyy}/{mmm}/{filename}",
                ),
                (
                    "Legacy",
                    filename,
                    f"https://nsearchives.nseindia.com/content/historical/EQUITIES/{yyyy}/{mmm}/{filename}",
                ),
            ]

    def download(
        self,
        trade_date: datetime.date,
        use_cache: bool = True,
    ) -> Tuple[str, bytes, str]:
        """
        Download or retrieve cached Bhavcopy for trade_date.

        Args:
            trade_date: The date to download.
            use_cache: If True, check local archive cache first.

        Returns:
            Tuple of (filename, raw_bytes, source_url_or_cache_path)

        Raises:
            ConfirmedHolidayError: If trade_date is a verified NSE holiday.
            NonTradingDayError: If trade_date is a regular weekend without trading sessions.
            ExpectedDataMissingError: If expected trading session returns 404 from all mirrors.
            DownloaderError: If download fails due to network error or corrupt content.
        """
        candidates = self.get_candidate_urls(trade_date)
        primary_filename = candidates[0][1]

        # 1. Local Cache Lookup
        if use_cache:
            cached = self.archiver.get_cached(primary_filename, trade_date=trade_date)
            if cached:
                path, content, _ = cached
                logger.info("Found cached archive for %s at %s (%d bytes)", trade_date, path, len(content))
                return primary_filename, content, f"cache://{path}"

        # 2. Confirmed Holiday Check
        is_hol, hol_name = NSETradingCalendar.is_confirmed_holiday(trade_date)
        if is_hol:
            raise ConfirmedHolidayError(f"{trade_date} is a confirmed NSE holiday: {hol_name}")

        # 3. Weekend Check (unless special live weekend session e.g. disaster recovery drill)
        if trade_date.weekday() >= 5 and trade_date not in SPECIAL_WEEKEND_SESSIONS:
            day_name = trade_date.strftime("%A")
            raise NonTradingDayError(f"{trade_date} is a weekend ({day_name}). No Bhavcopy scheduled.")

        # 4. Network Fetch
        all_404 = True
        last_error = None

        for era, filename, url in candidates:
            logger.info("Attempting download (%s): %s", era, url)
            if self.delay > 0:
                time.sleep(self.delay)
            try:
                resp = self.session.get(url, timeout=self.timeout)
                if resp.status_code == 404:
                    last_error = f"HTTP 404 (File not found on {url})"
                    continue

                all_404 = False

                if resp.status_code != 200:
                    last_error = f"HTTP {resp.status_code} on {url}"
                    continue

                content = resp.content
                # Reject HTML error pages
                if content.strip().startswith(b"<") or b"<html" in content[:200].lower():
                    last_error = f"Received HTML error response from {url}"
                    logger.warning("Rejected response from %s: HTML error page", url)
                    continue

                # Verify ZIP signature
                if not content.startswith(ZIP_MAGIC_BYTES):
                    last_error = f"Invalid ZIP signature (first 4 bytes: {content[:4]!r}) from {url}"
                    logger.warning("Rejected response from %s: Invalid ZIP header", url)
                    continue

                logger.info("Downloaded %s successfully (%d bytes)", filename, len(content))
                return filename, content, url

            except requests.RequestException as e:
                all_404 = False
                logger.warning("Network error fetching %s: %s", url, e)
                last_error = str(e)

        if all_404:
            raise ExpectedDataMissingError(
                f"Expected trading session data missing for {trade_date}. HTTP 404 on all mirrors."
            )

        raise DownloaderError(
            f"Failed to download Bhavcopy for date {trade_date}. Reason: {last_error}"
        )


# Backward-compatible alias
UDiFFDownloader = NSEDownloader
