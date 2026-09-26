"""RD rules: code that re-implements what Python already does, or ports a
pattern from another language that has no job here. See README."""

from __future__ import annotations

import ast
from collections.abc import Iterator

# guard kind -> the exception the unguarded operation raises by itself
_NATIVE = {"in": "KeyError", "hasattr": "AttributeError", "bounds": "IndexError"}
_SPELLED = {"in": "`{c}[{k}]`", "hasattr": "`{c}.{k}`", "bounds": "`{c}[{k}]`"}

Hit = tuple[int, int, str, str]  # line, col, code, msg


def check_redundant(tree: ast.AST) -> list[Hit]:
    out: list[Hit] = []
    for node in ast.walk(tree):
        for stmts in _blocks(node):
            out.extend(_guard_then_raise(stmts))
        if isinstance(node, ast.Try | ast.TryStar):
            out.extend(_same_type_reraise(node))
        if isinstance(node, ast.ClassDef):
            out.extend(_class_smells(node))
    return sorted(out)


def _blocks(node: ast.AST) -> Iterator[list[ast.stmt]]:
    for name in ("body", "orelse", "finalbody"):
        stmts = getattr(node, name, None)
        if isinstance(stmts, list) and stmts and isinstance(stmts[0], ast.stmt):
            yield stmts
    for h in getattr(node, "handlers", []):
        yield h.body
    for c in getattr(node, "cases", []):
        yield c.body


def _body(fn_or_cls: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) -> list[ast.stmt]:
    """Body without its docstring."""
    b = fn_or_cls.body
    if b and isinstance(b[0], ast.Expr) and isinstance(b[0].value, ast.Constant):
        return b[1:]
    return b


# -- RD001-003: guard, then raise the error the operation raises anyway ------


def _guard_kind(test: ast.expr) -> tuple[str, bool, str, str] | None:
    """-> (kind, negated, container, key) for `k in d`, `hasattr(o, "x")`,
    and comparisons against `len(xs)`, each optionally under `not`."""
    negated = False
    while isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
        test, negated = test.operand, not negated
    if isinstance(test, ast.Compare) and len(test.ops) == 1:
        op = test.ops[0]
        if isinstance(op, ast.In | ast.NotIn):
            neg = negated != isinstance(op, ast.NotIn)
            return "in", neg, ast.unparse(test.comparators[0]), ast.unparse(test.left)
    if (
        isinstance(test, ast.Call)
        and isinstance(test.func, ast.Name)
        and test.func.id == "hasattr"
        and len(test.args) == 2
        and isinstance(test.args[1], ast.Constant)
        and isinstance(test.args[1].value, str)
    ):
        return "hasattr", negated, ast.unparse(test.args[0]), test.args[1].value
    if isinstance(test, ast.Compare) and all(
        isinstance(op, ast.Lt | ast.LtE | ast.Gt | ast.GtE) for op in test.ops
    ):
        parts = [test.left, *test.comparators]
        lens = [
            p
            for p in parts
            if isinstance(p, ast.Call)
            and isinstance(p.func, ast.Name)
            and p.func.id == "len"
            and len(p.args) == 1
        ]
        others = [p for p in parts if p not in lens and not isinstance(p, ast.Constant)]
        if len(lens) == 1 and len(others) == 1:
            return "bounds", negated, ast.unparse(lens[0].args[0]), ast.unparse(others[0])
    return None


def _lone_raise(stmts: list[ast.stmt], exc: str) -> bool:
    if len(stmts) != 1 or not isinstance(stmts[0], ast.Raise):
        return False
    e = stmts[0].exc
    if isinstance(e, ast.Call):
        e = e.func
    return isinstance(e, ast.Name) and e.id == exc


def _accesses(stmts: list[ast.stmt], kind: str, container: str, key: str) -> bool:
    """Does `container[key]` / `container.key` actually happen in stmts?"""
    for n in (x for st in stmts for x in ast.walk(st)):
        if kind == "hasattr":
            if isinstance(n, ast.Attribute) and n.attr == key and ast.unparse(n.value) == container:
                return True
        elif (
            isinstance(n, ast.Subscript)
            and ast.unparse(n.value) == container
            and ast.unparse(n.slice) == key
        ):
            return True
    return False


def _terminates(stmts: list[ast.stmt]) -> bool:
    return bool(stmts) and isinstance(stmts[-1], ast.Return | ast.Raise | ast.Continue | ast.Break)


def _guard_then_raise(stmts: list[ast.stmt]) -> Iterator[Hit]:
    for i, st in enumerate(stmts):
        if not isinstance(st, ast.If):
            continue
        g = _guard_kind(st.test)
        if g is None:
            continue
        kind, negated, container, key = g
        exc = _NATIVE[kind]
        after = stmts[i + 1 :]
        # (branch taken when the guard fails, branch taken when it passes)
        if negated:
            cases = [(st.body, st.orelse or after)]
        elif st.orelse:
            cases = [(st.orelse, st.body)]
        elif _terminates(st.body):
            cases = [(after[:1], st.body)]
        else:
            cases = []
        if kind == "bounds":  # polarity of `i < len(xs)` vs `i >= len(xs)` is anyone's guess
            cases += [(st.orelse or after[:1], st.body), (st.body, st.orelse or after)]
        if not any(
            _lone_raise(fail, exc) and _accesses(ok, kind, container, key) for fail, ok in cases
        ):
            continue
        code = {"in": "RD001", "hasattr": "RD002", "bounds": "RD003"}[kind]
        op = _SPELLED[kind].format(c=container, k=key)
        yield (
            st.lineno,
            st.col_offset,
            code,
            f"checks before {op} only to raise {exc}; {op} already raises {exc}, drop the guard",
        )


# -- RD004: catch E, raise E -----------------------------------------------


def _same_type_reraise(node: ast.Try | ast.TryStar) -> Iterator[Hit]:
    if len(node.handlers) != 1 or node.orelse:
        return
    h = node.handlers[0]
    if not isinstance(h.type, ast.Name) or len(h.body) != 1:
        return
    r = h.body[0]
    if not isinstance(r, ast.Raise):
        return
    e = r.exc
    caught = h.type.id
    if e is None:
        how = "re-raises it"
    elif isinstance(e, ast.Name) and h.name and e.id == h.name:
        how = f"re-raises `{h.name}`"
    elif _exc_name(e) == caught and _adds_nothing(e):
        how = f"raises a new {caught} with nothing added"
    else:
        return
    fix = "drop the except clause" if node.finalbody else "drop the try/except"
    yield (h.lineno, h.col_offset, "RD004", f"catches {caught} and {how}; {fix}")


def _adds_nothing(e: ast.expr) -> bool:
    """`E`, `E()`, `E(k)`, `E(str(e))`: no message a reader didn't already have."""
    if isinstance(e, ast.Name):
        return True
    if not isinstance(e, ast.Call):
        return False
    return all(
        not isinstance(n, ast.Constant | ast.JoinedStr)
        for a in [*e.args, *(k.value for k in e.keywords)]
        for n in ast.walk(a)
    )


def _exc_name(e: ast.expr) -> str | None:
    if isinstance(e, ast.Call):
        e = e.func
    return e.id if isinstance(e, ast.Name) else None


# -- RD007-011: class shapes from other languages ---------------------------


def _self_attr(e: ast.expr, self_name: str) -> str | None:
    if isinstance(e, ast.Attribute) and isinstance(e.value, ast.Name) and e.value.id == self_name:
        return e.attr
    return None


def _writes_self(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """True when the method stores into `self` (a counter, a cache): state a function can't keep."""
    self_name = _params(fn)[0] if _params(fn) else ""
    for n in ast.walk(fn):
        targets = (
            n.targets
            if isinstance(n, ast.Assign)
            else [n.target]
            if isinstance(n, ast.AugAssign | ast.AnnAssign)
            else []
        )
        for t in targets:
            base = t.value if isinstance(t, ast.Subscript) else t
            if _self_attr(base, self_name) is not None:
                return True
    return False


def _params(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
    return [p.arg for p in (*fn.args.posonlyargs, *fn.args.args)]


def _reads(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> str | None:
    """`def m(self): return self.a` -> "a"."""
    ps, b = _params(fn), _body(fn)
    if len(ps) != 1 or fn.args.vararg or fn.args.kwonlyargs or fn.args.kwarg or len(b) != 1:
        return None
    if isinstance(b[0], ast.Return) and b[0].value is not None:
        return _self_attr(b[0].value, ps[0])
    return None


def _writes(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> str | None:
    """`def m(self, v): self.a = v` -> "a"."""
    ps, b = _params(fn), _body(fn)
    if len(ps) != 2 or fn.args.vararg or fn.args.kwonlyargs or fn.args.kwarg or len(b) != 1:
        return None
    st = b[0]
    if isinstance(st, ast.AnnAssign):
        target, value = st.target, st.value
    elif isinstance(st, ast.Assign) and len(st.targets) == 1:
        target, value = st.targets[0], st.value
    else:
        return None
    if isinstance(value, ast.Name) and value.id == ps[1]:
        return _self_attr(target, ps[0])
    return None


def _decorator_names(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
    return [ast.unparse(d) for d in fn.decorator_list]


def _backs(attr: str | None, name: str) -> bool:
    return attr is not None and attr.lstrip("_") == name.lstrip("_")


def _class_smells(cls: ast.ClassDef) -> Iterator[Hit]:
    body = _body(cls)
    defs = [s for s in body if isinstance(s, ast.FunctionDef | ast.AsyncFunctionDef)]
    by_name = {d.name: d for d in defs}
    plain = not cls.bases and not cls.keywords and not cls.decorator_list

    # RD007 -- get_x / set_x
    for d in defs:
        if d.decorator_list:
            continue
        for prefix, probe in (("get_", _reads), ("set_", _writes)):
            if d.name.startswith(prefix) and _backs(probe(d), d.name[len(prefix) :]):
                x = d.name[len(prefix) :]
                attr = probe(d)
                yield (
                    d.lineno,
                    d.col_offset,
                    "RD007",
                    f"`{cls.name}.{d.name}` just {'returns' if prefix == 'get_' else 'assigns'}"
                    f" `self.{attr}`; make `{x}` a plain attribute",
                )

    # RD008 -- @property + @x.setter that only proxy self._x
    for d in defs:
        if _decorator_names(d) != ["property"] or not _backs(_reads(d), d.name):
            continue
        setter = next(
            (
                s
                for s in defs
                if s.name == d.name
                and _decorator_names(s) == [f"{d.name}.setter"]
                and _backs(_writes(s), d.name)
            ),
            None,
        )
        if setter is not None:
            yield (
                d.lineno,
                d.col_offset,
                "RD008",
                f"`{cls.name}.{d.name}` property and setter only proxy `self.{_reads(d)}`;"
                f" make `{d.name}` a plain attribute",
            )

    # RD009 -- class used as a namespace of staticmethods
    if (
        plain
        and defs
        and len(defs) == len(body)
        and all(_decorator_names(d) == ["staticmethod"] for d in defs)
    ):
        yield (
            cls.lineno,
            cls.col_offset,
            "RD009",
            f"`{cls.name}` only holds staticmethods; use module-level functions",
        )

    # RD010 -- __init__ + one method: a function wearing a class
    init = by_name.get("__init__")
    if plain and init is not None and len(defs) == 2 and len(body) == 2:
        (other,) = [d for d in defs if d is not init]
        init_body = _body(init)
        self_name = _params(init)[0] if _params(init) else None
        only_assigns = bool(init_body) and all(
            isinstance(s, ast.Assign | ast.AnnAssign)
            and all(
                _self_attr(t, self_name or "") is not None
                for t in (s.targets if isinstance(s, ast.Assign) else [s.target])
            )
            for s in init_body
        )
        if (
            only_assigns
            and not other.decorator_list
            and not other.name.startswith("__")
            and not _writes_self(other)
        ):
            yield (
                cls.lineno,
                cls.col_offset,
                "RD010",
                f"`{cls.name}` is `__init__` plus `{other.name}`; make `{other.name}`"
                " a function that takes the constructor args",
            )

    # RD011 -- override that only forwards to super()
    for d in defs:
        if d.decorator_list or not _forwards_to_super(d):
            continue
        yield (
            d.lineno,
            d.col_offset,
            "RD011",
            f"`{cls.name}.{d.name}` only calls `super().{d.name}` with the same args; delete it",
        )


def _forwards_to_super(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    b = _body(fn)
    if len(b) != 1 or not isinstance(b[0], ast.Expr | ast.Return):
        return False
    call = b[0].value
    if isinstance(call, ast.Await):
        call = call.value
    if not (
        isinstance(call, ast.Call)
        and isinstance(call.func, ast.Attribute)
        and call.func.attr == fn.name
        and isinstance(call.func.value, ast.Call)
        and isinstance(call.func.value.func, ast.Name)
        and call.func.value.func.id == "super"
        and not call.func.value.args
    ):
        return False
    a = fn.args
    if a.defaults or any(d is not None for d in a.kw_defaults):
        return False  # may be changing the parent's defaults
    want = [*_params(fn)[1:]]
    if a.vararg:
        want.append(f"*{a.vararg.arg}")
    want += [f"{k.arg}={k.arg}" for k in a.kwonlyargs]
    if a.kwarg:
        want.append(f"**{a.kwarg.arg}")
    got = [ast.unparse(x) for x in call.args] + [ast.unparse(k) for k in call.keywords]
    return got == want
