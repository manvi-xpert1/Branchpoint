"""The command-line runner works on the reference experiment (engine only, no server)."""

from pathlib import Path

from app.cli import main

EXAMPLE = str(Path(__file__).resolve().parents[3] / "examples" / "ecommerce.json")


def test_comparison_table(capsys):
    assert main([EXAMPLE]) == 0
    out = capsys.readouterr().out
    assert "DB fails, no intervention       66.7%         10" in out


def test_evaluate_and_sensitivity(capsys):
    assert main([EXAMPLE, "--evaluate", "db-down", "db-down-replica", "db-down-fast-restore"]) == 0
    out = capsys.readouterr().out
    assert "1. DB fails + fast restore at t=8" in out and "[Pareto]" in out
    assert "Compared with DB fails, no intervention" in out
    assert main([EXAMPLE, "--sensitivity", "db-down"]) == 0
    assert "Sensitivity of downtime in 'DB fails, no intervention'" in capsys.readouterr().out
    assert main([EXAMPLE, "--sensitivity", "nope"]) == 1
