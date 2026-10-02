"""Classify downloaded files: text PDFs, scanned PDFs, or non-PDF formats.

Decides where OCR is needed and which files carry no usable text at all.
"""

import collections
import json
import pathlib

import pymupdf

PDF_DIR = pathlib.Path("data/pdf")
REPORT = PDF_DIR / "inspection.json"


def classify(path: pathlib.Path) -> dict:
    if path.suffix.lower() != ".pdf":
        return {"kind": path.suffix.lower().lstrip("."), "pages": 0, "chars": 0}

    with pymupdf.open(path) as doc:
        pages = len(doc)
        chars = sum(len(page.get_text().strip()) for page in doc)
        images = sum(len(page.get_images()) for page in doc)

    per_page = chars / pages if pages else 0
    if per_page >= 200:
        kind = "text"
    elif per_page < 50 and images:
        kind = "scanned"
    else:
        kind = "sparse"

    return {"kind": kind, "pages": pages, "chars": chars, "chars_per_page": round(per_page)}


def main() -> None:
    report = {}
    for path in sorted(PDF_DIR.iterdir()):
        if path.name in {"manifest.json", "inspection.json"}:
            continue
        try:
            report[path.name] = classify(path)
        except Exception as exc:
            report[path.name] = {"kind": "error", "error": type(exc).__name__}

    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    counts = collections.Counter(entry["kind"] for entry in report.values())
    pages = collections.Counter()
    for entry in report.values():
        pages[entry["kind"]] += entry.get("pages", 0)

    print(f"{'kind':10} {'files':>6} {'pages':>7}")
    for kind, count in counts.most_common():
        print(f"{kind:10} {count:>6} {pages[kind]:>7}")

    scanned_pages = pages["scanned"] + pages["sparse"]
    print(f"\nOCR 需要處理 {scanned_pages} 頁，以 9 秒/頁估算約 {scanned_pages * 9 / 60:.0f} 分鐘")


if __name__ == "__main__":
    main()
