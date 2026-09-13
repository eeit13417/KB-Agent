import io
import json
import pathlib
import re
import urllib.request
import zipfile

URL = "https://law.moj.gov.tw/api/Ch/Law/JSON"
RAW = pathlib.Path("data/raw")


def main() -> None:
    RAW.mkdir(parents=True, exist_ok=True)

    with urllib.request.urlopen(URL, timeout=180) as resp:
        blob = resp.read()

    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        raw = z.read(z.namelist()[0])
    data = json.loads(raw.decode("utf-8-sig"))

    laws = [
        law
        for law in data["Laws"]
        if "勞動部" in law.get("LawCategory", "")
        and not law["LawCategory"].startswith("廢止")
    ]

    for law in laws:
        slug = re.sub(r"[^\w]", "_", law["LawName"])
        path = RAW / f"{slug}.json"
        path.write_text(json.dumps(law, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"wrote {len(laws)} laws to {RAW}")


if __name__ == "__main__":
    main()
