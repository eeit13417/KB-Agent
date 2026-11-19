"""Draft candidate test questions from the knowledge base, for a person to review.

Samples chunks from the local database (a fixed seed, so a rerun picks the same ones),
asks the LLM for up to three questions each chunk can answer on its own, and checks that
the quote it gives as evidence is really in the chunk. Every candidate is still reviewed
by hand before it goes into eval/testset.csv; this only saves typing.

Three groups, matching the test set plan:
- current:    one chunk per eCFR part (the regulation in force)
- rulemaking: the summary of Federal Register final and proposed rules
- history:    past CFR editions and enacting laws (searched only with include_history)

Results are appended to eval/candidates.jsonl one chunk at a time, so an interrupted run
(rate limits) resumes where it stopped. eval/candidates.csv is rewritten at the end.

Run: uv run python -m eval.generate_candidates
"""

import csv
import json
import pathlib
import random
import time

from sqlalchemy import func, select

from app.config import settings
from app.db import SessionLocal
from app.models import CURRENT, ENACTED, RULEMAKING, SUPERSEDED, Chunk, Document
from app.rag.generator import get_client

OUT_DIR = pathlib.Path("eval")
JSONL = OUT_DIR / "candidates.jsonl"
CSV = OUT_DIR / "candidates.csv"
SEED = 20261120
MIN_CHARS = 600  # shorter chunks rarely hold a whole answer
PAUSE = 10  # seconds between calls: about 1.2K tokens each, inside Groq's 8K tokens per minute

HISTORY_PARTS = ["541", "785", "825", "1904", "570", "4", "516", "531", "778", "801"]
HISTORY_YEARS = [1997, 2002, 2005, 2010, 2015]
RULEMAKING_FINAL, RULEMAKING_PROPOSED = 8, 4
STATUTES = 6

INSTRUCTIONS = """You write test questions for a question-answering system about U.S. federal
labor regulations. You get one excerpt from its knowledge base. Write up to three questions
that this excerpt alone fully answers.

Rules:
- Ask as an employee, employer or HR person would, in plain English. Never mention "the
  excerpt", "the text" or "this document".
- Each question must have one clear, checkable answer (a number, a date, a yes/no with its
  condition, a named requirement). Skip trivia such as section numbers or headings.
- {context_rule}
- The answer is one or two sentences. The quote is copied word for word from the excerpt
  and is the sentence that proves the answer.
- If the excerpt cannot support a good question, return fewer questions, or none.

Reply with JSON only: {{"questions": [{{"question": "...", "answer": "...", "quote": "..."}}]}}"""

CONTEXT_RULES = {
    "current": "Ask about the rule as it stands; do not mention dates of editions.",
    "rulemaking": (
        "Name the rule in the question by its year and kind, for example 'the 2019 final "
        "rule' or 'the 2023 proposed rule', because proposed rules are not law."
    ),
    "history": (
        "The excerpt is a past version: put its year in the question, for example 'Under "
        "the 1997 rules, ...' or 'What did the Fair Labor Standards Amendments of 1977 "
        "change ...', because the rule today may differ."
    ),
}


def sample_chunks() -> list[tuple[str, dict]]:
    rng = random.Random(SEED)
    picked: list[tuple[str, dict]] = []
    with SessionLocal() as session:

        def rows(*conditions) -> list[dict]:
            statement = (
                select(
                    Chunk.id, Document.title, Document.status, Chunk.article_no,
                    Chunk.chapter, Chunk.content, Document.source_url,
                )
                .join(Chunk.document)
                .where(func.length(Chunk.content) >= MIN_CHARS, *conditions)
                .order_by(Chunk.id)
            )
            return [row._asdict() for row in session.execute(statement)]

        # current: one section per eCFR part, so every topic is represented
        by_part: dict[str, list[dict]] = {}
        for row in rows(Document.status == CURRENT, Chunk.article_no.like("§%")):
            by_part.setdefault(row["title"], []).append(row)
        picked += [("current", rng.choice(chunks)) for _, chunks in sorted(by_part.items())]

        # rulemaking: summaries, which state what a rule does and when
        summaries = rows(Document.status == RULEMAKING, Chunk.article_no == "Summary")
        finals = [r for r in summaries if "(Final rule," in r["title"]]
        proposed = [r for r in summaries if "(Proposed rule," in r["title"]]
        picked += [("rulemaking", r) for r in rng.sample(finals, RULEMAKING_FINAL)]
        picked += [("rulemaking", r) for r in rng.sample(proposed, RULEMAKING_PROPOSED)]

        # history: one past edition of each of these parts, in a random year
        for part in HISTORY_PARTS:
            year = rng.choice(HISTORY_YEARS)
            title = f"29 CFR Part {part} ({year} edition)"
            chunks = rows(Document.status == SUPERSEDED, Document.title == title,
                          Chunk.article_no.like("§%"))
            if chunks:
                picked.append(("history", rng.choice(chunks)))

        # history: one page each from some enacting laws, preferring pages with amounts
        by_law: dict[str, list[dict]] = {}
        for row in rows(Document.status == ENACTED):
            by_law.setdefault(row["title"], []).append(row)
        for title in rng.sample(sorted(by_law), STATUTES):
            pages = [r for r in by_law[title] if "$" in r["content"]] or by_law[title]
            picked.append(("history", rng.choice(pages)))
    return picked


def ask(group: str, chunk: dict) -> list[dict]:
    excerpt = f"Source: {chunk['title']} {chunk['article_no']}\n\n{chunk['content']}"
    response = get_client().chat.completions.create(
        model=settings.groq_model,
        messages=[
            {"role": "system", "content": INSTRUCTIONS.format(context_rule=CONTEXT_RULES[group])},
            {"role": "user", "content": excerpt},
        ],
        response_format={"type": "json_object"},
        temperature=0.3,
    )
    reply = json.loads(response.choices[0].message.content)
    questions = reply.get("questions", []) if isinstance(reply, dict) else reply
    # The model sometimes breaks the format; keep only well-formed items.
    return [q for q in questions if isinstance(q, dict) and q.get("question")]


# Models copy quotes with typographic variants (non-breaking hyphens, curly quotes) that
# would make a faithful quote look invented.
VARIANTS = str.maketrans({"‐": "-", "‑": "-", "‘": "'", "’": "'",
                          "“": '"', "”": '"', " ": " "})


def normalized(text: str) -> str:
    return " ".join(text.translate(VARIANTS).split()).lower()


def main() -> None:
    picked = sample_chunks()
    done = set()
    if JSONL.exists():
        done = {json.loads(line)["chunk_id"] for line in JSONL.read_text(encoding="utf-8").splitlines()}
    todo = [(g, c) for g, c in picked if c["id"] not in done]
    print(f"{len(picked)} chunks sampled, {len(done)} already done, {len(todo)} to ask")

    with JSONL.open("a", encoding="utf-8") as out:
        for i, (group, chunk) in enumerate(todo, 1):
            if i > 1:
                time.sleep(PAUSE)
            try:
                questions = ask(group, chunk)
            except Exception as exc:  # keep going; a rerun retries what failed
                print(f"  [{i}/{len(todo)}] {chunk['title']} {chunk['article_no']}: {exc}")
                continue
            record = {"chunk_id": chunk["id"], "group": group, "chunk": chunk, "questions": questions}
            out.write(json.dumps(record, ensure_ascii=False) + "\n")
            out.flush()
            print(f"  [{i}/{len(todo)}] {group:<10} {chunk['title']} {chunk['article_no']}: {len(questions)}")

    write_csv()


def write_csv() -> None:
    records = [json.loads(line) for line in JSONL.read_text(encoding="utf-8").splitlines()]
    rows = []
    for record in records:
        chunk = record["chunk"]
        for q in record["questions"]:
            if not isinstance(q, dict):  # records written before ask() filtered them
                continue
            rows.append({
                "id": f"c{len(rows) + 1:03d}",
                "group": record["group"],
                "question": q.get("question", ""),
                "answer": q.get("answer", ""),
                "quote": q.get("quote", ""),
                # False means the model's evidence is not in the chunk: check it first.
                "quote_found": normalized(q.get("quote", "")) in normalized(chunk["content"]),
                "source_title": chunk["title"],
                "source_article_no": chunk["article_no"],
                "status": chunk["status"],
                "source_url": chunk["source_url"],
                "keep": "",  # filled in by the reviewer: y / n / edit
                "notes": "",
            })
    # utf-8-sig so that Excel shows §, — and curly quotes correctly
    with CSV.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    by_group = {}
    for row in rows:
        by_group[row["group"]] = by_group.get(row["group"], 0) + 1
    unverified = sum(not row["quote_found"] for row in rows)
    print(f"\n{len(rows)} candidates written to {CSV}: {by_group}; {unverified} with a quote not found")


if __name__ == "__main__":
    main()
