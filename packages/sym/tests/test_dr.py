"""Tests for backup / disaster-recovery tooling (Story 2.9)."""

from __future__ import annotations

from sym.dr import RECOMPUTABLE_TABLES, backup_args, find_pg_dump


def test_backup_excludes_recomputable_fact_returns():
    assert "fact_returns" in RECOMPUTABLE_TABLES
    args = backup_args("out.dump")
    assert "--exclude-table=public.fact_returns" in args


def test_backup_excludes_sqitch_registry():
    assert "--exclude-schema=sqitch" in backup_args("out.dump")


def test_backup_is_custom_format_to_the_output_path():
    args = backup_args("/tmp/sym.dump")
    assert "--format=custom" in args
    assert args[args.index("--file") + 1] == "/tmp/sym.dump"


def test_find_pg_dump_honours_sym_pg_bin(tmp_path, monkeypatch):
    import os

    exe = "pg_dump.exe" if os.name == "nt" else "pg_dump"
    fake = tmp_path / exe
    fake.write_text("")
    monkeypatch.setenv("SYM_PG_BIN", str(tmp_path))
    assert find_pg_dump() == str(fake)
