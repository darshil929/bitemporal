import json
from pathlib import Path

import pytest

import compare_benchmarks


def write_run(path: Path, times: dict[str, float], aggregate: float | None = None) -> Path:
    runs = [{"name": name, "run_type": "iteration", "real_time": t} for name, t in times.items()]
    if aggregate is not None:
        runs.append({"name": "Sma20/1_median", "run_type": "aggregate", "real_time": aggregate})
    path.write_text(json.dumps({"benchmarks": runs}))
    return path


def test_each_side_is_the_median_of_its_runs(tmp_path: Path) -> None:
    base = [
        write_run(tmp_path / f"base-{i}.json", {"Sma20/1": t}) for i, t in enumerate((10, 30, 11))
    ]
    change = [
        write_run(tmp_path / f"change-{i}.json", {"Sma20/1": t}) for i, t in enumerate((12, 13, 50))
    ]
    [comparison] = compare_benchmarks.compare(
        compare_benchmarks.real_times(base), compare_benchmarks.real_times(change)
    )
    assert comparison.base == 11
    assert comparison.change == 13
    assert comparison.ratio == 13 / 11


def test_aggregate_rows_are_left_out(tmp_path: Path) -> None:
    run = write_run(tmp_path / "run.json", {"Sma20/1": 10.0}, aggregate=999.0)
    assert compare_benchmarks.real_times([run]) == {"Sma20/1": [10.0]}


def test_a_benchmark_the_base_lacks_is_new(tmp_path: Path) -> None:
    base = write_run(tmp_path / "base.json", {"Sma20/1": 10.0})
    change = write_run(tmp_path / "change.json", {"Sma20/1": 10.0, "Ema20/1": 5.0})
    comparisons = compare_benchmarks.compare(
        compare_benchmarks.real_times([base]), compare_benchmarks.real_times([change])
    )
    assert [c.name for c in comparisons] == ["Sma20/1", "Ema20/1"]
    assert comparisons[1].base is None
    assert "| Ema20/1 | new | 5.000 |  |" in compare_benchmarks.table(comparisons, 0.10)


def test_a_regression_fails_only_when_asked(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    base = write_run(tmp_path / "base.json", {"Sma20/1": 10.0, "Sma20/8": 2.0})
    change = write_run(tmp_path / "change.json", {"Sma20/1": 11.5, "Sma20/8": 2.1})
    files = ["--base", str(base), "--change", str(change)]

    assert compare_benchmarks.main(files) == 0
    assert compare_benchmarks.main([*files, "--fail"]) == 1
    assert compare_benchmarks.main([*files, "--fail", "--threshold", "0.2"]) == 0
    assert (
        "| Sma20/1 | 10.000 | 11.500 | 1.150 slower by more than 10% |" in capsys.readouterr().out
    )


def test_only_gated_benchmarks_fail(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    base = write_run(tmp_path / "base.json", {"Sma20/1/real_time": 10.0, "Sma20/8/real_time": 2.0})
    change = write_run(
        tmp_path / "change.json", {"Sma20/1/real_time": 10.5, "Sma20/8/real_time": 3.0}
    )
    files = ["--base", str(base), "--change", str(change), "--fail", "--threshold", "0.4"]

    assert compare_benchmarks.main([*files, "--gated", "/1/"]) == 0
    assert "slower by more than" not in capsys.readouterr().out
    assert compare_benchmarks.main([*files, "--gated", "/8/"]) == 1
