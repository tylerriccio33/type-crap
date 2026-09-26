"""NU005: a union param whose function rejects some of its members."""


def test_isinstance_raise(check):
    out = check(
        """
        def f(x: str | int) -> int:
            if isinstance(x, str):
                raise TypeError("no str")
            return x + 1
        """
    )
    assert out == ["NU005 `f` rejects `x: str` at line 3; annotate `x: int`"]


def test_negated_keeps_listed(check):
    out = check(
        """
        def f(x: str | int | bytes) -> int:
            if not isinstance(x, int):
                raise TypeError
            return x
        """
    )
    assert out == ["NU005 `f` rejects `x: str | bytes` at line 3; annotate `x: int`"]


def test_assert_isinstance(check):
    out = check(
        """
        from typing import Union

        def f(x: Union[str, int, float]) -> None:
            assert isinstance(x, (int, float))
            print(x)
        """
    )
    assert out == ["NU005 `f` rejects `x: str` at line 5; annotate `x: int | float`"]


def test_guards_accumulate(check):
    out = check(
        """
        def f(x: "str | int | bytes") -> int:
            \"\"\"doc\"\"\"
            if isinstance(x, str):
                raise TypeError
            if isinstance(x, bytes):
                raise TypeError
            return x
        """
    )
    assert out == ["NU005 `f` rejects `x: str | bytes` at line 4; annotate `x: int`"]


def test_dispatch_not_flagged(codes):
    assert (
        codes(
            """
        def f(x: str | int) -> str:
            if isinstance(x, str):
                return x
            return str(x)
        """
        )
        == []
    )


def test_guard_after_other_code_not_flagged(codes):
    assert (
        codes(
            """
        def f(x: str | int) -> int:
            log(x)
            if isinstance(x, str):
                raise TypeError
            return x
        """
        )
        == []
    )


def test_rejecting_everything_not_flagged(codes):
    assert (
        codes(
            """
        def f(x: str | int) -> None:
            if isinstance(x, (str, int)):
                raise TypeError
        """
        )
        == []
    )


def test_non_union_not_flagged(codes):
    assert (
        codes(
            """
        def f(x: object) -> None:
            if isinstance(x, str):
                raise TypeError
        """
        )
        == []
    )


def test_isinstance_rejecting_none(check):
    # NU002 only sees `is None`/truthiness guards; isinstance ones land here
    out = check(
        """
        from typing import Optional

        def f(x: Optional[int]) -> int:
            if not isinstance(x, int):
                raise TypeError
            return x
        """
    )
    assert out == ["NU005 `f` rejects `x: None` at line 5; annotate `x: int`"]


def test_noqa(codes):
    assert (
        codes(
            """
        def f(x: str | int) -> int:  # noqa: NU005
            if isinstance(x, str):
                raise TypeError
            return x
        """
        )
        == []
    )


def test_overload_impl_skipped(codes):
    assert (
        codes(
            """
        from typing import overload

        @overload
        def f(x: int) -> int: ...
        @overload
        def f(x: str) -> str: ...
        def f(x: str | int) -> str | int:
            if isinstance(x, bytes):
                raise TypeError
            return x
        """
        )
        == []
    )
