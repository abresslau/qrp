"""Smoke tests for the CLI scaffold (Story 1.1)."""

import argparse
import contextlib

import psycopg
import pytest

from sym import __version__
from sym.cli import build_parser, main


def test_version_command(capsys):
    rc = main(["version"])
    assert rc == 0
    assert __version__ in capsys.readouterr().out


def test_help_exits_zero(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0


def test_no_command_is_error():
    with pytest.raises(SystemExit) as exc:
        build_parser().parse_args([])
    assert exc.value.code != 0


# --- _cmd_classify report loop + coverage gate (DB-free; chain stubbed) ----------------


def _stub_classify(monkeypatch, *, results, coverage):
    """Wire _cmd_classify's DB + chain dependencies to in-memory stubs.

    ``coverage`` is either an ``(classified, active)`` tuple or an Exception to raise
    from ``read_active_coverage``. The primary summary is fixed; ``results`` is the list
    of PassResult the report loop iterates.
    """
    from sym.classification.gics import ClassificationSummary

    primary = ClassificationSummary(
        active_total=100, classified=99, rows_inserted=5, rows_updated=1, unchanged=93
    )

    monkeypatch.setattr("sym.config.load_dotenv", lambda *a, **k: None)
    monkeypatch.setattr("sym.db.connect", lambda *a, **k: contextlib.nullcontext(object()))
    monkeypatch.setattr(
        "sym.classification.registry.run_classification_chain",
        lambda conn, llm_enabled=False: (primary, results),
    )

    def fake_coverage(conn):
        if isinstance(coverage, Exception):
            raise coverage
        return coverage

    monkeypatch.setattr("sym.classification.gics.read_active_coverage", fake_coverage)


def _all_branch_results():
    from sym.classification.gics import ClassificationSummary
    from sym.classification.registry import PassResult

    ok = ClassificationSummary(active_total=100, classified=99, rows_inserted=3)
    return [
        PassResult("fmp", None, None, 0, True, skip_line="fmp fill pass: skipped — no FMP_API_KEY"),
        PassResult("llm", None, None, 0, True, skip_line=""),  # gated-off + silent
        PassResult("b3", None, "RuntimeError: boom", 0, False),  # error → stderr
        PassResult("sec_sic", None, None, 0, False),  # empty scope → "— not queried"
        PassResult("yahoo_profile", ok, None, 5, False, lines=["yahoo line A", "yahoo line B"]),
    ]


def test_cmd_classify_report_loop_routes_every_branch_to_the_right_stream(monkeypatch, capsys):
    from sym.cli import _cmd_classify

    _stub_classify(monkeypatch, results=_all_branch_results(), coverage=(100, 100))
    rc = _cmd_classify(argparse.Namespace(llm=False))
    out, err = capsys.readouterr()

    assert rc == 0  # coverage 100/100 ≥ threshold
    # stdout: primary summary, skip line, empty-scope "— not queried", success lines, coverage
    assert "classified 99/100" in out
    assert "fmp fill pass: skipped — no FMP_API_KEY" in out
    # exact empty-scope wording is pinned here (the line that drifted once)
    assert "sec_sic fill pass: nothing to fill (no classifiable actives) — not queried" in out
    assert "yahoo line A" in out and "yahoo line B" in out
    assert "whole-universe coverage (all sources): 100/100" in out
    # the silent gated-off llm pass prints nothing
    assert "llm" not in out
    # stderr: ONLY the failed pass
    assert "b3 fill pass FAILED (earlier passes unaffected): RuntimeError: boom" in err
    assert "yahoo line A" not in err


def test_cmd_classify_returns_2_when_coverage_below_threshold(monkeypatch, capsys):
    from sym.cli import _cmd_classify

    _stub_classify(monkeypatch, results=[], coverage=(0, 100))  # 0% coverage
    rc = _cmd_classify(argparse.Namespace(llm=False))
    out, err = capsys.readouterr()

    assert rc == 2
    assert "below the" in err  # the AC #2 threshold message on stderr


def test_cmd_classify_returns_0_when_coverage_read_fails(monkeypatch, capsys):
    from sym.cli import _cmd_classify

    # writes already committed; a coverage-read failure must NOT signal a failed run
    _stub_classify(monkeypatch, results=[], coverage=psycopg.Error("coverage read boom"))
    rc = _cmd_classify(argparse.Namespace(llm=False))
    out, err = capsys.readouterr()

    assert rc == 0
    assert "coverage read failed" in err
    assert "unavailable (coverage read failed)" in out
