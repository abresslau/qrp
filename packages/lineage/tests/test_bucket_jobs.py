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
    _window,
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


# --- window translation (AC#3) ----------------------------------------------------------

def test_window_single_day_default():
    assert _window("2026-06-20") == ("2026-06-19", "2026-06-20")


def test_window_rates_12_day_tail():
    assert _window("2026-06-20", days=12) == ("2026-06-08", "2026-06-20")


def test_equity_one_scopes_universe_and_windows():
    cmds = _flat(_equity_one("sp500", "2026-06-20"))
    assert cmds == [("sym.cli", "load", "--scope", "universe:sp500",
                     "--start_date", "2026-06-19", "--end_date", "2026-06-20")]


def test_rates_one_country_then_validate():
    de = _flat(_rates_one("DE", "2026-06-20"))
    assert de[0][:4] == ("rates.cli", "curve", "load-world", "--country")
    assert "DE" in de[0] and "2026-06-08" in de[0]  # 12-day tail start
    assert de[-1] == ("rates.cli", "validate", "!")  # validate is critical
    gb = _flat(_rates_one("GB", "2026-06-20"))
    assert gb[0] == ("rates.cli", "curve", "load")  # GB on the BoE-archive path
    assert gb[-1] == ("rates.cli", "validate", "!")


def test_calc_returns_is_critical_and_windowed():
    c = _flat(_calc_cmds("returns", "2026-06-20"))
    assert c[0][-1] == "!"  # recompute marked critical
    assert "--start_date" in c[0] and "--end_date" in c[0]
    assert _calc_cmds("gics", "2026-06-20") == [("sym.cli", "classify")]
    assert _calc_cmds("bogus", "2026-06-20") == []  # unknown calc type → no command


# --- _run_bucket: validation + attempt-all (AC#2, #4) ------------------------------------

def test_unknown_subcategory_rejected():
    with pytest.raises(RuntimeError, match="unknown subcategor"):
        _run_bucket(_Ctx(), "calculations", BucketConfig(subcategories=["bogus"]))


def test_invalid_as_of_date_rejected():
    with pytest.raises(RuntimeError, match="invalid as_of_date"):
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
