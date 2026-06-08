"""Smoke tests for the CLI scaffold (Story 1.1)."""

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
