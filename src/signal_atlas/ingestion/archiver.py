import datetime
import hashlib
import logging
from pathlib import Path
from typing import Optional, Tuple

from signal_atlas.config import settings

logger = logging.getLogger(__name__)


class RawArchiver:
    """
    Saves unmodified source files to the local archive directory
    and computes bit-level SHA-256 hashes for data provenance.
    Never silently overwrites an existing archive if hashes differ.
    """

    def __init__(self, raw_dir: Optional[Path] = None):
        self.raw_dir = raw_dir or settings.raw_dir

    def get_cached(
        self,
        filename: str,
        trade_date: Optional[datetime.date] = None,
    ) -> Optional[Tuple[Path, bytes, str]]:
        """
        Check if a valid archive already exists locally in raw_dir or fallback dirs.

        Returns:
            Tuple of (Path, content_bytes, sha256) if found, else None.
        """
        candidate_paths = []
        if trade_date:
            candidate_paths.append(self.raw_dir / str(trade_date.year) / filename)
        candidate_paths.append(self.raw_dir / filename)
        candidate_paths.append(Path("spikes/m0/downloads") / filename)

        for p in candidate_paths:
            if p.exists() and p.is_file():
                try:
                    content = p.read_bytes()
                    if content.startswith(b"PK\x03\x04"):
                        sha256 = hashlib.sha256(content).hexdigest()
                        return p, content, sha256
                except OSError as e:
                    logger.warning("Error reading candidate archive %s: %s", p, e)

        return None

    def archive(
        self,
        filename: str,
        content: bytes,
        trade_date: Optional[datetime.date] = None,
    ) -> Tuple[Path, str]:
        """
        Save raw bytes and calculate SHA-256.
        If a file already exists at the destination:
        - If SHA-256 matches: returns existing path (idempotent).
        - If SHA-256 differs: preserves both by saving with conflict tag.

        Returns:
            Tuple of (Path where saved, sha256_hex_digest)
        """
        year_str = str(trade_date.year) if trade_date else "misc"
        target_dir = self.raw_dir / year_str
        target_dir.mkdir(parents=True, exist_ok=True)

        sha256 = hashlib.sha256(content).hexdigest()
        target_file = target_dir / filename

        if target_file.exists():
            existing_bytes = target_file.read_bytes()
            existing_sha256 = hashlib.sha256(existing_bytes).hexdigest()
            if existing_sha256 == sha256:
                return target_file, sha256
            else:
                # Content discrepancy! Preserve both versions.
                ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                conflict_filename = f"{filename}.conflict_{ts}_{sha256[:8]}"
                conflict_path = target_dir / conflict_filename
                with open(conflict_path, "wb") as f:
                    f.write(content)
                logger.warning(
                    "Archive discrepancy for %s! Existing SHA256: %s, New SHA256: %s. Preserved conflict at %s",
                    filename,
                    existing_sha256,
                    sha256,
                    conflict_path,
                )
                return conflict_path, sha256

        with open(target_file, "wb") as f:
            f.write(content)

        return target_file, sha256
