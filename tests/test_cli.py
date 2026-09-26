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


RD_SRC = """
def g(d, k):
    if k not in d:
        raise KeyError(k)
    return d[k]
"""


def test_cli_rd_on_by_default(tmp_path, capsys):
    f = tmp_path / "m.py"
    f.write_text(textwrap.dedent(SRC + RD_SRC))
    assert main([str(f)]) == 1
    out = capsys.readouterr().out
    assert "NU001" in out and "RD001" in out


def test_cli_select_prefix(tmp_path, capsys):
    f = tmp_path / "m.py"
    f.write_text(textwrap.dedent(SRC + RD_SRC))
    main(["--select", "rd", str(f)])
    out = capsys.readouterr().out
    assert "RD001" in out and "NU0" not in out


def test_cli_ignore(tmp_path, capsys):
    f = tmp_path / "m.py"
    f.write_text(textwrap.dedent(SRC + RD_SRC))
    main(["--ignore", "RD001,NU003", str(f)])
    out = capsys.readouterr().out
    assert "NU001" in out and "RD001" not in out and "NU003" not in out


def test_cli_exclude(tmp_path, capsys):
    (tmp_path / "keep.py").write_text(textwrap.dedent(RD_SRC))
    (tmp_path / "vendor").mkdir()
    (tmp_path / "vendor" / "skip.py").write_text(textwrap.dedent(RD_SRC))
    (tmp_path / "gen_api.py").write_text(textwrap.dedent(RD_SRC))
    main(["--exclude", "vendor", "--exclude", "gen_*.py", str(tmp_path)])
    cap = capsys.readouterr()
    assert "keep.py" in cap.out and "skip.py" not in cap.out and "gen_api" not in cap.out
    assert "in 1 file(s)" in cap.err
