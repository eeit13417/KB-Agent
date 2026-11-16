"""Download selected parts of 29 CFR (Labor) from the eCFR API as raw XML.

The XML is saved untouched; splitting into sections happens at ingest time, so
changing the chunker never requires a re-download.
"""

import gzip
import json
import pathlib
import time
import urllib.error
import urllib.request

API = "https://www.ecfr.gov/api/versioner/v1"
TITLE = 29
# Parts that answer everyday workplace questions, grouped by topic.
PARTS = {
    "Wage and hour (FLSA)": [516, 531, 541, 547, 548, 552, 553, 778, 779, 785, 786, 790],
    "Child labor": [570],
    "Penalties": [578, 579],
    "Family and medical leave (FMLA)": [825],
    "Polygraph protection (EPPA)": [801],
    "Federal contracts": [4, 5, 10, 13],
    "Safety and health (OSHA)": [1903, 1904, 1977],
}
OUT = pathlib.Path("data/raw/ecfr")
HEADERS = {"Accept-Encoding": "gzip", "User-Agent": "kb-agent/0.2"}
MAX_ATTEMPTS = 3


def get(url: str) -> bytes:
    request = urllib.request.Request(url, headers=HEADERS)
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            with urllib.request.urlopen(request, timeout=120) as resp:
                body = resp.read()
                # eCFR rejects uncompressed requests, and urllib never decompresses for you.
                if resp.headers.get("Content-Encoding") == "gzip":
                    body = gzip.decompress(body)
                return body
        except urllib.error.HTTPError as exc:
            # 4xx means the request itself is wrong (e.g. a part that doesn't exist); retrying won't help.
            if exc.code < 500 or attempt == MAX_ATTEMPTS:
                raise
        except urllib.error.URLError:
            if attempt == MAX_ATTEMPTS:
                raise
        delay = 2**attempt
        print(f"{url} failed; retrying in {delay}s")
        time.sleep(delay)
    raise AssertionError("unreachable")


def latest_issue_date() -> str:
    # Ask instead of hard-coding: a fixed date would silently freeze the corpus.
    titles = json.loads(get(f"{API}/titles.json"))["titles"]
    return next(t["latest_issue_date"] for t in titles if t["number"] == TITLE)


def main() -> None:
    date = latest_issue_date()
    print(f"Title {TITLE} as of {date}")

    # Download everything first, so a failure leaves data/raw/ecfr untouched.
    blobs: dict[int, bytes] = {}
    topics: dict[int, str] = {}
    for topic, parts in PARTS.items():
        for part in parts:
            blobs[part] = get(f"{API}/full/{date}/title-{TITLE}.xml?part={part}")
            topics[part] = topic
            print(f"  part {part:>4} {len(blobs[part]) // 1024:>4} KB  {topic}")
            time.sleep(0.5)  # be polite to a free public API

    OUT.mkdir(parents=True, exist_ok=True)
    for part, blob in blobs.items():
        (OUT / f"part-{part}.xml").write_bytes(blob)
    index = {"title": TITLE, "date": date, "topics": topics}
    (OUT / "index.json").write_text(json.dumps(index, indent=2), encoding="utf-8")
    print(f"wrote {len(blobs)} parts to {OUT}")


if __name__ == "__main__":
    main()
