import textwrap

from type_crap.cli import main

SRC = """
def a(x: str | None) -> str | None:
    if x is None:
        return None
    return x

def b(x: int) -> int | None:
    return x + 1
"""


def test_cli_reports_and_exits_1(tmp_path, capsys):
    f = tmp_path / "m.py"
    f.write_text(textwrap.dedent(SRC))
    assert main([str(tmp_path)]) == 1
    out = capsys.readouterr()
    lines = out.out.strip().splitlines()
    assert len(lines) == 2
    assert lines[0].startswith(f"{f}:2:0: NU001")
    assert lines[1].startswith(f"{f}:7:0: NU003")
    assert "2 finding(s) in 1 file(s)" in out.err


def test_cli_select(tmp_path, capsys):
    f = tmp_path / "m.py"
    f.write_text(textwrap.dedent(SRC))
    assert main(["--select", "NU003", str(f)]) == 1
    assert capsys.readouterr().out.count("NU0") == 1


def test_cli_clean_exits_0(tmp_path, capsys):
    f = tmp_path / "m.py"
    f.write_text("def f(x: int) -> int:\n    return x\n")
    assert main([str(f)]) == 0
    assert capsys.readouterr().out == ""


def test_cli_skips_syntax_errors(tmp_path, capsys):
    f = tmp_path / "bad.py"
    f.write_text("def (:\n")
    assert main([str(f)]) == 0
    assert "skipped" in capsys.readouterr().err
