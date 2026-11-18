"""Download the full-text XML of the Federal Register documents we keep.

Reads data/raw/fr/catalog.json (from scripts/fr_catalog.py), applies the selection rules
in app/ingest/fedreg.py, and saves each document's XML untouched. Files already on disk
are skipped, so an interrupted run can simply be started again.

Finishes with a dry run of the parser: the real chunk count, before any embedding.
"""

import json
import pathlib
import time

from app.ingest.fedreg import parse_document, select_documents
from scripts.fetch_ecfr import get  # same retries and gzip handling as eCFR

FR_DIR = pathlib.Path("data/raw/fr")
XML_DIR = FR_DIR / "xml"


def download(entries: list[dict]) -> None:
    XML_DIR.mkdir(parents=True, exist_ok=True)
    for i, entry in enumerate(entries, 1):
        path = XML_DIR / f"{entry['document_number']}.xml"
        if path.exists():
            continue
        blob = get(entry["full_text_xml_url"])
        # Write to a temporary name first: a crash mid-write must not leave a partial
        # file that the next run would mistake for a finished download.
        tmp = path.with_suffix(".part")
        tmp.write_bytes(blob)
        tmp.replace(path)
        print(f"  [{i:>3}/{len(entries)}] {entry['document_number']:<12} {len(blob) // 1024:>5} KB")
        time.sleep(0.5)  # be polite to a free public API


def dry_run(entries: list[dict]) -> None:
    chunks, longest, failed = 0, 0, []
    for entry in entries:
        xml = (XML_DIR / f"{entry['document_number']}.xml").read_bytes()
        try:
            doc = parse_document(xml, entry)
        except Exception as exc:  # report every bad document, not just the first
            failed.append(f"{entry['document_number']}: {type(exc).__name__}: {exc}")
            continue
        chunks += len(doc.chunks)
        longest = max([longest, *(len(c.content) for c in doc.chunks)])

    size_mb = sum(p.stat().st_size for p in XML_DIR.glob("*.xml")) / 1_048_576
    print(f"\n{len(entries)} documents, {size_mb:.1f} MB of XML")
    print(f"{chunks} chunks (longest {longest} characters)")
    print(f"{len(failed)} failed to parse")
    for line in failed:
        print("  " + line)


def main() -> None:
    catalog = json.loads((FR_DIR / "catalog.json").read_text(encoding="utf-8"))
    entries = select_documents(catalog)
    print(f"{len(entries)} documents selected")
    download(entries)
    # run.py reads this list, so ingest uses exactly what was downloaded.
    (FR_DIR / "selected.json").write_text(json.dumps(entries, indent=2), encoding="utf-8")
    dry_run(entries)


if __name__ == "__main__":
    main()
