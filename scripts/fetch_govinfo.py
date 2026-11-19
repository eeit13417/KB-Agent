"""Download past CFR editions and enacting statutes from govinfo.gov as PDFs.

CFR: every part in scripts/fetch_ecfr.py, in each edition year below. govinfo answers 400
for a part that did not exist yet in that year (Part 10 before 2015, for example); those
are listed as missing, not treated as errors.

Statutes: the laws below, from the scanned Statutes at Large. A wrong citation shows up in
the dry run, because parse_statute cannot find "Public Law X" on the pages.

Files already on disk are skipped, so an interrupted run can simply be started again.
Writes data/raw/govinfo/selected.json (what app/ingest/run.py will load) and finishes with
a dry run of the parsers: the real chunk count, before any embedding.
"""

import json
import pathlib
import re
import time
import urllib.error

from app.ingest.govinfo import parse_cfr_part, parse_statute
from scripts.fetch_ecfr import PARTS, get

OUT = pathlib.Path("data/raw/govinfo")
LINK = "https://www.govinfo.gov/link/cfr/29/{part}?year={year}&link-type=pdf"
STATUTE = "https://www.govinfo.gov/content/pkg/STATUTE-{volume}/pdf/STATUTE-{volume}-Pg{page}.pdf"

# Each year shows a different version of a rule that changed: 1997 the old salary tests;
# 2002 the rewritten injury recordkeeping rule (Part 1904); 2005 the 2004 overtime rule;
# 2010 the 2008 FMLA rule; 2015 the first contractor minimum wage rule (Part 10); 2020 the
# 2019 overtime rule; 2025 the 2024 overtime rule, printed although a court vacated it.
YEARS = [1997, 2002, 2005, 2010, 2015, 2020, 2025]

# govinfo's files for these lack the part's first page (heading and opening sections), so
# parsing them would silently lose text. (year, part) -> reason.
EXCLUDED = {
    (1997, 785): "file starts in the middle of the table of contents",
    (1997, 579): "file starts in the middle of § 579.2",
}
# The link service answers 400 for these although the file exists. (year, part) -> URL.
SOURCE_OVERRIDES = {
    (2025, 4): "https://www.govinfo.gov/content/pkg/CFR-2025-title29-vol1/pdf/CFR-2025-title29-vol1-part4.pdf",
}

STATUTES = [
    ("84-381", 69, 711, "1955-08-12", "Fair Labor Standards Amendments of 1955", "Wage and hour (FLSA)"),
    ("87-30", 75, 65, "1961-05-05", "Fair Labor Standards Amendments of 1961", "Wage and hour (FLSA)"),
    ("88-38", 77, 56, "1963-06-10", "Equal Pay Act of 1963", "Wage and hour (FLSA)"),
    ("89-286", 79, 1034, "1965-10-22", "Service Contract Act of 1965", "Federal contracts"),
    ("89-601", 80, 830, "1966-09-23", "Fair Labor Standards Amendments of 1966", "Wage and hour (FLSA)"),
    ("91-596", 84, 1590, "1970-12-29", "Occupational Safety and Health Act of 1970", "Safety and health (OSHA)"),
    ("93-259", 88, 55, "1974-04-08", "Fair Labor Standards Amendments of 1974", "Wage and hour (FLSA)"),
    ("95-151", 91, 1245, "1977-11-01", "Fair Labor Standards Amendments of 1977", "Wage and hour (FLSA)"),
    ("99-150", 99, 787, "1985-11-13", "Fair Labor Standards Amendments of 1985", "Wage and hour (FLSA)"),
    ("100-347", 102, 646, "1988-06-27", "Employee Polygraph Protection Act of 1988", "Polygraph protection (EPPA)"),
    ("101-157", 103, 938, "1989-11-17", "Fair Labor Standards Amendments of 1989", "Wage and hour (FLSA)"),
    ("103-3", 107, 6, "1993-02-05", "Family and Medical Leave Act of 1993", "Family and medical leave (FMLA)"),
]


def cfr_entries() -> list[dict]:
    return [
        {
            "kind": "cfr",
            "part": str(part),
            "year": year,
            "category": category,
            "source_url": SOURCE_OVERRIDES.get((year, part), LINK.format(part=part, year=year)),
            "file": f"cfr/{year}-{part}.pdf",
        }
        for year in YEARS
        for category, parts in PARTS.items()
        for part in parts
        if (year, part) not in EXCLUDED
    ]


def statute_entries() -> list[dict]:
    return [
        {
            "kind": "statute",
            "public_law": public_law,
            "volume": volume,
            "page": page,
            "enacted": enacted,
            "name": name,
            "category": category,
            "source_url": STATUTE.format(volume=volume, page=page),
            "file": f"statutes/{volume}-{page}.pdf",
        }
        for public_law, volume, page, enacted, name, category in STATUTES
    ]


def download(entries: list[dict]) -> list[dict]:
    """Download what is missing; return the entries whose PDF is on disk."""
    kept = []
    for i, entry in enumerate(entries, 1):
        path = OUT / entry["file"]
        label = f"[{i:>3}/{len(entries)}] {entry['file']:<22}"
        if not path.exists():
            try:
                blob = get(entry["source_url"])
            except urllib.error.HTTPError as exc:
                print(f"  {label} missing (HTTP {exc.code})")
                time.sleep(1)
                continue
            if not blob.startswith(b"%PDF"):
                print(f"  {label} not a PDF ({blob[:40]!r})")
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            # A crash mid-write must not leave a partial file that the next run would
            # mistake for a finished download.
            tmp = path.with_suffix(".part")
            tmp.write_bytes(blob)
            tmp.replace(path)
            print(f"  {label} {len(blob) // 1024:>6} KB")
            time.sleep(1)  # be polite to a free public service
        kept.append(entry)
    return kept


def dry_run(entries: list[dict]) -> None:
    stats: dict[str, list[int]] = {}  # group -> [documents, chunks]
    failed, empty, warnings = [], [], []
    longest = 0
    for entry in entries:
        pdf = (OUT / entry["file"]).read_bytes()
        try:
            if entry["kind"] == "cfr":
                doc = parse_cfr_part(pdf, entry)
                group = str(entry["year"])
            else:
                doc = parse_statute(pdf, entry)
                group = "statutes"
        except Exception as exc:  # report every bad document, not just the first
            failed.append(f"{entry['file']}: {type(exc).__name__}: {exc}")
            continue
        if not doc.chunks:
            empty.append(entry["file"])
            continue
        if entry["kind"] == "statute":
            # The law should end with its own approval date; another date means the
            # citation points at a different law, or the end was cut in the wrong place.
            last = " ".join(doc.chunks[-1].content.split())
            year = entry["enacted"][:4]
            if not re.search(rf"Approved [A-Z][a-z]+\.? \d{{1,2}}, ?{year}\.?$", last):
                warnings.append(f"{entry['file']}: ends with ...{last[-60:]!r}")
        stats.setdefault(group, [0, 0])
        stats[group][0] += 1
        stats[group][1] += len(doc.chunks)
        longest = max([longest, *(len(c.content) for c in doc.chunks)])

    print("\ngroup       documents  chunks")
    for group, (docs, chunks) in stats.items():
        print(f"{group:<10} {docs:>10} {chunks:>7}")
    total_docs = sum(d for d, _ in stats.values())
    total_chunks = sum(c for _, c in stats.values())
    size_mb = sum(p.stat().st_size for p in OUT.rglob("*.pdf")) / 1_048_576
    print(f"{'total':<10} {total_docs:>10} {total_chunks:>7}   ({size_mb:.0f} MB of PDF, longest chunk {longest} characters)")
    for title, lines in [("failed to parse", failed), ("no chunks", empty), ("warnings", warnings)]:
        print(f"{len(lines)} {title}")
        for line in lines:
            print("  " + line)


def main() -> None:
    entries = cfr_entries() + statute_entries()
    print(f"{len(entries)} PDFs requested ({len(EXCLUDED)} excluded)")
    kept = download(entries)
    print(f"{len(kept)} on disk, {len(entries) - len(kept)} missing")
    # run.py reads this list, so ingest uses exactly what was downloaded.
    (OUT / "selected.json").write_text(json.dumps(kept, indent=2), encoding="utf-8")
    dry_run(kept)


if __name__ == "__main__":
    main()
