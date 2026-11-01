"""The command list a researcher sees first."""

import pytest

from proxy2model.cli import main


def test_overview_lists_every_command(capsys):
    """The short command list hides nothing: everyday commands, then the rest under More."""
    from proxy2model.cli.app import COMMANDS, MORE
    assert main([]) == 1
    out = capsys.readouterr().out
    for name, _ in COMMANDS:
        assert f"  {name} " in out
    assert "More: " + ", ".join(MORE) in out
    for name in MORE:                              # each folded command still explains itself
        with pytest.raises(SystemExit):
            main([name, "--help"])
        assert capsys.readouterr().out.split("\n\n")[1].strip()
