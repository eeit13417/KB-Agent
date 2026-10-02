import http.client
import io
import json
import pathlib
import re
import time
import urllib.error
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor

ENDPOINTS = {
    "law": "https://law.moj.gov.tw/api/Ch/Law/JSON",
    "order": "https://law.moj.gov.tw/api/Ch/Order/JSON",
}
RAW = pathlib.Path("data/raw")
MAX_ATTEMPTS = 3


def download(url: str) -> bytes:
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            with urllib.request.urlopen(url, timeout=300) as resp:
                expected = int(resp.headers.get("Content-Length") or 0)
                blob = resp.read()
            # This server sometimes closes mid-transfer; a short read would otherwise
            # pass silently and produce a half-updated data/raw.
            if expected and len(blob) != expected:
                raise OSError(f"got {len(blob)} of {expected} bytes")
            return blob
        except (urllib.error.URLError, http.client.HTTPException, OSError) as exc:
            if attempt == MAX_ATTEMPTS:
                raise
            delay = 2**attempt
            print(f"{url} failed ({exc}); retrying in {delay}s")
            time.sleep(delay)


def is_current_labor(law: dict) -> bool:
    category = law.get("LawCategory", "")
    return "勞動部" in category and not category.startswith("廢止")


def parse(blob: bytes) -> list[dict]:
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        raw = z.read(z.namelist()[0])
    return json.loads(raw.decode("utf-8-sig"))["Laws"]


def main() -> None:
    # Both endpoints at once: the run is network-bound, the CPU work takes under a second.
    with ThreadPoolExecutor(max_workers=len(ENDPOINTS)) as pool:
        blobs = dict(zip(ENDPOINTS, pool.map(download, ENDPOINTS.values()), strict=True))

    # Download everything before writing anything, so a failure leaves data/raw untouched.
    kept = {kind: [law for law in parse(blob) if is_current_labor(law)] for kind, blob in blobs.items()}

    RAW.mkdir(parents=True, exist_ok=True)
    for kind, laws in kept.items():
        for law in laws:
            slug = re.sub(r"[^\w]", "_", law["LawName"])
            (RAW / f"{slug}.json").write_text(
                json.dumps(law, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        print(f"{kind}: {len(laws)} documents")

    print(f"wrote {sum(len(v) for v in kept.values())} documents to {RAW}")



if __name__ == "__main__":
    main()
