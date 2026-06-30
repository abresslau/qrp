"""Part A — the nine config-driven bucket jobs. DB-free (no subprocess, no Dagster runtime).

Covers AC#8: config default (empty ⇒ all), explicit subset honored + unknown rejected,
single-as_of_date → window translation, and attempt-all isolation (one command failing does not
abort the rest; an all-failed or empty plan raises). Also the review patches: as_of validation,
empty-plan-fails, deferred-selection honesty, recompute-critical+windowed.
"""

import pytest

import lineage.bucket_jobs as bj
from lineage.bucket_jobs import (
    BucketConfig,
    _calc_cmds,
    _equity_one,
    _rates_one,
    _run_bucket,
    _tail,
    resolve_window,
)


def _flat(cmds):
    return [tuple(c) for c in cmds]


class _Log:
    def info(self, *a, **k):
        pass

    warning = error = info


class _Ctx:
    log = _Log()
    run = None  # _resolve_as_of falls back to config/today


# --- window resolution (AC#2, #3) -------------------------------------------------------

def test_resolve_window_both_blank_is_single_day_today():
    # all blank → end = today (no scheduled tick on _Ctx.run=None), start = end (single day,
    # so the scheduled nightly run is unchanged).
    s, e = resolve_window(_Ctx())
    assert s == e  # single day
    from datetime import date
    assert e == date.today().isoformat()


def test_resolve_window_explicit_range():
    assert resolve_window(_Ctx(), "2026-06-23", "2026-06-29") == ("2026-06-23", "2026-06-29")


def test_resolve_window_end_only_is_single_day():
    assert resolve_window(_Ctx(), "", "2026-06-29") == ("2026-06-29", "2026-06-29")


def test_resolve_window_as_of_alias_is_single_day():
    assert resolve_window(_Ctx(), as_of_date="2026-06-20") == ("2026-06-20", "2026-06-20")


def test_resolve_window_rejects_inverted_range():
    with pytest.raises(RuntimeError, match="after end_date"):
        resolve_window(_Ctx(), "2026-06-29", "2026-06-23")


def test_resolve_window_rejects_bad_date():
    with pytest.raises(RuntimeError, match="invalid date"):
        resolve_window(_Ctx(), end_date="2026-13-99")


def test_tail_pads_back_at_least_n_days_but_keeps_wider_range():
    assert _tail("2026-06-20", "2026-06-20", 12) == ("2026-06-08", "2026-06-20")  # single day → 12d tail
    assert _tail("2026-05-01", "2026-06-20", 12) == ("2026-05-01", "2026-06-20")  # wider range kept


def test_equity_one_scopes_universe_and_passes_window():
    cmds = _flat(_equity_one("sp500", "2026-06-23", "2026-06-29"))
    assert cmds == [("sym.cli", "load", "--scope", "universe:sp500",
                     "--start_date", "2026-06-23", "--end_date", "2026-06-29")]


def test_rates_one_country_then_validate():
    de = _flat(_rates_one("DE", "2026-06-23", "2026-06-29"))
    assert de[0][:4] == ("rates.cli", "curve", "load-world", "--country")
    assert "DE" in de[0] and "2026-06-17" in de[0]  # 12-day tail start (end 06-29 − 12d)
    assert de[-1] == ("rates.cli", "validate", "!")  # validate is critical
    gb = _flat(_rates_one("GB", "2026-06-23", "2026-06-29"))
    assert gb[0] == ("rates.cli", "curve", "load")  # GB on the BoE-archive path
    assert gb[-1] == ("rates.cli", "validate", "!")


def test_calc_returns_is_critical_and_windowed():
    c = _flat(_calc_cmds("returns", "2026-06-23", "2026-06-29"))
    assert c[0][-1] == "!"  # recompute marked critical
    assert c[0][-3:-1] == ("--end_date", "2026-06-29") or "--end_date" in c[0]
    assert "--start_date" in c[0] and "2026-06-23" in c[0]  # window threaded
    assert _calc_cmds("gics", "2026-06-23", "2026-06-29") == [("sym.cli", "classify")]
    assert _calc_cmds("bogus", "2026-06-23", "2026-06-29") == []  # unknown calc type → no command


# --- _run_bucket: validation + attempt-all (AC#2, #4) ------------------------------------

def test_unknown_subcategory_rejected():
    with pytest.raises(RuntimeError, match="unknown subcategor"):
        _run_bucket(_Ctx(), "calculations", BucketConfig(subcategories=["bogus"]))


def test_invalid_as_of_date_rejected():
    with pytest.raises(RuntimeError, match="invalid date"):
        _run_bucket(_Ctx(), "fx", BucketConfig(as_of_date="2026-13-99"))


def test_empty_plan_fails_not_silent_green(monkeypatch):
    # universe discovery returns nothing → the "all" plan is empty → must RAISE, not pass green.
    monkeypatch.setattr(bj, "_discover_universes", lambda: [])
    with pytest.raises(RuntimeError, match="nothing to run"):
        _run_bucket(_Ctx(), "universe", BucketConfig())


def test_empty_config_runs_all(monkeypatch):
    ran = []
    monkeypatch.setattr(bj, "_run_cmd", lambda ctx, cmd: (ran.append(tuple(cmd)) or True))
    _run_bucket(_Ctx(), "fx", BucketConfig())  # empty subcategories ⇒ all
    assert ran == [("sym.cli", "fx", "load")]


def test_known_subset_honored(monkeypatch):
    ran = []
    monkeypatch.setattr(bj, "_run_cmd", lambda ctx, cmd: (ran.append(tuple(cmd)) or True))
    _run_bucket(_Ctx(), "calculations", BucketConfig(subcategories=["returns"], as_of_date="2026-06-20"))
    assert len(ran) == 1 and ran[0][1] == "recompute"  # only the selected subcategory ran


def test_attempt_all_one_failure_does_not_abort(monkeypatch):
    # classify fails, the others succeed → run continues, no raise (ok > 0).
    def fake(ctx, cmd):
        return tuple(cmd)[:2] != ("sym.cli", "classify")
    monkeypatch.setattr(bj, "_run_cmd", fake)
    _run_bucket(_Ctx(), "calculations", BucketConfig(as_of_date="2026-06-20"))  # must not raise


def test_attempt_all_every_command_fails_raises(monkeypatch):
    monkeypatch.setattr(bj, "_run_cmd", lambda ctx, cmd: False)
    with pytest.raises(RuntimeError, match="every command failed"):
        _run_bucket(_Ctx(), "calculations", BucketConfig(as_of_date="2026-06-20"))


def test_single_subcategory_bucket_selection_is_deferred_not_silent(monkeypatch):
    # fx has no per-source selector: a selection must run the whole bucket (one cmd), honestly logged.
    ran = []
    monkeypatch.setattr(bj, "_run_cmd", lambda ctx, cmd: (ran.append(tuple(cmd)) or True))
    _run_bucket(_Ctx(), "fx", BucketConfig(subcategories=["ecb"]))
    assert ran == [("sym.cli", "fx", "load")]


def test_bucket_jobs_use_mnemonic_names_not_bare_keys():
    # the Dagster job names are mnemonic <asset>_<verb> (buckets.JOB_NAMES), distinct from the keys.
    from lineage.bucket_jobs import BUCKET_JOBS

    names = {j.name for j in BUCKET_JOBS}
    assert {"fx_load", "equity_load", "index_load", "rates_load", "fundamental_load",
            "alt_data_load", "macro_load", "universe_load", "calculations"} == names
    # the `rates` bucket job must NOT clash with the scheduled rates pipelines
    assert "rates" not in names and "rates_load" in names


def test_job_name_falls_back_to_key_when_unmapped():
    from lineage.buckets import job_name

    assert job_name("rates") == "rates_load"          # mapped
    assert job_name("calculations") == "calculations"  # unmapped → key (kept per Andre)
    assert job_name("commodities") == "commodities"    # the dedicated job, not a bucket job
