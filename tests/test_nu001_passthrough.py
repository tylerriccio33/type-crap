"""NU001: the None in the return type only exists to echo the None in a param."""


def test_pure_passthrough_wants_typevar(check):
    out = check(
        """
        def f(x: str | None) -> str | None:
            if x is None:
                return None
            return x
        """
    )
    assert len(out) == 1
    assert out[0].startswith("NU001")
    assert "def f[T]" in out[0]
    assert "no other None source" in out[0]


def test_ternary_passthrough(check):
    out = check(
        """
        def f(name: str | None) -> str | None:
            return name.lower() if name is not None else None
        """
    )
    assert len(out) == 1
    assert "NU001" in out[0]
    assert "def f[T]" in out[0]
    assert "unverified calls" in out[0]  # .lower() is opaque in strict mode


def test_ternary_passthrough_loose_is_clean(check):
    out = check(
        """
        def f(name: str | None) -> str | None:
            return name.lower() if name is not None else None
        """,
        loose=True,
    )
    assert "unverified" not in out[0]


def test_passthrough_with_other_none_source_wants_overloads(check):
    out = check(
        """
        def f(r: str | None) -> str | None:
            if r is None:
                return None
            sheet, sep, cells = r.partition("$")
            return sheet or None
        """
    )
    assert len(out) == 1
    assert "overloads" in out[0]
    assert "other maybe-None returns at 6" in out[0]


def test_passthrough_that_falls_off_end(check):
    out = check(
        """
        def f(x: str | None) -> str | None:
            if x is None:
                return None
            if x:
                return x
        """
    )
    assert len(out) == 1
    assert "falls off end" in out[0]


def test_returning_another_none_param_counts(check):
    out = check(
        """
        def join(a: str | None, b: str | None) -> str | None:
            if a is None:
                return b
            if b is None or a == b:
                return a
            return a + b
        """
    )
    assert [x.split()[0] for x in out] == ["NU001"]
    assert "for `a`" in out[0]


def test_bare_return_is_passthrough(codes):
    assert codes(
        """
        def f(x: int | None) -> int | None:
            if x is None:
                return
            return x
        """
    ) == ["NU001"]


def test_negated_guard(codes):
    assert codes(
        """
        def f(x: int | None) -> int | None:
            if x is not None:
                return x + 1
            else:
                return None
        """
    ) == ["NU001"]


def test_optional_spelling(codes):
    assert codes(
        """
        from typing import Optional
        def f(x: Optional[int]) -> Optional[int]:
            if x is None:
                return None
            return x
        """
    ) == ["NU001"]


def test_no_guard_no_finding(codes):
    assert (
        codes(
            """
        def f(x: str | None) -> str | None:
            return lookup(x)
        """
        )
        == []
    )


def test_none_handled_with_default_is_fine(codes):
    assert (
        codes(
            """
        def f(x: str | None) -> str:
            if x is None:
                return "default"
            return x
        """
        )
        == []
    )
