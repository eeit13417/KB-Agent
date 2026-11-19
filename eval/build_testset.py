"""Build eval/testset.csv from the three reviewed candidate files.

- eval/candidates.csv: drafted by eval/generate_candidates.py, reviewed by hand. A row is
  kept when `keep` is y or edit; for edit rows, revised_question and revised_answer
  replace the original text where they are filled in.
- eval/hard_candidates.csv: hard questions written by hand (cross-document, no answer,
  colloquial, coreference, injection), reviewed by hand.
- eval/history_extra.csv: history questions whose answer differs from today's rule.

Run: uv run python -m eval.build_testset
"""

import csv
import pathlib
from collections import Counter

EVAL = pathlib.Path("eval")
FIELDS = [
    "id", "type", "question", "previous_question", "expected_answer", "expected_sources",
    "include_history", "expected_behavior", "quick", "notes",
]

# History candidates whose answer is the same as today's rule test little about versions.
# Two are kept as controls (can the system cite the edition it was asked about?); the
# rest are left out. c114: a concrete scenario from a CFR edition; c142: a statute.
HISTORY_CONTROLS = {"c114", "c142"}
SAME_AS_TODAY = {
    "c109", "c114", "c115", "c123", "c125", "c128", "c131", "c132", "c136", "c142", "c143", "c146",
}

# h013 asks for a 2027 threshold. The knowledge base holds the vacated 2024 rule, which
# scheduled an update for July 1, 2027, so the right answer explains that rule's status
# instead of declining: it is a version question, not a no-answer question.
RETYPE = {"h013": "cross"}

# The quick set run on every pull request: 20 questions covering every type, weighted
# toward the version questions this project is about.
QUICK = {
    "h047", "c013", "c031", "c053", "c064",  # current (h047: the 2026-11-18 spot-check failure)
    "c082", "c085", "c099",  # rulemaking: final vs proposed, a vacated rule, a proposal
    "y001", "y003", "c145",  # history
    "h002", "h010", "h013",  # cross-document version conflicts
    "h011", "h019", "h026",  # no answer
    "h029", "h037", "h043",  # colloquial, coreference, injection
}


def read(name: str) -> list[dict]:
    with (EVAL / name).open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def kept(row: dict) -> bool:
    return row["keep"].strip().lower() in ("y", "edit")


def from_candidates() -> list[dict]:
    rows = []
    for r in read("candidates.csv"):
        if not kept(r):
            continue
        if r["id"] in SAME_AS_TODAY and r["id"] not in HISTORY_CONTROLS:
            continue
        rows.append({
            "id": r["id"],
            "type": r["group"],
            "question": r.get("revised_question", "").strip() or r["question"],
            "previous_question": "",
            "expected_answer": r.get("revised_answer", "").strip() or r["answer"],
            "expected_sources": f"{r['source_title']} | {r['source_article_no']}",
            "include_history": "y" if r["status"] in ("superseded", "enacted") else "n",
            "expected_behavior": "answer",
            "notes": r["notes"],
        })
    return rows


def from_written(name: str) -> list[dict]:
    rows = []
    for r in read(name):
        if not kept(r):
            continue
        row = {field: r.get(field, "") for field in FIELDS}
        row["type"] = RETYPE.get(r["id"], r["type"])
        rows.append(row)
    return rows


def main() -> None:
    rows = from_candidates() + from_written("hard_candidates.csv") + from_written("history_extra.csv")
    ids = [r["id"] for r in rows]
    duplicates = [i for i, n in Counter(ids).items() if n > 1]
    missing = QUICK - set(ids)
    if duplicates or missing:
        raise SystemExit(f"duplicate ids {duplicates}; quick-set ids not in the test set {sorted(missing)}")
    for r in rows:
        r["quick"] = "y" if r["id"] in QUICK else "n"

    with (EVAL / "testset.csv").open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    print(f"{len(rows)} questions, {len(QUICK)} in the quick set")
    types = Counter(r["type"] for r in rows)
    quick = Counter(r["type"] for r in rows if r["quick"] == "y")
    for t, n in types.most_common():
        print(f"  {t:<12} {n:>3}   quick {quick[t]}")
    no_answer = types["no_answer"] / len(rows)
    print(f"no-answer share {no_answer:.0%}; need history search: {sum(r['include_history'] == 'y' for r in rows)}")


if __name__ == "__main__":
    main()
