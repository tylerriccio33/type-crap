# type-crap

A tiny AST linter for one specific smell: `X | None` parameters and returns
that don't mean what they say.

```python
def f(x: str | None) -> str | None:  # both Nones are lies
    if x is None:
        raise ValueError
    return x.upper()


def g(x: str | None) -> str | None:  # this is just `def g[T](x: T) -> T`
    if x is None:
        return None
    return x
```

Type checkers are happy with both. `type-crap` is not.

## Install / run

```sh
uv tool install .            # or: uv run type-crap ...
type-crap src/ tests/
type-crap --select NU001,NU003 --loose src/   # a subset of rules, wider net
```

Output is `path:line:col: CODE message`, one per finding; exit code is 1 if
anything was reported. Silence a function with `# noqa: NU001` (or a bare
`# noqa`) on its `def` line. `@overload` stubs and empty bodies are skipped.

## Rules

### NU001 — None-passthrough

The function's `| None` return exists only to echo a `| None` param:

```python
if p is None:
    return None  # or `return p`, or bare `return`
x if p is not None else None  # ternary form
```

The message tells you which fix fits:

- **no other None source** → the function is `def f[T](p: T) -> T`.
- **other maybe-None returns at N** / **falls off end** → it genuinely
  returns None elsewhere too; write `@overload (None) -> None` and
  `@overload (X) -> Y | None`.

### NU002 — raise-narrowed param

A `X | None` param whose first act is to reject None:

```python
if p is None:
    raise ...
if not p:
    raise ...
assert p is not None
```

The function doesn't *accept* None, it *rejects* it. Annotate `p: X` and
let the caller own the runtime check.

Guards are found at any depth. One that runs unconditionally (function
body, or under `with`/`try`) gets the message above. One nested under
`if`/`for`/`while`/`match`/`except` is reported as *conditional*: None is
rejected on that path only, so either hoist the check or make sure the
other paths really handle None.

### NU003 — unreachable None return

Annotated `-> Y | None` but every `return` is definitely not None (a
literal, f-string, arithmetic, comparison, container display, `Ctor(...)`,
a builtin like `str(...)`, or a param that is either not `| None` or has
been narrowed) **and** the body can't fall off the end. Drop the `| None`.

Calls and attribute reads are opaque, so by default NU003 stays quiet when
any return goes through one — except in the NU002 shape above (reject
None, then return only calls), where it reports as *unverified* because
that is the exact pattern this tool exists for. `--loose` treats calls as
non-None everywhere; expect false positives, use it as a worklist.

### NU004 — unchecked Optional use

A `X | None` param that is dereferenced somewhere (`p.attr`, `p[i]`,
`p()`, `p + 1`, `-p`, `p < q`, `for _ in p`, `with p:`) while the body
contains **no** None-ish test on it anywhere: no `is None`, `== None`,
`in (None, ...)`, `not p`, `if p:`, `p or ...`, `isinstance(p, ...)`,
assert, and no reassignment. Either the annotation is wrong or the runtime
check is missing. A type checker will also catch this; it's here so the
tool tells the whole story on its own.

## What it knows and doesn't

Knows: `A | B | None`, `Optional[A]`, `Union[A, None]`, string
annotations; guards on bare names with `is None` / `is not None` / `==` /
`!=` / truthiness; narrowing after a top-level guard that terminates;
reachability through `if`/`else`, `match` with a wildcard, `try`/`except`,
`while True` without `break`.

Doesn't: follow locals (`y = None; ...; return y` is "unknown"), know
method return types (`s.lower()` is "unknown"), guards on attributes
(`self.x is None`), or anything a type checker would need inference for.
It is deliberately a syntactic tool; the sharp version of NU003 belongs in
a type checker plugin.

## Development

```sh
uv run pytest
uv run ruff check . && uv run ruff format --check .
```
