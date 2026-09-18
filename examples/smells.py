"""Every rule, one function each. Run: type-crap examples/"""


def shout(x: str | None) -> str | None:
    """NU002 + NU003: None is rejected, and the result is never None."""
    if x is None:
        raise ValueError("x is required")
    return x.upper()


def ident(x: str | None) -> str | None:
    """NU001: this is `def ident[T](x: T) -> T` wearing a disguise."""
    if x is None:
        return None
    return x


def lower(name: str | None) -> str | None:
    """NU001, ternary form."""
    return name.lower() if name is not None else None


def sheet(range_: str | None) -> str | None:
    """NU001 with a genuine second None source -> overloads, not a TypeVar."""
    if range_ is None:
        return None
    name, _, _ = range_.partition("$")
    return name or None


def succ(x: int) -> int | None:
    """NU003: `| None` is unreachable."""
    return x + 1


def first_line(text: str | None) -> str:
    """NU004: dereferenced, never checked."""
    return text.splitlines()[0]


def read(path: str | None, strict: bool) -> int:
    """NU002 (conditional): None is only rejected on the strict path."""
    if strict:
        if path is None:
            raise FileNotFoundError
    return 0
