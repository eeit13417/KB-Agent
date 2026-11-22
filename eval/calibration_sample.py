"""Draw the 20 baseline answers a person grades by hand to calibrate the judge (step 9c).

The sample is stratified by question type and by the judge's verdict, so that it holds
answers the judge passed and answers it failed in every type. Non-correct verdicts are
over-sampled (11 of 20, against 38 of 117 in the baseline): those are where a judge mistake
moves the numbers most, and a sample that is mostly "correct" would show agreement that
says little. Agreement is therefore reported per verdict as well as overall.

The sheet is blind: it shows what the judge saw (question, expected behavior, reference
answer, the assistant's answer) and leaves out the judge's verdict and reason.

The holdout sheet (--holdout) is drawn after the judge prompt was revised on the first 20:
8 other answers, graded by the revised judge, in roughly the proportions of its verdicts.
They are only used to check the agreement, never to tune the prompt again.

Run: uv run python -m eval.calibration_sample [--holdout]
Writes: eval/calibration.csv or eval/calibration_holdout.csv (fill in human_verdict, and
human_note where useful)
"""

import argparse
import csv
import pathlib
import random

EVAL = pathlib.Path("eval")
BASELINE = EVAL / "results" / "2026-11-21-baseline.csv"
OUT = EVAL / "calibration.csv"
SEED = 9  # step 9c; fixed so the sample can be drawn again

# (type, judge verdict) -> how many to draw
PLAN = {
    ("current", "correct"): 2, ("current", "partial"): 1, ("current", "incorrect"): 2,
    ("rulemaking", "correct"): 2, ("rulemaking", "incorrect"): 1,
    ("history", "correct"): 1, ("history", "incorrect"): 2,
    ("cross", "correct"): 1, ("cross", "incorrect"): 1,
    ("no_answer", "correct"): 1, ("no_answer", "incorrect"): 1,
    ("colloquial", "correct"): 1, ("colloquial", "partial"): 1,
    ("coreference", "partial"): 1,
    ("injection", "correct"): 1, ("injection", "incorrect"): 1,
}
HOLDOUT_BASELINE = EVAL / "results" / "2026-11-21-baseline-judge2.csv"
HOLDOUT_OUT = EVAL / "calibration_holdout.csv"
HOLDOUT_SEED = 10
HOLDOUT_PLAN = {
    ("current", "correct"): 1, ("rulemaking", "correct"): 1, ("no_answer", "correct"): 1,
    ("cross", "correct"): 1, ("colloquial", "correct"): 1,
    ("coreference", "partial"): 1,
    ("history", "incorrect"): 1, ("current", "incorrect"): 1,
}
FIELDS = [
    "id", "type", "expected_behavior", "question", "previous_question", "expected_answer",
    "answer", "human_verdict", "human_note",
]


def read(path: pathlib.Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--holdout", action="store_true", help="draw the 8-answer holdout sheet")
    args = parser.parse_args()
    if args.holdout:
        baseline, out, seed, plan = HOLDOUT_BASELINE, HOLDOUT_OUT, HOLDOUT_SEED, HOLDOUT_PLAN
        used = {r["id"] for r in read(OUT)}
    else:
        baseline, out, seed, plan, used = BASELINE, OUT, SEED, PLAN, set()
    if out.exists():
        raise SystemExit(f"{out} exists; it may hold your grades. Move it away to draw again.")
    results = read(baseline)
    questions = {r["id"]: r for r in read(EVAL / "testset.csv")}
    rng = random.Random(seed)
    picked = []
    for (type_, verdict), n in plan.items():
        pool = sorted(
            r["id"] for r in results
            if r["type"] == type_ and r["verdict"] == verdict and r["id"] not in used
        )
        picked += rng.sample(pool, n)
    rng.shuffle(picked)  # so the order gives no hint of the judge's verdict

    answers = {r["id"]: r["answer"] for r in results}
    with out.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        for id_ in picked:
            q = questions[id_]
            writer.writerow({
                "id": id_, "type": q["type"], "expected_behavior": q["expected_behavior"],
                "question": q["question"], "previous_question": q["previous_question"],
                "expected_answer": q["expected_answer"], "answer": answers[id_],
                "human_verdict": "", "human_note": "",
            })
    print(f"{len(picked)} answers -> {out}")


if __name__ == "__main__":
    main()
