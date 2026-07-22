"""``pharos_engine.scenes.scene_diff`` — structured Scene-to-Scene diff.

This module compares two :class:`~pharos_engine.scenes.scene.Scene`
instances (the YAML-serialisable authoring dataclass, *not* the runtime
scene) and produces a structured diff report suitable for review
tooling, VCS-style previews, and programmatic patching.

Two-line usage::

    from pharos_engine.scenes import Scene
    from pharos_engine.scenes.scene_diff import diff_scenes, pretty_print_diff
    print(pretty_print_diff(diff_scenes(scene_a, scene_b)))

The output data model (:class:`SceneDiff` + :class:`EntityDiff`) is
intentionally plain (dataclasses with ``dict`` / ``list`` fields) so the
diff round-trips cleanly through JSON / YAML for review reports.

Design notes
~~~~~~~~~~~~
* Entities are matched by their ``id`` — the FF3 :class:`Scene` mints
  stable ``entity_N`` ids so this is the natural matching key.
* Field-level deltas are computed on the top-level entity keys plus the
  nested ``params`` dict; changes in ``params`` are reported as
  ``params.<key>`` so callers can rebuild a patch without re-walking the
  dicts.
* :func:`apply_diff` is a pure-Python replayer that mutates a *copy* of
  the input scene by default (constructed via ``Scene.from_dict``) so
  callers can chain diffs without touching the source.
* :func:`merge_diffs` uses a "later wins" policy on conflicting entity
  ids and metadata keys, matching the behaviour a rebase-style tool
  wants when stacking successive edits.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from pharos_engine.scenes.scene import Scene


# ---------------------------------------------------------------------------
# ANSI colour helpers (no external dependency; degrades to plain text when
# callers strip the escape sequences).
# ---------------------------------------------------------------------------


_ANSI_GREEN = "\x1b[32m"
_ANSI_RED = "\x1b[31m"
_ANSI_YELLOW = "\x1b[33m"
_ANSI_CYAN = "\x1b[36m"
_ANSI_RESET = "\x1b[0m"


def _green(text: str) -> str:
    return f"{_ANSI_GREEN}{text}{_ANSI_RESET}"


def _red(text: str) -> str:
    return f"{_ANSI_RED}{text}{_ANSI_RESET}"


def _yellow(text: str) -> str:
    return f"{_ANSI_YELLOW}{text}{_ANSI_RESET}"


def _cyan(text: str) -> str:
    return f"{_ANSI_CYAN}{text}{_ANSI_RESET}"


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class EntityDiff:
    """One entity's diff between two scenes.

    Attributes
    ----------
    entity_id:
        The ``id`` of the entity being compared. For ``"added"`` /
        ``"removed"`` kinds this is the id present in the destination /
        source scene respectively.
    kind:
        One of ``"added"``, ``"removed"``, or ``"modified"``.
    before:
        The entity dict from ``scene_a`` (source), or ``None`` when
        added.
    after:
        The entity dict from ``scene_b`` (destination), or ``None`` when
        removed.
    field_deltas:
        Mapping of dotted field path → ``(before_value, after_value)``
        pairs. Only populated for ``"modified"`` diffs; nested ``params``
        keys are exposed as ``params.<key>``.
    """

    entity_id: str
    kind: str
    before: dict[str, Any] | None
    after: dict[str, Any] | None
    field_deltas: dict[str, tuple[Any, Any]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Return a plain-dict view (JSON-safe field_deltas as lists)."""
        return {
            "entity_id": self.entity_id,
            "kind": self.kind,
            "before": (
                None if self.before is None else dict(self.before)
            ),
            "after": (
                None if self.after is None else dict(self.after)
            ),
            "field_deltas": {
                k: [v[0], v[1]] for k, v in self.field_deltas.items()
            },
        }


@dataclass
class SceneDiff:
    """Aggregate diff between two whole scenes.

    Attributes
    ----------
    scene_a_name:
        ``name`` of the source scene (``"before"``).
    scene_b_name:
        ``name`` of the destination scene (``"after"``).
    entity_diffs:
        Ordered list of per-entity diffs. Order is *removed → modified →
        added* so a reviewer reading top-to-bottom sees deletions first.
    layer_diffs:
        List of ``("added", name)`` / ``("removed", name)`` tuples for
        the top-level ``layers`` list. Order-preserving.
    metadata_diffs:
        Mapping of top-level ``metadata`` key → ``(before, after)``.
        Uses ``None`` as the sentinel for missing on either side.
    total_changes:
        Convenience sum: ``len(entity_diffs) + len(layer_diffs) +
        len(metadata_diffs)``.
    """

    scene_a_name: str
    scene_b_name: str
    entity_diffs: list[EntityDiff] = field(default_factory=list)
    layer_diffs: list[tuple[str, str]] = field(default_factory=list)
    metadata_diffs: dict[str, tuple[Any, Any]] = field(default_factory=dict)
    total_changes: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Return a plain-dict view (JSON-safe)."""
        return {
            "scene_a_name": self.scene_a_name,
            "scene_b_name": self.scene_b_name,
            "entity_diffs": [d.to_dict() for d in self.entity_diffs],
            "layer_diffs": [list(t) for t in self.layer_diffs],
            "metadata_diffs": {
                k: [v[0], v[1]] for k, v in self.metadata_diffs.items()
            },
            "total_changes": self.total_changes,
        }

    def is_empty(self) -> bool:
        """``True`` when there are no changes of any kind."""
        return (
            not self.entity_diffs
            and not self.layer_diffs
            and not self.metadata_diffs
        )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


_TOP_LEVEL_ENTITY_KEYS = ("kind", "position", "params", "prefab_ref")


def _entities_by_id(scene: Scene) -> dict[str, dict[str, Any]]:
    """Index a scene's entities by id.

    When the same id appears more than once (the FF3 loader forbids
    this, but callers may construct a scene directly) the *first*
    occurrence wins so downstream matching stays deterministic.
    """
    out: dict[str, dict[str, Any]] = {}
    for ent in scene.entities:
        eid = ent.get("id")
        if not isinstance(eid, str) or not eid:
            continue
        if eid not in out:  # first wins
            out[eid] = ent
    return out


def _compute_field_deltas(
    before: dict[str, Any], after: dict[str, Any],
) -> dict[str, tuple[Any, Any]]:
    """Return the dotted-key delta map for one entity pair."""
    deltas: dict[str, tuple[Any, Any]] = {}
    for key in _TOP_LEVEL_ENTITY_KEYS:
        b_has = key in before
        a_has = key in after
        if not b_has and not a_has:
            continue
        b_val = before.get(key)
        a_val = after.get(key)
        if key == "params":
            # Flatten to params.<sub_key> for reviewer legibility.
            b_params = b_val if isinstance(b_val, dict) else {}
            a_params = a_val if isinstance(a_val, dict) else {}
            for sub in sorted(set(b_params) | set(a_params)):
                bv = b_params.get(sub)
                av = a_params.get(sub)
                if bv != av:
                    deltas[f"params.{sub}"] = (bv, av)
            continue
        if b_val != a_val:
            deltas[key] = (b_val, a_val)
    # Surface unknown top-level keys too (editor-only metadata like
    # 'metadata' or 'colour' that authoring tools may attach).
    for extra in sorted(set(before) | set(after)):
        if extra in _TOP_LEVEL_ENTITY_KEYS or extra == "id":
            continue
        bv = before.get(extra)
        av = after.get(extra)
        if bv != av:
            deltas[extra] = (bv, av)
    return deltas


def _fmt_value(value: Any) -> str:
    """Compact repr used by :func:`pretty_print_diff`."""
    if isinstance(value, float):
        # Trim trailing zeros for readability without losing precision.
        text = f"{value:.6g}"
        return text
    return repr(value)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def diff_scenes(scene_a: Scene, scene_b: Scene) -> SceneDiff:
    """Compute the structured diff from ``scene_a`` → ``scene_b``.

    Parameters
    ----------
    scene_a:
        The source ("before") :class:`Scene`.
    scene_b:
        The destination ("after") :class:`Scene`.

    Returns
    -------
    SceneDiff
        An aggregate diff with per-entity, per-layer, and per-metadata
        deltas. Callers can serialise via :meth:`SceneDiff.to_dict`.
    """
    if not isinstance(scene_a, Scene):
        raise TypeError(
            f"diff_scenes: scene_a must be a Scene; "
            f"got {type(scene_a).__name__}"
        )
    if not isinstance(scene_b, Scene):
        raise TypeError(
            f"diff_scenes: scene_b must be a Scene; "
            f"got {type(scene_b).__name__}"
        )

    a_index = _entities_by_id(scene_a)
    b_index = _entities_by_id(scene_b)

    entity_diffs: list[EntityDiff] = []

    # Preserve source order for removed / modified so reviewers see the
    # scene walk in its original layout. Track which ids we've already
    # emitted so duplicate ids (which callers can inject by bypassing
    # add_entity validation) only produce one diff entry.
    seen_a: set[str] = set()
    for ent in scene_a.entities:
        eid = ent.get("id")
        if not isinstance(eid, str) or not eid:
            continue
        if eid in seen_a:
            continue
        seen_a.add(eid)
        if eid not in b_index:
            entity_diffs.append(
                EntityDiff(
                    entity_id=eid,
                    kind="removed",
                    before=dict(ent),
                    after=None,
                    field_deltas={},
                )
            )
            continue
        b_ent = b_index[eid]
        deltas = _compute_field_deltas(ent, b_ent)
        if deltas:
            entity_diffs.append(
                EntityDiff(
                    entity_id=eid,
                    kind="modified",
                    before=dict(ent),
                    after=dict(b_ent),
                    field_deltas=deltas,
                )
            )
    # Added entities: preserve destination order.
    seen_b: set[str] = set()
    for ent in scene_b.entities:
        eid = ent.get("id")
        if not isinstance(eid, str) or not eid:
            continue
        if eid in seen_b:
            continue
        seen_b.add(eid)
        if eid not in a_index:
            entity_diffs.append(
                EntityDiff(
                    entity_id=eid,
                    kind="added",
                    before=None,
                    after=dict(ent),
                    field_deltas={},
                )
            )

    # Layer diffs: report added / removed while preserving encounter
    # order (removed layers first, then added).
    a_layers = list(scene_a.layers)
    b_layers = list(scene_b.layers)
    a_set = set(a_layers)
    b_set = set(b_layers)
    layer_diffs: list[tuple[str, str]] = []
    for name in a_layers:
        if name not in b_set:
            layer_diffs.append(("removed", name))
    for name in b_layers:
        if name not in a_set:
            layer_diffs.append(("added", name))

    # Metadata diffs: symmetric-difference plus value-changed keys.
    metadata_diffs: dict[str, tuple[Any, Any]] = {}
    for key in sorted(set(scene_a.metadata) | set(scene_b.metadata)):
        bv = scene_a.metadata.get(key)
        av = scene_b.metadata.get(key)
        if key not in scene_a.metadata:
            metadata_diffs[key] = (None, av)
        elif key not in scene_b.metadata:
            metadata_diffs[key] = (bv, None)
        elif bv != av:
            metadata_diffs[key] = (bv, av)

    total = len(entity_diffs) + len(layer_diffs) + len(metadata_diffs)
    return SceneDiff(
        scene_a_name=scene_a.name,
        scene_b_name=scene_b.name,
        entity_diffs=entity_diffs,
        layer_diffs=layer_diffs,
        metadata_diffs=metadata_diffs,
        total_changes=total,
    )


def pretty_print_diff(diff: SceneDiff, *, colour: bool = True) -> str:
    """Render *diff* as a coloured markdown-style diff string.

    Parameters
    ----------
    diff:
        The :class:`SceneDiff` to render.
    colour:
        Emit ANSI escape sequences when ``True`` (default). Set to
        ``False`` for logs / test assertions that need plain text.

    Returns
    -------
    str
        The rendered diff — always begins with a ``# Scene diff`` header
        followed by ``+`` (added) and ``-`` (removed) prefixed lines and
        ``~`` (modified) prefixed sections.
    """
    if not isinstance(diff, SceneDiff):
        raise TypeError(
            f"pretty_print_diff: diff must be a SceneDiff; "
            f"got {type(diff).__name__}"
        )

    def _plus(s: str) -> str:
        return _green(s) if colour else s

    def _minus(s: str) -> str:
        return _red(s) if colour else s

    def _mod(s: str) -> str:
        return _yellow(s) if colour else s

    def _hdr(s: str) -> str:
        return _cyan(s) if colour else s

    lines: list[str] = []
    lines.append(_hdr(f"# Scene diff: {diff.scene_a_name} -> {diff.scene_b_name}"))
    lines.append(_hdr(f"# total_changes: {diff.total_changes}"))

    if diff.metadata_diffs:
        lines.append(_hdr("## metadata"))
        for key, (bv, av) in diff.metadata_diffs.items():
            if bv is None and av is not None:
                lines.append(_plus(f"+ metadata.{key}: {_fmt_value(av)}"))
            elif av is None and bv is not None:
                lines.append(_minus(f"- metadata.{key}: {_fmt_value(bv)}"))
            else:
                lines.append(
                    _mod(
                        f"~ metadata.{key}: "
                        f"{_fmt_value(bv)} -> {_fmt_value(av)}"
                    )
                )

    if diff.layer_diffs:
        lines.append(_hdr("## layers"))
        for op, name in diff.layer_diffs:
            if op == "added":
                lines.append(_plus(f"+ layer: {name}"))
            else:
                lines.append(_minus(f"- layer: {name}"))

    if diff.entity_diffs:
        lines.append(_hdr("## entities"))
        for ed in diff.entity_diffs:
            if ed.kind == "added":
                after = ed.after or {}
                lines.append(
                    _plus(
                        f"+ entity {ed.entity_id} "
                        f"({after.get('kind', '?')}) "
                        f"@ {after.get('position', '?')}"
                    )
                )
            elif ed.kind == "removed":
                before = ed.before or {}
                lines.append(
                    _minus(
                        f"- entity {ed.entity_id} "
                        f"({before.get('kind', '?')}) "
                        f"@ {before.get('position', '?')}"
                    )
                )
            else:  # modified
                lines.append(_mod(f"~ entity {ed.entity_id}"))
                for path, (bv, av) in ed.field_deltas.items():
                    lines.append(
                        _minus(f"-   {path}: {_fmt_value(bv)}")
                    )
                    lines.append(
                        _plus(f"+   {path}: {_fmt_value(av)}")
                    )

    if not lines[2:]:  # only the two header lines
        lines.append(_hdr("(no changes)"))

    return "\n".join(lines)


def apply_diff(scene: Scene, diff: SceneDiff) -> Scene:
    """Return a new :class:`Scene` with *diff* applied on top of *scene*.

    Applies the ``scene_a → scene_b`` deltas encoded in *diff* to a
    copy of *scene*: added entities are appended, removed entities are
    dropped, and modified entities have their ``field_deltas`` replayed
    field-by-field.

    Layer additions / removals are applied preserving the source
    ordering, and metadata deltas are folded into the copy's metadata
    dict.

    The input scene is *not* mutated.

    Parameters
    ----------
    scene:
        The base scene the diff is applied to. Typically the same scene
        that was the ``scene_a`` argument of :func:`diff_scenes`, but
        any :class:`Scene` with matching entity ids is accepted (this
        makes chaining and cherry-picking possible).
    diff:
        The :class:`SceneDiff` to replay.
    """
    if not isinstance(scene, Scene):
        raise TypeError(
            f"apply_diff: scene must be a Scene; "
            f"got {type(scene).__name__}"
        )
    if not isinstance(diff, SceneDiff):
        raise TypeError(
            f"apply_diff: diff must be a SceneDiff; "
            f"got {type(diff).__name__}"
        )

    # Deep-ish copy via to_dict/from_dict — guarantees the returned
    # scene is fully detached from the caller's dicts.
    result = Scene.from_dict(scene.to_dict())

    # Index once for O(1) lookups.
    by_id = {ent["id"]: ent for ent in result.entities}

    for ed in diff.entity_diffs:
        if ed.kind == "removed":
            result.remove_entity(ed.entity_id)
            by_id.pop(ed.entity_id, None)
        elif ed.kind == "added":
            if ed.after is None:
                continue
            # Skip if the entity already exists (idempotent apply).
            if ed.entity_id in by_id:
                continue
            new_ent = dict(ed.after)
            new_ent["id"] = ed.entity_id
            result.add_entity(new_ent)
            by_id[ed.entity_id] = result.get(ed.entity_id) or new_ent
        else:  # modified
            target = by_id.get(ed.entity_id)
            if target is None:
                # Entity missing from base — treat as an add using the
                # 'after' snapshot when available so the diff still
                # replays coherently.
                if ed.after is not None:
                    new_ent = dict(ed.after)
                    new_ent["id"] = ed.entity_id
                    result.add_entity(new_ent)
                    by_id[ed.entity_id] = result.get(ed.entity_id) or new_ent
                continue
            for path, (_before_val, after_val) in ed.field_deltas.items():
                if path.startswith("params."):
                    sub = path.split(".", 1)[1]
                    params = target.setdefault("params", {})
                    if not isinstance(params, dict):
                        params = {}
                        target["params"] = params
                    if after_val is None and sub in params:
                        del params[sub]
                    else:
                        params[sub] = after_val
                elif path in _TOP_LEVEL_ENTITY_KEYS:
                    if after_val is None and path in target:
                        del target[path]
                    else:
                        target[path] = after_val
                else:
                    # Unknown top-level key (editor metadata etc.).
                    if after_val is None and path in target:
                        del target[path]
                    else:
                        target[path] = after_val

    # Layer diffs — remove first, then append additions in source order.
    for op, name in diff.layer_diffs:
        if op == "removed" and name in result.layers:
            result.layers.remove(name)
    for op, name in diff.layer_diffs:
        if op == "added" and name not in result.layers:
            result.layers.append(name)

    # Metadata diffs.
    for key, (_bv, av) in diff.metadata_diffs.items():
        if av is None:
            result.metadata.pop(key, None)
        else:
            result.metadata[key] = av

    return result


def filter_by_kind(diff: SceneDiff, kinds: set[str]) -> SceneDiff:
    """Return a new :class:`SceneDiff` containing only the requested kinds.

    Parameters
    ----------
    diff:
        The source diff.
    kinds:
        Any subset of ``{"added", "removed", "modified"}``. Unknown
        strings are silently ignored so callers can pass user input
        without pre-validating it.

    Notes
    -----
    * ``layer_diffs`` and ``metadata_diffs`` are preserved untouched —
      this filter only narrows the entity-level view. Callers that want
      an entities-only diff can pair this with a manual layer reset.
    """
    if not isinstance(diff, SceneDiff):
        raise TypeError(
            f"filter_by_kind: diff must be a SceneDiff; "
            f"got {type(diff).__name__}"
        )
    if not isinstance(kinds, (set, frozenset, list, tuple)):
        raise TypeError(
            f"filter_by_kind: kinds must be an iterable of str; "
            f"got {type(kinds).__name__}"
        )
    allowed = {str(k) for k in kinds}
    filtered = [ed for ed in diff.entity_diffs if ed.kind in allowed]
    total = (
        len(filtered) + len(diff.layer_diffs) + len(diff.metadata_diffs)
    )
    return SceneDiff(
        scene_a_name=diff.scene_a_name,
        scene_b_name=diff.scene_b_name,
        entity_diffs=filtered,
        layer_diffs=list(diff.layer_diffs),
        metadata_diffs=dict(diff.metadata_diffs),
        total_changes=total,
    )


def merge_diffs(*diffs: SceneDiff) -> SceneDiff:
    """Merge multiple :class:`SceneDiff` instances into one.

    Later diffs win on conflicting entity ids, layer operations, and
    metadata keys — this mirrors the semantics a rebase-style tool wants
    when stacking successive edits.

    Notes
    -----
    * The result's ``scene_a_name`` is taken from the first diff and
      ``scene_b_name`` from the last, so the merged range spans the
      full history.
    * When an entity id appears in both an earlier ``removed`` diff and
      a later ``added`` diff the later ``added`` wins (net effect:
      replace).
    * ``field_deltas`` from successive ``modified`` diffs are merged
      key-by-key (later values overwrite earlier).
    """
    if not diffs:
        raise ValueError("merge_diffs: at least one diff is required")
    for i, d in enumerate(diffs):
        if not isinstance(d, SceneDiff):
            raise TypeError(
                f"merge_diffs: diffs[{i}] must be a SceneDiff; "
                f"got {type(d).__name__}"
            )

    entity_state: dict[str, EntityDiff] = {}
    # Preserve first-seen order for deterministic iteration.
    order: list[str] = []

    for d in diffs:
        for ed in d.entity_diffs:
            eid = ed.entity_id
            if eid not in entity_state:
                order.append(eid)
                entity_state[eid] = EntityDiff(
                    entity_id=eid,
                    kind=ed.kind,
                    before=(None if ed.before is None else dict(ed.before)),
                    after=(None if ed.after is None else dict(ed.after)),
                    field_deltas=dict(ed.field_deltas),
                )
                continue
            existing = entity_state[eid]
            # Later wins on kind + after snapshot. field_deltas merge.
            existing.kind = ed.kind
            if ed.after is not None:
                existing.after = dict(ed.after)
            elif ed.kind == "removed":
                existing.after = None
            # Preserve the earliest 'before' — it's the true source.
            if existing.before is None and ed.before is not None:
                existing.before = dict(ed.before)
            merged_deltas = dict(existing.field_deltas)
            for k, v in ed.field_deltas.items():
                merged_deltas[k] = v
            existing.field_deltas = merged_deltas

    merged_entities = [entity_state[eid] for eid in order]

    # Layer ops: later wins. Track final state as add/remove per name.
    layer_state: dict[str, str] = {}
    layer_order: list[str] = []
    for d in diffs:
        for op, name in d.layer_diffs:
            if name not in layer_state:
                layer_order.append(name)
            layer_state[name] = op
    merged_layers = [(layer_state[n], n) for n in layer_order]

    # Metadata: later wins.
    merged_metadata: dict[str, tuple[Any, Any]] = {}
    for d in diffs:
        for k, v in d.metadata_diffs.items():
            if k in merged_metadata:
                # Preserve earliest 'before', take latest 'after'.
                earlier_before = merged_metadata[k][0]
                merged_metadata[k] = (earlier_before, v[1])
            else:
                merged_metadata[k] = v

    total = (
        len(merged_entities) + len(merged_layers) + len(merged_metadata)
    )
    return SceneDiff(
        scene_a_name=diffs[0].scene_a_name,
        scene_b_name=diffs[-1].scene_b_name,
        entity_diffs=merged_entities,
        layer_diffs=merged_layers,
        metadata_diffs=merged_metadata,
        total_changes=total,
    )


__all__ = [
    "EntityDiff",
    "SceneDiff",
    "apply_diff",
    "diff_scenes",
    "filter_by_kind",
    "merge_diffs",
    "pretty_print_diff",
]
