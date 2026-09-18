"""NU003: `-> X | None` but None can never come out."""


def test_arith_return(check):
    out = check(
        """
        def f(x: int) -> int | None:
            return x + 1
        """
    )
    assert len(out) == 1
    assert out[0].startswith("NU003")
    assert "use `-> int`" in out[0]


def test_constructor_calls_are_not_none(codes):
    assert codes(
        """
        class Foo: ...
        def f(x: int) -> Foo | None:
            if x:
                return Foo()
            return Foo()
        """
    ) == ["NU003"]


def test_builtin_ctor(codes):
    assert codes(
        """
        def f(x: object) -> str | None:
            return str(x)
        """
    ) == ["NU003"]


def test_falls_off_end_is_reachable_none(codes):
    assert (
        codes(
            """
        def f(x: int) -> int | None:
            if x:
                return x
        """
        )
        == []
    )


def test_explicit_none_is_honest(codes):
    assert (
        codes(
            """
        def f(x: int) -> int | None:
            if x > 0:
                return x
            return None
        """
        )
        == []
    )


def test_opaque_call_is_silent_in_strict(codes):
    assert (
        codes(
            """
        def f(x: str) -> str | None:
            return lookup(x)
        """
        )
        == []
    )


def test_opaque_call_fires_in_loose(codes):
    assert codes(
        """
        def f(x: str) -> str | None:
            return lookup(x)
        """,
        loose=True,
    ) == ["NU003"]


def test_bare_none_return_annotation_is_not_a_union(codes):
    assert (
        codes(
            """
        def f(x: str | None) -> None:
            if x is None:
                return None
            print(x)
        """
        )
        == []
    )


def test_or_expression_last_arm_decides(codes):
    assert (
        codes(
            """
        def f(x: str) -> str | None:
            return x or None
        """
        )
        == []
    )


def test_if_else_both_terminate(codes):
    assert codes(
        """
        def f(x: int) -> int | None:
            if x:
                return 1
            else:
                return 2
        """
    ) == ["NU003"]


def test_match_with_wildcard_terminates(codes):
    assert codes(
        """
        def f(x: int) -> int | None:
            match x:
                case 1:
                    return 1
                case _:
                    return 2
        """
    ) == ["NU003"]


def test_match_without_wildcard_can_fall_off(codes):
    assert (
        codes(
            """
        def f(x: int) -> int | None:
            match x:
                case 1:
                    return 1
        """
        )
        == []
    )


def test_try_all_paths_terminate(codes):
    assert codes(
        """
        def f(x: str) -> int | None:
            try:
                return int(x)
            except ValueError:
                return 0
        """
    ) == ["NU003"]
