"""Compare the hand grades in eval/calibration.csv with a run's judge verdicts (step 9c).

Reports exact agreement, Cohen's kappa, agreement on correct vs not correct (what strict
accuracy counts), a confusion table, and every question where the two disagree.

Run: uv run python -m eval.calibration_report <results csv> [<hand-graded sheet>]
    uv run python -m eval.calibration_report eval/results/2026-11-21-baseline.csv
    uv run python -m eval.calibration_report eval/results/2026-11-21-baseline-judge2.csv eval/calibration_holdout.csv
"""

import csv
import pathlib
import sys
from collections import Counter

from eval.metrics import VERDICTS


def read(path: pathlib.Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def kappa(pairs: list[tuple[str, str]]) -> float:
    n = len(pairs)
    observed = sum(a == b for a, b in pairs) / n
    human, judge = Counter(a for a, _ in pairs), Counter(b for _, b in pairs)
    expected = sum(human[v] * judge[v] for v in VERDICTS) / n**2
    return (observed - expected) / (1 - expected) if expected < 1 else 1.0


def main() -> None:
    if len(sys.argv) not in (2, 3):
        raise SystemExit(__doc__)
    sheet = pathlib.Path(sys.argv[2] if len(sys.argv) == 3 else "eval/calibration.csv")
    results = {r["id"]: r for r in read(pathlib.Path(sys.argv[1]))}
    graded = [r for r in read(sheet) if r["human_verdict"].strip()]
    pairs, disagreements = [], []
    for r in graded:
        human = r["human_verdict"].strip().lower()
        judge = results[r["id"]]["verdict"]
        if human not in VERDICTS:
            raise SystemExit(f"{r['id']}: unknown hand grade {human!r}")
        pairs.append((human, judge))
        if human != judge:
            disagreements.append((r["id"], r["type"], human, judge, results[r["id"]]["reason"]))

    n = len(pairs)
    exact = sum(a == b for a, b in pairs)
    binary = sum((a == "correct") == (b == "correct") for a, b in pairs)
    print(f"{n} hand-graded answers")
    print(f"  exact agreement           {exact}/{n} ({exact / n:.0%})")
    print(f"  Cohen's kappa             {kappa(pairs):.2f}")
    print(f"  correct vs not correct    {binary}/{n} ({binary / n:.0%})")
    print("\n  human \\ judge   " + "".join(f"{v:>10}" for v in VERDICTS))
    table = Counter(pairs)
    for h in VERDICTS:
        print(f"  {h:<15} " + "".join(f"{table[(h, j)]:>10}" for j in VERDICTS))
    if disagreements:
        print("\nDisagreements:")
        for id_, type_, human, judge, reason in disagreements:
            print(f"  {id_} ({type_}): human {human}, judge {judge}\n    judge: {reason}")


if __name__ == "__main__":
    main()
