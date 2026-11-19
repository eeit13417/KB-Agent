"""Parse govinfo PDFs: annual CFR part editions and Statutes at Large scans.

Spec: docs/specs/govinfo.md
"""

from app.config import settings
from app.ingest.chunker import SourceDocument


def parse_cfr_part(pdf: bytes, entry: dict, max_chars: int = settings.chunk_size) -> SourceDocument:
    raise NotImplementedError


def parse_statute(pdf: bytes, entry: dict, max_chars: int = settings.chunk_size) -> SourceDocument:
    raise NotImplementedError
