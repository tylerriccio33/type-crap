"""NU002: the function doesn't accept None, it rejects it."""


def test_raise_guard(check):
    out = check(
        """
        def f(x: str | None) -> str:
            if x is None:
                raise ValueError("x")
            return x.upper()
        """
    )
    assert len(out) == 1
    assert out[0].startswith("NU002")
    assert "annotate `x: str`" in out[0]


def test_assert_guard(codes):
    assert codes(
        """
        def f(x: int | None) -> int:
            assert x is not None
            return x + 1
        """
    ) == ["NU002"]


def test_falsy_guard(codes):
    assert codes(
        """
        def f(x: str | None) -> str:
            if not x:
                raise ValueError
            return x
        """
    ) == ["NU002"]


def test_raise_after_message_building(codes):
    assert codes(
        """
        def f(x: str | None) -> str:
            if x is None:
                msg = "nope"
                raise ValueError(msg)
            return x
        """
    ) == ["NU002"]


def test_multi_member_union_strips_only_none(check):
    out = check(
        """
        def f(v: str | float | None) -> float:
            if v is None:
                raise TypeError
            return float(v)
        """
    )
    assert "annotate `v: str | float`" in out[0]


def test_nested_raise_is_conditional(check):
    out = check(
        """
        def f(x: str | None) -> str | None:
            for c in x or "":
                if x is None:
                    raise ValueError
        """
    )
    assert len(out) == 1
    assert out[0].startswith("NU002")
    assert "only inside `for`" in out[0]


def test_raise_inside_with_is_unconditional(check):
    out = check(
        """
        def f(x: str | None, lock) -> str:
            with lock:
                if x is None:
                    raise ValueError
                return x
        """
    )
    assert "assert at the call site" in out[0]


def test_raise_after_other_statements_is_unconditional(check):
    out = check(
        """
        def f(x: str | None) -> int:
            y = compute()
            log(y)
            if x is None:
                raise ValueError
            return y
        """
    )
    assert "assert at the call site" in out[0]


def test_raise_inside_if_and_except_names_both(check):
    out = check(
        """
        def f(x: str | None, strict: bool) -> int:
            if strict:
                try:
                    pass
                except Exception:
                    if x is None:
                        raise ValueError
            return 1
        """
    )
    assert "only inside `if/except`" in out[0]


def test_example_one_fires_both_nu002_and_soft_nu003(codes):
    # The shape from the original complaint: reject None, then only return str.
    assert codes(
        """
        def f(x: str | None) -> str | None:
            if x is None:
                raise ValueError
            return x.upper()
        """
    ) == ["NU002", "NU003"]
