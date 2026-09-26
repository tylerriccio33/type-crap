"""RD005-RD006: runtime checks that repeat the annotation."""

import pytest


def test_rd005_dead_none_guard(check):
    out = check(
        """
        def f(x: str) -> str:
            if x is None:
                raise ValueError
            return x
        """
    )
    assert out == [
        "RD005 `f` tests `x is None` at line 3 but `x: str` can't be None;"
        " drop the check or annotate `| None`"
    ]


def test_rd005_anywhere_in_body(codes):
    assert codes(
        """
        def f(x: int, y: int) -> int:
            total = y
            return total if x is not None else 0
        """
    ) == ["RD005"]


@pytest.mark.parametrize(
    "src",
    [
        "def f(x: str = None):\n    if x is None:\n        x = ''\n",  # implicit Optional
        "def f(x: Any):\n    if x is None:\n        pass\n",
        "def f(x: object):\n    if x is None:\n        pass\n",
        "def f[T](x: T):\n    if x is None:\n        pass\n",
        "T = TypeVar('T')\ndef f(x: T):\n    if x is None:\n        pass\n",
        "def f(x: str):\n    x = g()\n    if x is None:\n        pass\n",  # reassigned
        "def f(x: str):\n    def g(x=None):\n        return x is None\n",  # nested scope
        "def f(x):\n    if x is None:\n        pass\n",  # unannotated
        "if TYPE_CHECKING:\n    V = int | None\ndef f(x: V):\n    if x is None:\n        pass\n",
        "type V = int | None\ndef f(x: V):\n    if x is None:\n        pass\n",
    ],
)
def test_rd005_fine(codes, src):
    assert "RD005" not in codes(src)


def test_rd006_redundant_isinstance(check):
    out = check(
        """
        def f(x: int) -> int:
            if not isinstance(x, int):
                raise TypeError
            return x
        """
    )
    assert out == [
        "RD006 `f` re-checks `isinstance(x, int)` at line 3 but the annotation already says so;"
        " drop the check"
    ]


def test_rd006_assert_and_tuple(codes):
    assert codes(
        """
        def f(x: float) -> float:
            assert isinstance(x, (int, float))
            return x
        """
    ) == ["RD006"]


def test_rd006_other_type_is_fine(codes):
    assert not codes(
        """
        def f(x: Base) -> None:
            if not isinstance(x, Sub):
                raise TypeError
        """
    )


def test_rd006_noqa(codes):
    assert not codes(
        """
        def f(x: int) -> int:  # noqa: RD006
            assert isinstance(x, int)
            return x
        """
    )
