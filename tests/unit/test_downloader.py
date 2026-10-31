import datetime
from unittest.mock import MagicMock, patch
import pytest

from signal_atlas.providers.nse.downloader import (
    DataUnavailableError,
    DownloaderError,
    ExpectedDataMissingError,
    NonTradingDayError,
    NSEDownloader,
    UDiFFDownloader,
)


def test_candidate_urls_generation_udiff():
    downloader = NSEDownloader()
    dt = datetime.date(2024, 10, 25)
    candidates = downloader.get_candidate_urls(dt)
    assert len(candidates) == 2
    era, filename, url = candidates[0]
    assert era == "UDiFF"
    assert filename == "BhavCopy_NSE_CM_0_0_0_20241025_F_0000.csv.zip"
    assert "20241025" in url


def test_candidate_urls_generation_legacy():
    downloader = NSEDownloader()
    dt = datetime.date(2022, 7, 28)
    candidates = downloader.get_candidate_urls(dt)
    assert len(candidates) == 2
    era, filename, url = candidates[0]
    assert era == "Legacy"
    assert filename == "cm28JUL2022bhav.csv.zip"
    assert "2022/JUL" in url


def test_weekend_detection_raises_non_trading_day():
    downloader = NSEDownloader()
    # 2024-10-26 is a Saturday
    sat = datetime.date(2024, 10, 26)
    with pytest.raises(NonTradingDayError, match="weekend"):
        downloader.download(sat, use_cache=False)


def test_all_404_raises_data_unavailable():
    downloader = NSEDownloader(delay=0.0)
    mock_resp = MagicMock()
    mock_resp.status_code = 404

    with patch.object(downloader.session, "get", return_value=mock_resp):
        with pytest.raises(ExpectedDataMissingError, match="Expected trading session data missing"):
            downloader.download(datetime.date(2024, 10, 25), use_cache=False)


def test_reject_html_error_response():
    downloader = NSEDownloader(delay=0.0)
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = b"<!DOCTYPE html><html><head><title>Error</title></head><body>File not found</body></html>"

    with patch.object(downloader.session, "get", return_value=mock_resp):
        with pytest.raises(DownloaderError, match="Received HTML error response"):
            downloader.download(datetime.date(2024, 10, 25), use_cache=False)


def test_reject_invalid_zip_signature():
    downloader = NSEDownloader(delay=0.0)
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = b"SOMERANDOMBYTESNOTAZIPFILE"

    with patch.object(downloader.session, "get", return_value=mock_resp):
        with pytest.raises(DownloaderError, match="Invalid ZIP signature"):
            downloader.download(datetime.date(2024, 10, 25), use_cache=False)


def test_download_success():
    downloader = NSEDownloader(delay=0.0)
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = b"PK\x03\x04fakepayload"

    with patch.object(downloader.session, "get", return_value=mock_resp):
        fname, content, url = downloader.download(datetime.date(2024, 10, 25), use_cache=False)
        assert fname == "BhavCopy_NSE_CM_0_0_0_20241025_F_0000.csv.zip"
        assert content == b"PK\x03\x04fakepayload"
