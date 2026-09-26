"""RD001-RD004: guards and handlers that redo what Python already does."""

import pytest


@pytest.mark.parametrize(
    "src",
    [
        """
        def f(d, k):
            if k not in d:
                raise KeyError(k)
            return d[k]
        """,
        """
        def f(d, k):
            if k in d:
                return d[k]
            raise KeyError(k)
        """,
        """
        def f(d, k):
            if k in d:
                return d[k]
            else:
                raise KeyError(f"missing {k}")
        """,
        """
        def f(d, k):
            if not k in d:
                raise KeyError
            return d[k]
        """,
    ],
)
def test_rd001_membership_then_keyerror(codes, src):
    assert codes(src) == ["RD001"]


def test_rd001_message(check):
    out = check(
        """
        def f(d, k):
            if k not in d:
                raise KeyError(k)
            return d[k]
        """
    )
    assert out == [
        "RD001 checks before `d[k]` only to raise KeyError; `d[k]` already raises KeyError,"
        " drop the guard"
    ]


def test_rd001_different_exception_is_fine(codes):
    assert not codes(
        """
        def f(d, k):
            if k not in d:
                raise ValueError(f"unknown option {k}")
            return d[k]
        """
    )


def test_rd001_positive_guard_that_falls_through_is_fine(codes):
    assert not codes(
        """
        def f(d, k):
            if k in d:
                log(k)
            raise KeyError(k)
        """
    )


def test_rd002_hasattr(check):
    out = check(
        """
        def f(o):
            if not hasattr(o, "name"):
                raise AttributeError("name")
            return o.name
        """
    )
    assert out == [
        "RD002 checks before `o.name` only to raise AttributeError; `o.name` already raises"
        " AttributeError, drop the guard"
    ]


def test_rd002_hasattr_with_fallback_is_fine(codes):
    assert not codes(
        """
        def f(o):
            if hasattr(o, "name"):
                return o.name
            return "anon"
        """
    )


@pytest.mark.parametrize(
    "test",
    ["i >= len(xs)", "not 0 <= i < len(xs)", "len(xs) <= i"],
)
def test_rd003_bounds(codes, test):
    assert codes(
        f"""
        def f(xs, i):
            if {test}:
                raise IndexError(i)
            return xs[i]
        """
    ) == ["RD003"]


def test_rd003_else_form(codes):
    assert codes(
        """
        def f(xs, i):
            if 0 <= i < len(xs):
                return xs[i]
            else:
                raise IndexError
        """
    ) == ["RD003"]


def test_rd003_bounds_with_default_is_fine(codes):
    assert not codes(
        """
        def f(xs, i):
            if i >= len(xs):
                return None
            return xs[i]
        """
    )


@pytest.mark.parametrize(
    "handler, how",
    [
        ("except KeyError:\n        raise", "re-raises it"),
        ("except KeyError as ke:\n        raise ke", "re-raises `ke`"),
        ("except KeyError:\n        raise KeyError(k)", "raises a new KeyError with nothing added"),
        (
            "except KeyError as e:\n        raise KeyError(str(e)) from e",
            "raises a new KeyError with nothing added",
        ),
    ],
)
def test_rd004_same_type(check, handler, how):
    out = check(
        f"""
def f(d, k):
    try:
        return d[k]
    {handler}
"""
    )
    assert out == [f"RD004 catches KeyError and {how}; drop the try/except"]


def test_rd004_with_finally(check):
    out = check(
        """
        def f(d, k):
            try:
                return d[k]
            except KeyError:
                raise
            finally:
                cleanup()
        """
    )
    assert out == ["RD004 catches KeyError and re-raises it; drop the except clause"]


@pytest.mark.parametrize(
    "src",
    [
        # translated to a different type: that's the point of the handler
        """
        def f(d, k):
            try:
                return d[k]
            except KeyError as e:
                raise ConfigError(k) from e
        """,
        # rebuilt with a message that tells the reader something
        """
        def f(o, name):
            try:
                return getattr(o, name)
            except AttributeError as e:
                raise AttributeError(f"{type(o).__name__} has no {name!r}") from e
        """,
        # bare raise that shields a later, broader handler
        """
        def f(d, k):
            try:
                return d[k]
            except KeyError:
                raise
            except Exception:
                return None
        """,
        # does something before re-raising
        """
        def f(d, k):
            try:
                return d[k]
            except KeyError:
                log(k)
                raise
        """,
    ],
)
def test_rd004_fine(codes, src):
    assert codes(src) == []


def test_rd_noqa_on_line(codes):
    assert not codes(
        """
        def f(d, k):
            if k not in d:  # noqa: RD001
                raise KeyError(k)
            return d[k]
        """
    )


@pytest.mark.parametrize(
    "src",
    [
        # guard protects a different operation than the one that would raise
        """
        def f(self, name):
            if name not in self.sections:
                raise KeyError(name)
            return SectionWrapper(self, name)
        """,
        """
        def f(self, lineno):
            if not (0 <= lineno < len(self)):
                raise IndexError("lineno out of range")
            return statement_range(lineno, self)
        """,
        """
        def f(o):
            if not hasattr(o, "name"):
                raise AttributeError("name")
            return describe(o)
        """,
    ],
)
def test_guard_without_the_access_is_fine(codes, src):
    assert not codes(src)
