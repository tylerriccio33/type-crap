"""An implementation that follows `@overload` stubs of the same name is skipped.

The stubs are the public contract; the implementation's `X | None` signature is
just their union, so none of the rules apply to it.
"""

import textwrap

import pytest

IMPORT = "from typing import overload\n"


def stubs(name: str = "f", self: str = "", deco: str = "@overload") -> str:
    return (
        f"{deco}\ndef {name}({self}x: None) -> None: ...\n"
        f"{deco}\ndef {name}({self}x: str) -> str: ...\n"
    )


def impl(name: str = "f", self: str = "", *, async_: bool = False) -> str:
    kw = "async def" if async_ else "def"
    return (
        f"{kw} {name}({self}x: str | None) -> str | None:\n"
        "    if x is None:\n"
        "        return None\n"
        "    return x\n"
    )


def block(header: str, body: str, indent: str = "    ") -> str:
    return f"{header}\n{textwrap.indent(body, indent)}"


# --- what counts as an overload set ------------------------------------------


@pytest.mark.parametrize(
    "imp, deco",
    [
        ("from typing import overload", "@overload"),
        ("import typing", "@typing.overload"),
        ("import typing as t", "@t.overload"),
        ("from typing_extensions import overload", "@overload"),
    ],
)
def test_overload_decorator_spellings(codes, imp, deco):
    assert codes(f"{imp}\n" + stubs(deco=deco) + impl()) == []


def test_single_overload_stub_is_enough(codes):
    # invalid per typing rules, but that's not this tool's job
    src = IMPORT + "@overload\ndef f(x: None) -> None: ...\n" + impl()
    assert codes(src) == []


def test_impl_may_carry_other_decorators(codes):
    src = IMPORT + "import functools\n" + stubs() + "@functools.cache\n" + impl()
    assert codes(src) == []


def test_stubs_may_carry_other_decorators(codes):
    body = (
        "@overload\n@staticmethod\ndef f(x: None) -> None: ...\n"
        "@staticmethod\n@overload\ndef f(x: str) -> str: ...\n"
        "@staticmethod\n" + impl()
    )
    assert codes(IMPORT + block("class C:", body)) == []


def test_stub_with_real_body_still_counts_as_overload(codes):
    src = IMPORT + "@overload\ndef f(x: None) -> None:\n    raise NotImplementedError\n" + impl()
    assert codes(src) == []


def test_async(codes):
    src = (
        IMPORT
        + "@overload\nasync def f(x: None) -> None: ...\n"
        + "@overload\nasync def f(x: str) -> str: ...\n"
        + impl(async_=True)
    )
    assert codes(src) == []


def test_sync_stubs_async_impl_still_match_by_name(codes):
    assert codes(IMPORT + stubs() + impl(async_=True)) == []


# --- what does NOT count ----------------------------------------------------


def test_impl_with_different_name_is_linted(codes):
    assert codes(IMPORT + stubs("f") + impl("g")) == ["NU001"]


def test_sibling_after_impl_is_linted(codes):
    assert codes(IMPORT + stubs("f") + impl("f") + impl("g")) == ["NU001"]


def test_same_name_def_after_impl_is_linted(codes):
    # only the first def after the stubs is the implementation
    assert codes(IMPORT + stubs("f") + impl("f") + impl("f")) == ["NU001"]


def test_statement_between_stubs_and_impl_breaks_the_run(codes):
    assert codes(IMPORT + stubs() + "x = 1\n" + impl()) == ["NU001"]


def test_plain_def_between_stubs_and_impl_breaks_the_run(codes):
    src = IMPORT + stubs("f") + "def g() -> None: pass\n" + impl("f")
    assert codes(src) == ["NU001"]


def test_other_overload_set_between_breaks_the_run(codes):
    src = IMPORT + "@overload\ndef f(x: None) -> None: ...\n" + stubs("g") + impl("f")
    assert codes(src) == ["NU001"]


def test_stubs_in_a_different_block_do_not_count(codes):
    src = IMPORT + "from typing import TYPE_CHECKING\n"
    src += block("if TYPE_CHECKING:", stubs()) + impl()
    assert codes(src) == ["NU001"]


def test_stubs_in_enclosing_scope_do_not_count(codes):
    src = IMPORT + stubs() + block("def outer():", impl())
    assert codes(src) == ["NU001"]


def test_stubs_in_nested_scope_do_not_count(codes):
    src = IMPORT + block("class C:", stubs(self="self, ")) + impl()
    assert codes(src) == ["NU001"]


def test_lookalike_decorator_does_not_count(codes):
    src = "def overloaded(f): return f\n" + stubs(deco="@overloaded") + impl()
    assert codes(src) == ["NU001"]


def test_overload_call_does_not_count(codes):
    # `@overload()` is not a thing; a Call is not the decorator
    assert codes(IMPORT + stubs(deco="@overload()") + impl()) == ["NU001"]


def test_impl_without_none_in_signature_is_not_affected(codes):
    # nothing to report either way; just make sure it doesn't blow up
    src = IMPORT + stubs() + "def f(x: str) -> str:\n    return x\n"
    assert codes(src) == []


# --- every block kind -------------------------------------------------------


@pytest.mark.parametrize(
    "header",
    [
        "class C:",
        "def outer():",
        "async def outer():",
        "if True:",
        "if False:\n    pass\nelse:",
        "for _ in ():",
        "for _ in ():\n    pass\nelse:",
        "while False:",
        "while False:\n    pass\nelse:",
        "with open('x'):",
        "try:\n    pass\nfinally:\n    pass\ntry:",
        "try:\n    pass\nexcept Exception:",
        "try:\n    pass\nexcept* Exception:",
        "try:\n    pass\nexcept Exception:\n    pass\nelse:",
        "try:\n    pass\nfinally:",
        "match 0:\n    case 0:",
    ],
)
def test_overload_set_inside_block(codes, header):
    self = "self, " if header.startswith("class") else ""
    indent = "        " if header.startswith("match") else "    "
    src = IMPORT + block(header, stubs(self=self) + impl(self=self), indent)
    if header.endswith("try:"):
        src += "finally:\n    pass\n"
    assert codes(src) == []


def test_deeply_nested(codes):
    inner = block("if True:", stubs(self="self, ") + impl(self="self, "))
    src = IMPORT + block("def outer():", block("class C:", inner))
    assert codes(src) == []


def test_two_overload_sets_in_a_row(codes):
    assert codes(IMPORT + stubs("f") + impl("f") + stubs("g") + impl("g")) == []


def test_overloaded_method_next_to_plain_method(check):
    body = impl("plain", "self, ") + stubs("f", "self, ") + impl("f", "self, ")
    out = check(IMPORT + block("class C:", body))
    assert len(out) == 1 and out[0].startswith("NU001 `plain`")


# --- all rules are skipped, not just NU001 ----------------------------------


def test_nu002_and_nu003_skipped_on_impl(codes):
    body = (
        "def f(x: str | None) -> str | None:\n"
        "    if x is None:\n"
        "        raise ValueError\n"
        "    return x.upper()\n"
    )
    assert codes(body) == ["NU002", "NU003"]
    assert codes(IMPORT + stubs() + body) == []


def test_nu004_skipped_on_impl(codes):
    body = "def f(x: str | None) -> str:\n    return x.upper()\n"
    assert codes(body) == ["NU004"]
    assert codes(IMPORT + stubs() + body) == []


def test_noqa_on_impl_is_harmless(codes):
    src = IMPORT + stubs() + impl().replace("None:\n", "None:  # noqa: NU001\n", 1)
    assert codes(src) == []


# --- the skip is precise ----------------------------------------------------


def test_nested_function_inside_impl_is_still_linted(check):
    body = block("def f(x: str | None) -> str | None:", impl("inner") + "return inner(x)\n")
    out = check(IMPORT + stubs() + body)
    assert len(out) == 1 and out[0].startswith("NU001 `inner`")


def test_impl_findings_reported_for_the_right_function(check):
    out = check(IMPORT + stubs("f") + impl("f") + impl("g"))
    assert len(out) == 1 and out[0].startswith("NU001 `g`")


def test_overload_stubs_themselves_never_reported(codes):
    # a stub with a lying signature and a real body is still a stub
    src = IMPORT + "@overload\n" + impl() + "@overload\n" + impl()
    assert codes(src) == []
