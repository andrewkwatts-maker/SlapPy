<!-- handauthored: do not regenerate -->
# pharos_engine.\<subpackage\> — API Reference

> Hand-written reference for the `<subpackage>` subpackage.
> One-line scope sentence: what this subpackage owns, what it does not,
> and one or two cross-links to sibling references for things callers
> tend to mix it up with. Cross-links use the markdown
> `LBLK`name.md`RBLK(name.md)` form so they survive a `mkdocs` build
> and `SlapPyEngineTests/tests/test_docs_links_resolve_all.py` (replace `LBLK` / `RBLK`
> with literal `[` / `]`).

<!--
================================================================================
                  META-TEMPLATE — read this before writing
================================================================================

Every hand-authored doc under `docs/api/` follows this skeleton. The
auto-generator (`scripts/gen_subpackage_api_docs.py`) skips files that
carry the `<!-- handauthored: do not regenerate -->` marker on line 1,
so structural consistency lives here in the template rather than in the
generator.

The regression test `SlapPyEngineTests/tests/test_docs_api_template_conformance.py`
asserts the load-bearing pieces. Specifically it checks that every
hand-authored doc:

  1. starts with `<!-- handauthored: do not regenerate -->` on line 1,
  2. has an H1 of the form `# pharos_engine.<X> — API Reference`,
  3. has at least one of `## Overview`, `## Public surface`, `## Usage`.

Everything below is convention — follow it for new docs, leave existing
docs alone unless they actively contradict the template.

────────────────────────────────────────────────────────────────────────
SECTION ORDER
────────────────────────────────────────────────────────────────────────

  1. Hand-authored marker          REQUIRED — line 1, exact bytes.
  2. H1 + blockquote tagline       REQUIRED — H1 must match the form
                                    `# pharos_engine.<X> — API Reference`.
  3. ## Overview                   REQUIRED for new docs (or one of the
                                    two alternates below).
  4. ## Public surface             ALTERNATE to Overview — use this when
                                    the doc opens with a `from
                                    pharos_engine.<x> import (...)` block
                                    and an `__all__` listing.
  5. ## Usage                      ALTERNATE — use this when the doc
                                    leads with a worked example.
  6. ## Classes / ## Functions /
     ## Constants                  As needed — name them per-topic
                                    (`## ResidencyManager`, `## TAAPass`)
                                    when there are only one or two
                                    members, or use the generator's
                                    flat layout for many small members.
  7. ## Inner modules              RECOMMENDED — one bullet per
                                    submodule with a one-line role.
                                    Either `## Inner modules` or
                                    `## Inner module surface` is fine.
  8. ## Conventions / ## Notes     OPTIONAL — package-wide invariants
                                    (lazy import, validation rules,
                                    threading model, …).
  9. ## See also                   RECOMMENDED for any doc that is not
                                    self-contained; one bullet per
                                    sibling doc with a one-line "why
                                    you'd jump there" hint.

────────────────────────────────────────────────────────────────────────
STYLE CONVENTIONS
────────────────────────────────────────────────────────────────────────

  - Code-block language tags. Use ```python for import blocks and
    constructor signatures, ```wgsl for shader snippets, plain ```
    for ASCII layout diagrams. Never leave a code fence untagged when
    a language applies.
  - Citation format. References to papers go in a per-section
    `**References**:` line or a `#### References` H4, citing
    `Author Year *Title*` followed by a parenthetical venue. The GI
    doc is the canonical example.
  - Tables. Use GFM pipe-tables for {field, type, default, notes}
    bundles (Stage, TelemetryEvent, diff_pngs return dict). Tables are
    not mandatory but preferred over bullet-per-row when there are
    more than three fields with the same shape.
  - Cross-links. Always `LBLK`name.md`RBLK(name.md)` relative form
    (`LBLK` / `RBLK` stand in for literal `[` / `]` so the link
    checker does not parse this template entry) so
    `SlapPyEngineTests/tests/test_docs_links_resolve_all.py` resolves them; never an
    absolute URL or a bare `name.md` reference.
  - Tone. Reference docs, not tutorials — describe the surface, link
    to demos for worked examples. Past-tense sprint notes are fine
    (`> **Sprint 7B binding fix.** …`) when they explain a non-obvious
    current behaviour.

────────────────────────────────────────────────────────────────────────
WHEN TO HAND-AUTHOR vs LET THE GENERATOR RUN
────────────────────────────────────────────────────────────────────────

Hand-author when the subpackage has:
  - a non-trivial pipeline shape that needs a paragraph of prose
    (compute dispatch order, GPU/CPU residency tiers, post-process
    chain composition),
  - WGSL / UBO layouts the generator cannot see,
  - external citations (papers, sprint logs, design docs),
  - cross-cutting conventions (lazy import, threading model, validation
    rules) that span multiple classes.

Let the generator handle it when the subpackage is a flat set of
dataclasses + free functions with self-explanatory docstrings; the
zones / thermal / numerics / topology docs sit in that band and were
opted into the marker only to lock the existing wording while the
subpackages settle.
-->

## Overview

One to three paragraphs of high-level prose describing what the
subpackage exists to do, the load-bearing pipeline shape, and any
import / lazy-load story the caller needs to know up front. This is the
canonical landing section that the conformance test looks for.

## Public surface

```python
from pharos_engine.<subpackage> import (
    PublicSymbolA,
    PublicSymbolB,
    public_function,
)
```

Optional bulleted breakdown of `__all__` when the import block alone
does not communicate roles — group by purpose
("composition primitives", "GPU walker", "preset factories").

## Classes

### `PublicSymbolA`

_class | dataclass — defined in `pharos_engine.<subpackage>.<module>`_

One-paragraph role description.

#### Constructor signature

```python
PublicSymbolA(arg1: int, arg2: str = "default") -> None
```

#### Methods

- `do_thing(self, ...) -> ReturnType` — one-line summary plus any
  raise / side-effect notes.

#### References

- Citation line — paper / sprint / design doc that owns the algorithm.

## Functions

### `public_function(arg: int) -> bool`

_defined in `pharos_engine.<subpackage>`_

One-paragraph role description, followed by a `Raises:` bullet list if
the function validates its inputs.

## Constants

### `CONSTANT_NAME`

_int | str | … — defined in `pharos_engine.<subpackage>`_

Value: `42`. One-line description of what callers use it for.

## Inner modules

- `pharos_engine.<subpackage>.<module_a>` — one-line role.
- `pharos_engine.<subpackage>.<module_b>` — one-line role.

## Conventions

- **Lazy import** / **Validation** / **Threading** — package-wide
  invariants that span the classes above.

## See also

- `LBLK`<sibling>.md`RBLK(<sibling>.md)` — one-line "why jump here"
  hint (replace `LBLK` / `RBLK` / `<sibling>` with literal `[` / `]`
  / the real subpackage doc stem).
