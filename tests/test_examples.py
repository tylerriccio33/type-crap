"""examples/smells.py must keep hitting every rule, in this order."""

from pathlib import Path

from type_crap import check_source

EXAMPLES = Path(__file__).parent.parent / "examples" / "smells.py"


def test_examples_hit_every_rule():
    findings = check_source(EXAMPLES, EXAMPLES.read_text())
    assert [f.code for f in findings] == [
        "NU002",
        "NU003",
        "NU001",
        "NU001",
        "NU001",
        "NU003",
        "NU004",
        "NU002",
    ]
    assert [f.msg.split("`")[1] for f in findings] == [
        "shout",
        "shout",
        "ident",
        "lower",
        "sheet",
        "succ",
        "first_line",
        "read",
    ]
