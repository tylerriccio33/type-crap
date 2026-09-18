"""NU004: `X | None` param used as if it were `X`, with no None check anywhere."""


def test_attribute_deref(check):
    out = check(
        """
        def f(x: str | None) -> str:
            return x.upper()
        """
    )
    assert len(out) == 1
    assert out[0].startswith("NU004")
    assert "at line 3" in out[0]
    assert "annotate `x: str`" in out[0]


def test_subscript_call_binop_deref(codes):
    assert codes(
        """
        def f(a: list[int] | None, b: int | None, c: object | None) -> int:
            return a[0] + b + len(c())
        """
    ) == ["NU004", "NU004", "NU004"]


def test_for_iter_and_with(codes):
    assert codes(
        """
        def f(xs: list[int] | None, lock: object | None) -> None:
            with lock:
                for x in xs:
                    print(x)
        """
    ) == ["NU004", "NU004"]


def test_ordering_compare_is_a_deref_but_equality_is_a_check(codes):
    assert codes(
        """
        def f(a: int | None, b: int | None) -> bool:
            return a < 3 or b == 3
        """
    ) == ["NU004"]


def test_any_none_check_anywhere_silences(codes):
    assert (
        codes(
            """
        def f(x: str | None) -> str:
            y = x.upper()
            if x is not None:
                return y
            return ""
        """
        )
        == []
    )


def test_truthiness_check_silences(codes):
    assert (
        codes(
            """
        def f(x: str | None) -> str:
            if x:
                return x.upper()
            return ""
        """
        )
        == []
    )


def test_isinstance_silences(codes):
    assert (
        codes(
            """
        def f(x: str | None) -> str:
            if isinstance(x, str):
                return x.upper()
            return ""
        """
        )
        == []
    )


def test_reassignment_silences(codes):
    assert (
        codes(
            """
        def f(x: str | None) -> str:
            x = x or "default"
            return x.upper()
        """
        )
        == []
    )


def test_passing_to_a_function_is_not_a_deref(codes):
    assert (
        codes(
            """
        def f(x: str | None) -> str:
            return g(x)
        """
        )
        == []
    )


def test_raise_guard_is_a_check(codes):
    assert codes(
        """
        def f(x: str | None) -> str:
            if x is None:
                raise ValueError
            return x.upper()
        """
    ) == ["NU002"]


def test_deref_inside_nested_block(check):
    out = check(
        """
        def f(x: str | None, flag: bool) -> str:
            if flag:
                return x.upper()
            return ""
        """
    )
    assert out[0].startswith("NU004")
    assert "at line 4" in out[0]


def test_membership_against_none_is_a_check(codes):
    assert (
        codes(
            """
        def f(path: str | None) -> str:
            if path in (None, "-"):
                return ""
            return path.strip()
        """
        )
        == []
    )


def test_vararg_iteration_is_not_a_deref(codes):
    assert (
        codes(
            """
        def f(*xs: str | None) -> int:
            n = 0
            for x in xs:
                if x is not None:
                    n += 1
            return n
        """
        )
        == []
    )
