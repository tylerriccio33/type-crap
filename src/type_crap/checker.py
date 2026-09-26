"""The rules. See README for what each one means."""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path

from type_crap._ast import (
    NONE,
    UNKNOWN,
    Ctx,
    _guard_target,
    _has_none,
    _is_none_ann,
    _noneness,
    _strip_none,
    _terminates,
)
from type_crap.redundant import check_redundant

NU_CODES = {"NU001", "NU002", "NU003", "NU004", "NU005"}
RD_CODES = {f"RD{n:03}" for n in range(1, 12)}
CODES = NU_CODES | RD_CODES

# Enclosing constructs that don't make a nested guard conditional.
_STRAIGHT_LINE = {"with", "try"}


@dataclass
class Finding:
    path: Path
    line: int
    col: int
    code: str
    msg: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line}:{self.col}: {self.code} {self.msg}"


@dataclass
class _Guard:
    line: int
    enclosing: tuple[str, ...]  # constructs between the def and the guard

    @property
    def unconditional(self) -> bool:
        return all(e in _STRAIGHT_LINE for e in self.enclosing)


@dataclass
class _FuncScan:
    """Everything we learn from one function body (not nested defs)."""

    returns: list[ast.Return] = field(default_factory=list)
    # param -> lines of `return None`/`return p` inside a None-guard on it
    passthrough: dict[str, list[int]] = field(default_factory=dict)
    # param -> raise/assert guards on it, in source order
    raise_guards: dict[str, list[_Guard]] = field(default_factory=dict)
    guarded_returns: set[int] = field(default_factory=set)  # id(Return) in a passthrough
    narrowed_at: dict[int, frozenset[str]] = field(default_factory=dict)  # id(Return)
    checked: set[str] = field(default_factory=set)  # params mentioned in any None-ish test
    reassigned: set[str] = field(default_factory=set)
    derefs: dict[str, int] = field(default_factory=dict)  # param -> first deref line


def _returns_none_ish(stmts: list[ast.stmt], none_params: set[str]) -> ast.Return | None:
    """If `stmts` ends in `return None` / bare `return` / `return <none-param>`, give it."""
    if not stmts:
        return None
    last = stmts[-1]
    if isinstance(last, ast.Return):
        v = last.value
        if v is None or _is_none_ann(v):
            return last
        if isinstance(v, ast.Name) and v.id in none_params:
            return last
    return None


def _ends_in_raise(stmts: list[ast.stmt]) -> bool:
    return bool(stmts) and isinstance(stmts[-1], ast.Raise)


def _scan(
    fn: ast.FunctionDef | ast.AsyncFunctionDef, none_params: set[str], varargs: set[str]
) -> _FuncScan:
    s = _FuncScan()

    def walk(stmts: list[ast.stmt], enclosing: tuple[str, ...], narrowed: frozenset[str]) -> None:
        for st in stmts:
            if isinstance(st, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
                continue
            _note_uses(st, narrowed)
            if isinstance(st, ast.Return):
                s.returns.append(st)
                s.narrowed_at[id(st)] = narrowed
                continue
            if isinstance(st, ast.Assert):
                g = _guard_target(st.test)
                if g and g[0] in none_params and not g[1]:
                    s.raise_guards.setdefault(g[0], []).append(_Guard(st.lineno, enclosing))
                    narrowed |= {g[0]}
                continue
            if isinstance(st, ast.If):
                g = _guard_target(st.test)
                if g and g[0] in none_params:
                    name, body_is_none = g
                    none_block, other_block = (
                        (st.body, st.orelse) if body_is_none else (st.orelse, st.body)
                    )
                    r = _returns_none_ish(none_block, none_params)
                    if r is not None:
                        s.passthrough.setdefault(name, []).append(r.lineno)
                        s.guarded_returns.add(id(r))
                    elif _ends_in_raise(none_block):
                        s.raise_guards.setdefault(name, []).append(_Guard(st.lineno, enclosing))
                    walk(none_block, (*enclosing, "if"), narrowed)
                    walk(other_block, (*enclosing, "if"), narrowed | {name})
                    if _terminates(none_block):
                        narrowed |= {name}
                    continue
                walk(st.body, (*enclosing, "if"), narrowed)
                walk(st.orelse, (*enclosing, "if"), narrowed)
                continue
            for kind, sub in _child_blocks(st):
                walk(sub, (*enclosing, kind), narrowed)

    def _note_uses(st: ast.stmt, narrowed: frozenset[str]) -> None:
        """Record None-checks, reassignments, derefs and ternary passthroughs in `st`.

        Only looks at expressions directly on `st`, not its nested blocks --
        those are walked separately so narrowing stays per-block.
        """
        if isinstance(st, ast.Assign | ast.AnnAssign | ast.AugAssign):
            targets = st.targets if isinstance(st, ast.Assign) else [st.target]
            for t in targets:
                for n in ast.walk(t):
                    if isinstance(n, ast.Name) and n.id in none_params:
                        s.reassigned.add(n.id)
        if isinstance(st, ast.For | ast.AsyncFor) and isinstance(st.iter, ast.Name):
            _deref(st.iter, st.lineno, narrowed)
        if isinstance(st, ast.With | ast.AsyncWith):
            for item in st.items:
                if isinstance(item.context_expr, ast.Name):
                    _deref(item.context_expr, st.lineno, narrowed)
        _note_expr(st, narrowed)
        for e in _own_exprs(st):
            for n in ast.walk(e):
                _note_expr(n, narrowed)

    def _note_expr(n: ast.AST, narrowed: frozenset[str]) -> None:
        for name in _none_tested_names(n):
            if name in none_params:
                s.checked.add(name)
        if isinstance(n, ast.IfExp):
            g = _guard_target(n.test)
            if g and g[0] in none_params:
                name, body_is_none = g
                none_arm = n.body if body_is_none else n.orelse
                if _is_none_ann(none_arm) or (
                    isinstance(none_arm, ast.Name) and none_arm.id in none_params
                ):
                    s.passthrough.setdefault(name, []).append(n.lineno)
        # derefs: p.x, p[i], p(), p + 1, -p, p < q
        if isinstance(n, ast.Attribute | ast.Subscript):
            _deref(n.value, n.lineno, narrowed)
        elif isinstance(n, ast.Call):
            _deref(n.func, n.lineno, narrowed)
        elif isinstance(n, ast.BinOp):
            _deref(n.left, n.lineno, narrowed)
            _deref(n.right, n.lineno, narrowed)
        elif isinstance(n, ast.UnaryOp) and not isinstance(n.op, ast.Not):
            _deref(n.operand, n.lineno, narrowed)
        elif isinstance(n, ast.Compare) and all(
            isinstance(op, ast.Lt | ast.LtE | ast.Gt | ast.GtE) for op in n.ops
        ):
            for e in (n.left, *n.comparators):
                _deref(e, n.lineno, narrowed)

    def _deref(e: ast.expr, line: int, narrowed: frozenset[str]) -> None:
        # `*args: X | None` is a tuple; using the tuple isn't using an element
        if isinstance(e, ast.Name) and e.id in none_params - varargs and e.id not in narrowed:
            s.derefs.setdefault(e.id, line)

    walk(fn.body, (), frozenset())
    return s


def _none_tested_names(n: ast.AST) -> list[str]:
    """Names whose None-ness `n` tests: `p is None`, `p == None`, `not p`, `if p:`,
    `p or q`, `p and q`, `isinstance(p, ...)`, `x if p else y`, `while p:`."""
    names: list[str] = []

    def bare(e: ast.expr) -> None:
        if isinstance(e, ast.Name):
            names.append(e.id)

    if isinstance(n, ast.Compare) and all(
        isinstance(op, ast.Is | ast.IsNot | ast.Eq | ast.NotEq) for op in n.ops
    ):
        for e in (n.left, *n.comparators):
            bare(e)
    elif isinstance(n, ast.Compare) and all(isinstance(op, ast.In | ast.NotIn) for op in n.ops):
        bare(n.left)  # `p in (None, "x")` -- membership against a set that may hold None
    elif isinstance(n, ast.UnaryOp) and isinstance(n.op, ast.Not):
        bare(n.operand)
    elif isinstance(n, ast.BoolOp):
        for e in n.values:
            bare(e)
    elif isinstance(n, ast.If | ast.While | ast.IfExp | ast.Assert):
        bare(n.test)
    elif isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "isinstance":
        for e in n.args[:1]:
            bare(e)
    return names


def _own_exprs(st: ast.stmt) -> list[ast.expr]:
    """Expressions hanging directly off `st` (not inside its nested statement blocks)."""
    out: list[ast.expr] = []
    for _field, val in ast.iter_fields(st):
        if isinstance(val, ast.expr):
            out.append(val)
        elif isinstance(val, list):
            out.extend(v for v in val if isinstance(v, ast.expr))
    return out


def _child_blocks(st: ast.stmt) -> list[tuple[str, list[ast.stmt]]]:
    kind = {
        ast.For: "for",
        ast.AsyncFor: "for",
        ast.While: "while",
        ast.With: "with",
        ast.AsyncWith: "with",
        ast.Try: "try",
        ast.TryStar: "try",
        ast.Match: "match",
    }.get(type(st), "block")
    out: list[tuple[str, list[ast.stmt]]] = []
    for f in ("body", "orelse", "finalbody"):
        b = getattr(st, f, None)
        if isinstance(b, list) and b and isinstance(b[0], ast.stmt):
            # a loop's `else` and a try's `else` only run on some paths
            out.append((kind if f == "body" or kind == "with" else f"{kind}-{f}", b))
    for h in getattr(st, "handlers", []) or []:
        out.append(("except", h.body))
    for c in getattr(st, "cases", []) or []:
        out.append(("match", c.body))
    return out


def _noqa(src_lines: list[str], fn: ast.AST) -> set[str]:
    return _noqa_line(src_lines, fn.lineno)


def _noqa_line(src_lines: list[str], lineno: int) -> set[str]:
    line = src_lines[lineno - 1]
    if "# noqa" not in line:
        return set()
    tail = line.split("# noqa", 1)[1].lstrip(":").strip()
    codes = {c.strip() for c in tail.replace(",", " ").split()} & CODES
    return codes or CODES


def _is_overload(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    return any(
        (isinstance(d, ast.Name) and d.id == "overload")
        or (isinstance(d, ast.Attribute) and d.attr == "overload")
        for d in fn.decorator_list
    )


def _overload_impls(tree: ast.AST) -> set[int]:
    """ids of defs that implement a preceding run of `@overload` stubs of the same name.

    Their `X | None` signature is just the union of the stubs, so it is not a lie.
    """
    out: set[int] = set()
    for node in ast.walk(tree):
        for block in ("body", "orelse", "finalbody"):
            stmts = getattr(node, block, None)
            if not isinstance(stmts, list):
                continue
            pending: str | None = None
            for st in stmts:
                if isinstance(st, ast.FunctionDef | ast.AsyncFunctionDef):
                    if _is_overload(st):
                        pending = st.name
                        continue
                    if st.name == pending:
                        out.add(id(st))
                pending = None
    return out


def _is_stub(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    for st in fn.body:
        if isinstance(st, ast.Pass):
            continue
        if isinstance(st, ast.Expr) and isinstance(st.value, ast.Constant):
            continue
        return False
    return True


def _union_members(ann: ast.expr | None) -> list[str]:
    """`A | B`, `Union[A, B]`, `Optional[A]`, or a string of those -> ["A", "B"].
    Anything else is a single member."""
    if ann is None:
        return []
    if isinstance(ann, ast.Constant) and isinstance(ann.value, str):
        try:
            ann = ast.parse(ann.value, mode="eval").body
        except SyntaxError:
            return [ann.value]
    if isinstance(ann, ast.BinOp) and isinstance(ann.op, ast.BitOr):
        return _union_members(ann.left) + _union_members(ann.right)
    if isinstance(ann, ast.Subscript):
        v = ann.value
        head = v.attr if isinstance(v, ast.Attribute) else getattr(v, "id", "")
        if head == "Union":
            elts = ann.slice.elts if isinstance(ann.slice, ast.Tuple) else [ann.slice]
            return [m for e in elts for m in _union_members(e)]
        if head == "Optional":
            return [*_union_members(ann.slice), "None"]
    return ["None" if _is_none_ann(ann) else ast.unparse(ann)]


def _isinstance_test(test: ast.expr) -> tuple[str, list[str], bool] | None:
    """`isinstance(p, T)` / `isinstance(p, (T1, T2))`, optionally under `not`
    -> (p, [T...], negated)."""
    negated = False
    if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
        test, negated = test.operand, True
    if not (
        isinstance(test, ast.Call)
        and isinstance(test.func, ast.Name)
        and test.func.id == "isinstance"
        and len(test.args) == 2
        and isinstance(test.args[0], ast.Name)
    ):
        return None
    t = test.args[1]
    elts = t.elts if isinstance(t, ast.Tuple) else [t]
    return test.args[0].id, [ast.unparse(e) for e in elts], negated


@dataclass
class _TypeGuard:
    line: int  # first guard on the param
    rejected: set[str] = field(default_factory=set)  # `if isinstance(p, T): raise`
    kept: list[set[str]] = field(default_factory=list)  # `assert isinstance(p, T)`

    def survivors(self, members: list[str]) -> list[str]:
        return [m for m in members if m not in self.rejected and all(m in k for k in self.kept)]


def _type_guards(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> dict[str, _TypeGuard]:
    """Leading `if isinstance(p, T): raise` / `assert isinstance(p, T)` guards.
    Stops at the first statement that isn't a docstring or such a guard."""
    out: dict[str, _TypeGuard] = {}
    body = fn.body
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
        body = body[1:]
    for st in body:
        if isinstance(st, ast.If) and not st.orelse and _ends_in_raise(st.body):
            hit, raises_on_match = _isinstance_test(st.test), True
        elif isinstance(st, ast.Assert):
            hit, raises_on_match = _isinstance_test(st.test), False
        else:
            break
        if hit is None:
            break
        name, types, negated = hit
        g = out.setdefault(name, _TypeGuard(st.lineno))
        if negated == raises_on_match:  # `if not isinstance: raise` / `assert isinstance`
            g.kept.append(set(types))
        else:
            g.rejected.update(types)
    return out


def _typevars(tree: ast.AST) -> set[str]:
    return {
        t.id
        for n in ast.walk(tree)
        if isinstance(n, ast.Assign)
        and isinstance(n.value, ast.Call)
        and ast.unparse(n.value.func).split(".")[-1] == "TypeVar"
        for t in n.targets
        if isinstance(t, ast.Name)
    }


def _aliases(tree: ast.AST) -> set[str]:
    """Names bound at any level to something that could be a type alias
    (`X = A | None`, `X: TypeAlias = ...`, `type X = ...`): we can't see
    through them, so a None test on an `X` param may be legit."""
    out: set[str] = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.TypeAlias) and isinstance(n.name, ast.Name):
            out.add(n.name.id)
        elif isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name):
            out.add(n.target.id)
        elif isinstance(n, ast.Assign):
            out |= {t.id for t in n.targets if isinstance(t, ast.Name)}
    return out


def _first_none_test(fn: ast.FunctionDef | ast.AsyncFunctionDef, name: str) -> int | None:
    """Line of the first `name is None` / `is not None` / `== None` in fn's own body."""
    todo: list[ast.AST] = list(fn.body)
    hits: list[int] = []
    while todo:
        n = todo.pop()
        if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda | ast.ClassDef):
            continue
        if (
            isinstance(n, ast.Compare)
            and len(n.ops) == 1
            and isinstance(n.ops[0], ast.Is | ast.IsNot | ast.Eq | ast.NotEq)
        ):
            sides = [n.left, n.comparators[0]]
            if any(isinstance(x, ast.Name) and x.id == name for x in sides) and any(
                _is_none_ann(x) for x in sides
            ):
                hits.append(n.lineno)
        todo.extend(ast.iter_child_nodes(n))
    return min(hits) if hits else None


def _lines(nums: list[int]) -> str:
    return ", ".join(map(str, nums))


def check_source(path: Path, src: str, *, loose: bool = False) -> list[Finding]:
    tree = ast.parse(src, filename=str(path))
    lines = src.splitlines()
    out: list[Finding] = []
    impls = _overload_impls(tree)
    typevars = _typevars(tree)
    aliases = _aliases(tree)
    for line, col, code, msg in check_redundant(tree):
        if code not in _noqa_line(lines, line):
            out.append(Finding(path, line, col, code, msg))

    for fn in ast.walk(tree):
        if not isinstance(fn, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        if _is_overload(fn) or _is_stub(fn) or id(fn) in impls:
            continue
        silenced = _noqa(lines, fn)
        a = fn.args
        params = [*a.posonlyargs, *a.args, *a.kwonlyargs]
        if a.vararg:
            params.append(a.vararg)
        ann_of = {p.arg: p.annotation for p in params if p.annotation is not None}
        none_params = {n for n, ann in ann_of.items() if _has_none(ann)}
        nonnone_params = set(ann_of) - none_params
        ret_none = _has_none(fn.returns)

        # NU005 -- union param that rejects some of its members
        for name, g in sorted(_type_guards(fn).items()):
            members = _union_members(ann_of.get(name))
            left = g.survivors(members)
            gone = [m for m in members if m not in left]
            if not gone or not left:
                continue
            msg = (
                f"`{fn.name}` rejects `{name}: {' | '.join(gone)}` at line {g.line};"
                f" annotate `{name}: {' | '.join(left)}`"
            )
            if "NU005" not in silenced:
                out.append(Finding(path, fn.lineno, fn.col_offset, "NU005", msg))

        def report_rd(code: str, msg: str, fn=fn, silenced=silenced) -> None:
            if code not in silenced:
                out.append(Finding(path, fn.lineno, fn.col_offset, code, f"`{fn.name}` {msg}"))

        # RD005 -- None check on a param whose annotation excludes None
        tvs = typevars | {t.name for t in getattr(fn, "type_params", [])}
        defaults = dict(
            zip([p.arg for p in [*a.posonlyargs, *a.args]][::-1], a.defaults[::-1], strict=False)
        )
        defaults |= {k.arg: d for k, d in zip(a.kwonlyargs, a.kw_defaults, strict=True) if d}
        reassigned = {
            n.id for n in ast.walk(fn) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store)
        }
        for name in sorted(nonnone_params - reassigned):
            ann = ann_of[name]
            if ast.unparse(ann).strip("'\"") in {"Any", "object", "typing.Any", *tvs, *aliases}:
                continue
            if _is_none_ann(defaults.get(name)):
                continue  # `x: str = None`: implicit Optional, NU rules' business
            line = _first_none_test(fn, name)
            if line is not None:
                report_rd(
                    "RD005",
                    f"tests `{name} is None` at line {line} but `{name}: {ast.unparse(ann)}`"
                    " can't be None; drop the check or annotate `| None`",
                )

        # RD006 -- isinstance guard that repeats a non-union annotation
        for name, g in sorted(_type_guards(fn).items()):
            members = _union_members(ann_of.get(name))
            if len(members) == 1 and members[0] != "None" and any(members[0] in k for k in g.kept):
                report_rd(
                    "RD006",
                    f"re-checks `isinstance({name}, {members[0]})` at line {g.line} but the"
                    " annotation already says so; drop the check",
                )

        if not none_params and not ret_none:
            continue

        ctx = Ctx(none_params, nonnone_params, loose)
        s = _scan(fn, none_params, {a.vararg.arg} if a.vararg else set())
        cls = {
            id(r): _noneness(r.value, ctx, s.narrowed_at.get(id(r), frozenset()))
            for r in s.returns
            if id(r) not in s.guarded_returns
        }
        other_none = sorted({r.lineno for r in s.returns if cls.get(id(r)) == NONE})
        unknown = sorted({r.lineno for r in s.returns if cls.get(id(r)) == UNKNOWN})
        falls_off = not _terminates(fn.body)
        unverified = f" (unverified calls at {_lines(unknown)})" if unknown else ""
        ret_str = _strip_none(fn.returns) if fn.returns is not None else ""

        def report(code: str, msg: str, fn=fn, silenced=silenced) -> None:
            if code not in silenced:
                out.append(Finding(path, fn.lineno, fn.col_offset, code, f"`{fn.name}` {msg}"))

        # NU001 -- None-passthrough
        if ret_none:
            for name, glines in sorted(s.passthrough.items()):
                reasons = []
                if other_none:
                    reasons.append(f"other maybe-None returns at {_lines(other_none)}")
                if falls_off:
                    reasons.append("falls off end")
                if reasons:
                    hint = (
                        f"`(None) -> None` / `({_strip_none(ann_of[name])}) -> {ret_str} | None`"
                        f" overloads ({' and '.join(reasons)})"
                    )
                else:
                    hint = (
                        f"no other None source{unverified}; want"
                        f" `def {fn.name}[T](...{name}: T...) -> T` or overloads"
                    )
                report("NU001", f"echoes None for `{name}` (guard at {_lines(glines)}); {hint}")

        # NU002 -- raise-narrowed param
        for name, guards in sorted(s.raise_guards.items()):
            ann = _strip_none(ann_of[name])
            g = guards[0]
            if g.unconditional:
                report(
                    "NU002",
                    f"rejects `{name}=None` at line {g.line}; annotate `{name}: {ann}`"
                    " and assert at the call site",
                )
            else:
                where = "/".join(e for e in g.enclosing if e not in _STRAIGHT_LINE)
                report(
                    "NU002",
                    f"rejects `{name}=None` at line {g.line} but only inside `{where}`;"
                    f" hoist the check and annotate `{name}: {ann}`, or handle None on"
                    " the other paths",
                )

        # NU003 -- `| None` return that can't return None
        if ret_none and s.returns and not falls_off:
            any_none = other_none or s.guarded_returns or s.passthrough
            shown = ast.unparse(fn.returns)
            if not any_none and not unknown:
                report(
                    "NU003",
                    f"is annotated `-> {shown}` but no return path yields None; use `-> {ret_str}`",
                )
            elif not any_none and s.raise_guards:
                # the "reject None then return stuff" shape: worth a look even
                # though the returns are calls we can't see through
                report(
                    "NU003",
                    f"is annotated `-> {shown}` but no *explicit* None return{unverified};"
                    f" verify and use `-> {ret_str}`",
                )

        # NU004 -- `| None` param dereferenced with no None check anywhere
        for name, line in sorted(s.derefs.items()):
            if name in s.checked or name in s.reassigned or name in s.raise_guards:
                continue
            if name in s.passthrough:
                continue
            report(
                "NU004",
                f"dereferences `{name}: {ast.unparse(ann_of[name])}` at line {line} with no"
                f" None check anywhere; guard it or annotate `{name}: {_strip_none(ann_of[name])}`",
            )
    return out
