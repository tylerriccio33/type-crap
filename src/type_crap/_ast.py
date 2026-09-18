"""AST helpers: union annotations, None-guards, reachability, None-ness."""

from __future__ import annotations

import ast
from dataclasses import dataclass


def _is_none_ann(node: ast.expr | None) -> bool:
    return isinstance(node, ast.Constant) and node.value is None


def _union_members(ann: ast.expr) -> list[ast.expr]:
    """Flatten `A | B | None`, `Optional[A]`, `Union[A, None]` to members."""
    if isinstance(ann, ast.BinOp) and isinstance(ann.op, ast.BitOr):
        return _union_members(ann.left) + _union_members(ann.right)
    if isinstance(ann, ast.Subscript):
        head = ann.value
        name = head.attr if isinstance(head, ast.Attribute) else getattr(head, "id", "")
        if name == "Optional":
            return [*_union_members(ann.slice), ast.Constant(None)]
        if name == "Union":
            elts = ann.slice.elts if isinstance(ann.slice, ast.Tuple) else [ann.slice]
            return [m for e in elts for m in _union_members(e)]
    if isinstance(ann, ast.Constant) and isinstance(ann.value, str):
        try:
            return _union_members(ast.parse(ann.value, mode="eval").body)
        except SyntaxError:
            return [ann]
    return [ann]


def _has_none(ann: ast.expr | None) -> bool:
    """`X | None` / `Optional[X]` -- a bare `None` annotation is not a union."""
    if ann is None:
        return False
    members = _union_members(ann)
    return len(members) > 1 and any(_is_none_ann(m) for m in members)


def _strip_none(ann: ast.expr) -> str:
    return " | ".join(ast.unparse(m) for m in _union_members(ann) if not _is_none_ann(m))


# ---------------------------------------------------------------- guards
def _guard_target(test: ast.expr) -> tuple[str, bool] | None:
    """Return (name, is_none_branch) if `test` is a None-check on a bare name.

    is_none_branch=True  -> the `if` body runs when name IS None.
    is_none_branch=False -> the `if` body runs when name is NOT None.
    """
    if isinstance(test, ast.Compare) and len(test.ops) == 1:
        lhs, rhs = test.left, test.comparators[0]
        op = test.ops[0]
        if isinstance(op, (ast.Is, ast.IsNot, ast.Eq, ast.NotEq)):
            name = None
            if isinstance(lhs, ast.Name) and _is_none_ann(rhs):
                name = lhs.id
            elif isinstance(rhs, ast.Name) and _is_none_ann(lhs):
                name = rhs.id
            if name:
                return name, isinstance(op, (ast.Is, ast.Eq))
    if (
        isinstance(test, ast.UnaryOp)
        and isinstance(test.op, ast.Not)
        and isinstance(test.operand, ast.Name)
    ):
        return test.operand.id, True  # `if not p` (falsy, incl. None)
    if isinstance(test, ast.Name):
        return test.id, False  # `if p:` -> body is the not-None branch
    return None


# ---------------------------------------------------------------- flow
def _terminates(stmts: list[ast.stmt]) -> bool:
    """Conservative: does control never fall off the end of this block?"""
    if not stmts:
        return False
    last = stmts[-1]
    if isinstance(last, (ast.Return, ast.Raise, ast.Continue, ast.Break)):
        return True
    if isinstance(last, ast.If):
        return _terminates(last.body) and _terminates(last.orelse)
    if isinstance(last, ast.Match):
        has_wild = any(
            isinstance(c.pattern, ast.MatchAs) and c.pattern.pattern is None and c.guard is None
            for c in last.cases
        )
        return has_wild and all(_terminates(c.body) for c in last.cases)
    if isinstance(last, (ast.Try, ast.TryStar)):
        if last.finalbody and _terminates(last.finalbody):
            return True
        body_ok = _terminates(last.orelse) if last.orelse else _terminates(last.body)
        return body_ok and all(_terminates(h.body) for h in last.handlers)
    if isinstance(last, ast.With):
        return _terminates(last.body)
    if isinstance(last, ast.While):
        infinite = isinstance(last.test, ast.Constant) and bool(last.test.value)
        return infinite and not _has_break(last.body)
    return False


def _has_break(stmts: list[ast.stmt]) -> bool:
    for s in stmts:
        for n in ast.walk(s):
            if isinstance(n, ast.Break):
                return True
    return False


_NOT_NONE_CTORS = {
    "str",
    "int",
    "float",
    "bool",
    "bytes",
    "list",
    "dict",
    "set",
    "tuple",
    "frozenset",
    "len",
    "repr",
    "sorted",
    "reversed",
    "enumerate",
    "zip",
    "range",
    "abs",
    "round",
    "min",
    "max",
    "sum",
    "type",
    "format",
    "hash",
}


@dataclass
class Ctx:
    none_params: set[str]
    nonnone_params: set[str]
    loose: bool


NONE, UNKNOWN, NO = "none", "unknown", "no"


def _noneness(e: ast.expr | None, ctx: Ctx, narrowed: frozenset[str] = frozenset()) -> str:
    """NONE = explicitly/structurally None-able, UNKNOWN = a call/attr we can't
    see through, NO = definitely not None."""
    if e is None:
        return NONE
    if isinstance(e, ast.Constant):
        return NONE if e.value is None else NO
    if isinstance(
        e,
        (
            ast.JoinedStr,
            ast.List,
            ast.Dict,
            ast.Set,
            ast.Tuple,
            ast.ListComp,
            ast.DictComp,
            ast.SetComp,
            ast.GeneratorExp,
            ast.Lambda,
            ast.BinOp,
            ast.UnaryOp,
            ast.Compare,
        ),
    ):
        return NO
    if isinstance(e, ast.Name):
        if e.id in ctx.nonnone_params or e.id in narrowed:
            return NO
        if e.id in ctx.none_params:
            return NONE
        return UNKNOWN  # untracked local
    if isinstance(e, ast.IfExp):
        g = _guard_target(e.test)
        if g and g[0] in ctx.none_params:
            name, body_is_none = g
            none_arm, other = (e.body, e.orelse) if body_is_none else (e.orelse, e.body)
            if _noneness(none_arm, ctx, narrowed) == NONE:
                # the None arm is the passthrough (recorded by _scan); only the
                # other arm counts as an independent None source
                return _noneness(other, ctx, narrowed | {name})
            return _worst(
                _noneness(none_arm, ctx, narrowed), _noneness(other, ctx, narrowed | {name})
            )
        return _worst(_noneness(e.body, ctx, narrowed), _noneness(e.orelse, ctx, narrowed))
    if isinstance(e, ast.BoolOp):
        if isinstance(e.op, ast.Or):
            return _noneness(e.values[-1], ctx, narrowed)
        return _worst(*(_noneness(v, ctx, narrowed) for v in e.values))
    if isinstance(e, ast.Call):
        f = e.func
        if isinstance(f, ast.Name) and (f.id in _NOT_NONE_CTORS or f.id[:1].isupper()):
            return NO
        if isinstance(f, ast.Attribute) and f.attr[:1].isupper():
            return NO
        return NO if ctx.loose else UNKNOWN
    if isinstance(e, (ast.Attribute, ast.Subscript)):
        return NO if ctx.loose else UNKNOWN
    return UNKNOWN


def _worst(*vals: str) -> str:
    if NONE in vals:
        return NONE
    if UNKNOWN in vals:
        return UNKNOWN
    return NO
