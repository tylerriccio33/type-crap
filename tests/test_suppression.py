"""noqa, @overload, stubs, methods."""


def test_noqa_specific_code(codes):
    assert (
        codes(
            """
        def f(x: str | None) -> str | None:  # noqa: NU001
            if x is None:
                return None
            return x
        """
        )
        == []
    )


def test_noqa_other_code_does_not_silence(codes):
    assert codes(
        """
        def f(x: str | None) -> str | None:  # noqa: NU003
            if x is None:
                return None
            return x
        """
    ) == ["NU001"]


def test_bare_noqa(codes):
    assert (
        codes(
            """
        def f(x: int) -> int | None:  # noqa
            return x
        """
        )
        == []
    )


def test_overloads_are_skipped(codes):
    assert (
        codes(
            """
        from typing import overload
        @overload
        def f(x: None) -> None: ...
        @overload
        def f(x: str) -> str: ...
        def f(x: str | None) -> str | None:
            if x is None:
                return None
            return x
        """
        )
        == []
    )


def test_stub_bodies_are_skipped(codes):
    assert (
        codes(
            """
        def f(x: str | None) -> str | None: ...
        def g(x: str | None) -> str | None:
            '''doc'''
        """
        )
        == []
    )


def test_methods_and_nested_functions(check):
    out = check(
        """
        class C:
            def m(self, x: int | None) -> int | None:
                if x is None:
                    return None
                return x

        def outer():
            def inner(refs: list[int] | None) -> int:
                if refs is None:
                    raise ValueError
                return len(refs)
        """
    )
    assert [x.split()[0] for x in out] == ["NU001", "NU002"]
    assert "`m`" in out[0] and "`inner`" in out[1]
