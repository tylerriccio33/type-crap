import textwrap
from pathlib import Path

import pytest

from type_crap import check_source


@pytest.fixture
def check():
    def _check(src: str, *, loose: bool = False) -> list[str]:
        findings = check_source(Path("t.py"), textwrap.dedent(src), loose=loose)
        return [f"{f.code} {f.msg}" for f in findings]

    return _check


@pytest.fixture
def codes(check):
    def _codes(src: str, *, loose: bool = False) -> list[str]:
        return [x.split()[0] for x in check(src, loose=loose)]

    return _codes
