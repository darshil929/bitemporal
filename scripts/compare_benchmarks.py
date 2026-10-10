"""Compares Google Benchmark runs of a change with runs of its base, benchmark by benchmark.

Each side is the median real time over its runs, so one slow run on a shared machine does not decide
the comparison. Prints a Markdown table; with --fail, exits 1 when a benchmark whose name --gated
matches is slower than its base by more than the threshold.
"""

import argparse
import json
import re
import statistics
import sys
from dataclasses import dataclass
from pathlib import Path

DEFAULT_THRESHOLD = 0.10
EVERY_BENCHMARK = ".*"


@dataclass(frozen=True)
class Comparison:
    name: str
    base: float | None
    change: float

    @property
    def ratio(self) -> float | None:
        return None if self.base is None else self.change / self.base


def real_times(outputs: list[Path]) -> dict[str, list[float]]:
    """Each benchmark's real time in every run, in the order the benchmarks first appear."""
    times: dict[str, list[float]] = {}
    for output in outputs:
        for run in json.loads(output.read_text())["benchmarks"]:
            if run.get("run_type", "iteration") == "iteration":
                times.setdefault(run["name"], []).append(float(run["real_time"]))
    return times


def compare(base: dict[str, list[float]], change: dict[str, list[float]]) -> list[Comparison]:
    return [
        Comparison(
            name=name,
            base=statistics.median(base[name]) if name in base else None,
            change=statistics.median(times),
        )
        for name, times in change.items()
    ]


def regressions(
    comparisons: list[Comparison], threshold: float, gated: str = EVERY_BENCHMARK
) -> list[Comparison]:
    return [
        c
        for c in comparisons
        if c.ratio is not None and c.ratio > 1 + threshold and re.search(gated, c.name)
    ]


def table(comparisons: list[Comparison], threshold: float, gated: str = EVERY_BENCHMARK) -> str:
    slower = {c.name for c in regressions(comparisons, threshold, gated)}
    lines = ["| Benchmark | Base | Change | Change / base |", "|---|---|---|---|"]
    for c in comparisons:
        base = "new" if c.base is None else f"{c.base:.3f}"
        ratio = "" if c.ratio is None else f"{c.ratio:.3f}"
        marker = f" slower by more than {threshold:.0%}" if c.name in slower else ""
        lines.append(f"| {c.name} | {base} | {c.change:.3f} | {ratio}{marker} |")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", nargs="+", type=Path, required=True)
    parser.add_argument("--change", nargs="+", type=Path, required=True)
    parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD)
    parser.add_argument("--fail", action="store_true", help="exit 1 on a regression")
    parser.add_argument(
        "--gated", default=EVERY_BENCHMARK, help="pattern of the benchmark names held to the base"
    )
    args = parser.parse_args(argv)

    comparisons = compare(real_times(args.base), real_times(args.change))
    print(table(comparisons, args.threshold, args.gated))
    return 1 if args.fail and regressions(comparisons, args.threshold, args.gated) else 0


if __name__ == "__main__":
    sys.exit(main())
