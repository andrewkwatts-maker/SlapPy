"""Common base class for post-process pass wrappers.

Eliminates the boilerplate shared by ``BloomPass``, ``TonemapPass``,
``OutlinePass``, ``VignettePass``, ``ContactShadowsPass``, etc.  Every
post-process pass class implements roughly the same five things:

1. ``__init__`` with per-kwarg type/range validation (the
   ``_validation`` helpers).
2. ``from_config(cls, cfg)`` reading a nested config section like
   ``cfg.rendering.bloom`` with graceful fallback to defaults.
3. ``make_pass()`` returning a :class:`PostProcessPass` record for the
   executor.
4. ``params_to_bytes()`` packing a per-pass UBO via ``struct.pack``
   (or, when the executor does the packing, ``params_dict()``
   returning the dict that gets fed to ``_make_params_buffer``).
5. ``apply_cpu()`` / ``resolve_numpy()`` for the testable subset (out
   of scope for the base class — too varied per pass).

The base class generalises steps 2-4 via declarative class
attributes so subclasses only declare the static schema once:

* ``label``           — chain label (``"bloom"``, ``"outline"``, …).
* ``SHADER``          — WGSL file under ``shaders/``.
* ``ENTRY``           — WGSL entry point (defaults to ``"main"``).
* ``CONFIG_KEY``      — dotted config path, e.g. ``"rendering.bloom"``.
* ``PARAMS_LAYOUT``   — optional ``(struct_fmt, fields)`` tuple.  When
  set, :meth:`params_to_bytes` packs the per-pass UBO directly so the
  executor can be handed ``raw_params_bytes``.  When ``None`` the
  subclass falls back to ``params_dict()`` and lets the executor pack.

Byte-for-byte parity with the legacy hand-rolled ``struct.pack`` calls
is enforced by ``tests/test_post_process_base.py``.  The Sprint 2D
runtime splice helper depends on the UBO offsets staying stable — the
base class merely centralises *how* those bytes are produced; it does
not move any offsets around.

Design tradeoff
---------------
We intentionally support **both** UBO packing modes (per-pass
``raw_params_bytes`` and executor-side ``params`` dict packing) because
the existing executor splice helper already handles both — forcing
every pass onto one path would require either rewriting the executor
or rewriting every params-dict pass's WGSL bindings.  Subclasses opt
in to direct packing by declaring ``PARAMS_LAYOUT``; otherwise the
legacy params-dict route stays intact bit-for-bit.
"""
from __future__ import annotations

import struct
from typing import Any, ClassVar, Optional, Protocol, Sequence, runtime_checkable

from .chain import PostProcessPass
from ._ubo import UboField, compute_offsets, pack_struct


# ---------------------------------------------------------------------------
# PostProcessParams protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class PostProcessParams(Protocol):
    """Structural type for ``PARAMS_LAYOUT``-driven post-process passes.

    Any object that produces a packed-UBO ``bytes`` payload via
    ``pack_params()`` satisfies this protocol. The shipped
    :class:`PostProcessPassBase` subclasses (BloomPass, TonemapPass,
    OutlinePass, …) expose their packed UBO via :meth:`params_to_bytes`;
    :meth:`PostProcessPassBase.pack_params` is an alias kept in sync
    with that method so every concrete pass already conforms.

    The executor's runtime splice helper depends on the byte layout of
    these UBOs being stable; this Protocol formalises the contract so
    third-party passes (extensions, mods, generated chains) can be type-
    checked against it without inheriting from
    :class:`PostProcessPassBase`.

    Marked ``@runtime_checkable`` so tests and tooling can verify
    conformance via ``isinstance(obj, PostProcessParams)``.
    """

    def pack_params(self) -> bytes:  # noqa: D401
        ...  # pragma: no cover — Protocol stub


# ---------------------------------------------------------------------------
# Marker for "subclass must define this"
# ---------------------------------------------------------------------------

class _Required:
    """Sentinel — class attribute MUST be overridden by the subclass."""
    def __repr__(self) -> str:  # pragma: no cover — debug aid
        return "<REQUIRED>"


_REQUIRED = _Required()


# ---------------------------------------------------------------------------
# Base class
# ---------------------------------------------------------------------------

class PostProcessPassBase:
    """Common scaffolding for post-process pass wrapper classes.

    Subclasses must declare:

    * ``label``        — string label used by the chain.
    * ``SHADER``       — WGSL filename relative to ``shaders/``.

    Subclasses may declare:

    * ``ENTRY``        — WGSL entry-point name (default ``"main"``).
    * ``CONFIG_KEY``   — dotted path on the config object that
      :meth:`from_config` traverses (e.g. ``"rendering.bloom"``).
      When set, :meth:`from_config` is provided by the base class and
      walks the path with ``getattr`` fallback; missing sections return
      ``cls()`` with defaults.  When unset, subclasses override
      :meth:`from_config` themselves.
    * ``PARAMS_LAYOUT`` — either:

      - the legacy ``(struct_fmt, fields)`` tuple where
        ``struct_fmt`` is the ``struct.pack`` format string and
        ``fields`` is a sequence of attribute-name strings whose
        values get packed in order, **or**
      - a list of :class:`~pharos_engine.post_process._ubo.UboField`
        objects describing the std140-aligned UBO schema.  In this
        case :meth:`params_to_bytes` packs via the shared
        :func:`~pharos_engine.post_process._ubo.pack_struct` helper
        and subclasses provide field values via :meth:`_field_values`
        returning a ``dict`` (when overriding) or via attribute
        lookup on ``self``.

      When set, :meth:`params_to_bytes` packs the per-pass UBO
      directly.  When ``None`` (default), subclasses override
      :meth:`params_to_bytes` themselves or rely on the executor
      packing the ``params`` dict.
    * ``EXTRA_BINDINGS`` — optional tuple/list of binding-name strings
      that are merged into the ``params`` sideband dict by
      :meth:`make_pass` from the keyword arguments forwarded to it.
      Used by passes (TAA, GTAO, …) whose shader reads extra texture
      bindings beyond the standard ping/pong pair.
    * ``DEPENDS_ON``   — optional tuple/list of pass labels that must
      precede this one (mirrors ``RenderPass.depends_on``); forwarded
      to ``PostProcessPass.depends_on``.
    * ``BLOB_SIZE``    — optional explicit byte-length of the packed
      UBO.  When set, :meth:`params_to_bytes` truncates or right-pads
      the output of :func:`pack_struct` to exactly this many bytes.
      Used for legacy layouts (e.g. VolumetricFog) whose total size
      is not a multiple of 16 — the helper's std140 round-up would
      otherwise over-pad them.
    """

    # ---- declarative schema (subclasses override) -----------------------

    label: ClassVar[str] = ""
    SHADER: ClassVar[Any] = _REQUIRED
    ENTRY: ClassVar[str] = "main"
    CONFIG_KEY: ClassVar[Optional[str]] = None
    PARAMS_LAYOUT: ClassVar[Any] = None
    DEPENDS_ON: ClassVar[Sequence[str]] = ()
    EXTRA_BINDINGS: ClassVar[Sequence[str]] = ()
    BLOB_SIZE: ClassVar[Optional[int]] = None

    # ---- subclass-init enforcement --------------------------------------

    def __init_subclass__(cls, **kwargs: Any) -> None:
        """Enforce required class-attr declarations at subclass-creation time.

        Raises a clear ``TypeError`` *as soon as the subclass is defined*
        — much friendlier than a downstream ``NameError`` when somebody
        calls ``make_pass()`` on a half-finished subclass.  Skipped for
        intermediate abstract subclasses that mark themselves with
        ``_abstract = True``.
        """
        super().__init_subclass__(**kwargs)
        if getattr(cls, "_abstract", False):
            return
        if cls.SHADER is _REQUIRED or not isinstance(cls.SHADER, str):
            raise TypeError(
                f"{cls.__name__}: must declare a class attribute "
                f"`SHADER: ClassVar[str]` naming the WGSL file under "
                f"shaders/ (or set `_abstract = True` for an "
                f"intermediate abstract subclass)."
            )
        if not cls.label:
            raise TypeError(
                f"{cls.__name__}: must declare a non-empty `label` "
                f"class attribute (used as the chain key)."
            )

    # ---- config glue ----------------------------------------------------

    @classmethod
    def from_config(cls, cfg: Any) -> "PostProcessPassBase":
        """Build an instance from a nested config object.

        Walks ``cls.CONFIG_KEY`` (a dotted attribute path like
        ``"rendering.bloom"``) on ``cfg``.  Missing sections fall back
        to ``cls()`` with defaults — the documented backward-compat
        contract for every from_config in the package.

        Subclasses with non-trivial mapping (renamed fields, fallback
        sections, type coercions) should override this method.
        """
        if cls.CONFIG_KEY is None:
            raise NotImplementedError(
                f"{cls.__name__}: declare `CONFIG_KEY` or override "
                f"`from_config` — the base-class template needs one of "
                f"these to know where to read defaults from."
            )
        section: Any = cfg
        for part in cls.CONFIG_KEY.split("."):
            try:
                section = getattr(section, part)
            except AttributeError:
                return cls()  # type: ignore[call-arg]

        # Walk the declared field list (the keys in PARAMS_LAYOUT[1]
        # or the constructor's defaults).  We copy any attribute that
        # the section exposes, preserving the constructor defaults for
        # everything else.
        kwargs: dict[str, Any] = {}
        for field_name in cls._config_field_names():
            if hasattr(section, field_name):
                kwargs[field_name] = getattr(section, field_name)
        return cls(**kwargs)  # type: ignore[call-arg]

    @classmethod
    def _config_field_names(cls) -> tuple[str, ...]:
        """Field names from PARAMS_LAYOUT (or () if none declared).

        Subclasses with config keys that don't map 1:1 onto
        ``PARAMS_LAYOUT`` (e.g. colour tuples vs flat r/g/b/a fields)
        should override this to return the *constructor* kwarg names.

        Handles both the legacy ``(fmt, fields)`` tuple form and the
        new ``[UboField, ...]`` list form.
        """
        layout = cls.PARAMS_LAYOUT
        if layout is None:
            return ()
        if cls._is_ubo_field_layout(layout):
            return tuple(
                f.name for f in layout if not f.name.startswith("_")
            )
        # Legacy ``(fmt, fields)`` tuple.
        return tuple(
            f for f in layout[1] if not f.startswith("_")
        )

    @staticmethod
    def _is_ubo_field_layout(layout: Any) -> bool:
        """Return True when ``layout`` is a list/tuple of :class:`UboField`."""
        if not isinstance(layout, (list, tuple)):
            return False
        if not layout:
            return False
        if isinstance(layout, tuple) and len(layout) == 2 and isinstance(layout[0], str):
            # Legacy ``(fmt, fields)`` tuple has a string format as the
            # first element — distinguishes it from a 2-element UboField list.
            return False
        return all(isinstance(f, UboField) for f in layout)

    # ---- UBO packing ----------------------------------------------------

    def params_to_bytes(self) -> bytes:
        """Pack the per-pass UBO using the declarative ``PARAMS_LAYOUT``.

        Supports two layout styles:

        * Legacy ``(struct_fmt, fields)`` tuple — each name is read via
          ``getattr(self, name)`` (overridable through
          :meth:`_field_values`) and packed positionally by
          ``struct.pack``.
        * New ``[UboField, ...]`` list — values come from
          :meth:`_field_values` returning a ``dict``, which is then
          fed to :func:`pack_struct` for std140-aligned packing.

        When ``BLOB_SIZE`` is set the result is truncated or
        right-padded to that exact size — preserves legacy layouts
        whose total length is not a multiple of 16.

        Raises
        ------
        NotImplementedError
            If the subclass declares no ``PARAMS_LAYOUT`` and does not
            override ``params_to_bytes``.
        """
        layout = self.PARAMS_LAYOUT
        if layout is None:
            raise NotImplementedError(
                f"{type(self).__name__}: declare `PARAMS_LAYOUT` or "
                f"override `params_to_bytes`."
            )
        if self._is_ubo_field_layout(layout):
            values = self._field_values()
            if not isinstance(values, dict):
                # Default ``_field_values`` returns a tuple; for the
                # UboField path subclasses must override to return a
                # dict.  Auto-derive from attribute names so simple
                # passes don't need any override.
                values = {
                    f.name: (0 if f.name.startswith("_") else getattr(self, f.name))
                    for f in layout
                }
            raw = pack_struct(layout, values)
        else:
            fmt, _fields = layout
            raw = struct.pack(fmt, *self._field_values())
        size = self.BLOB_SIZE
        if size is not None:
            if len(raw) > size:
                raw = raw[:size]
            elif len(raw) < size:
                raw = raw + b"\x00" * (size - len(raw))
        return raw

    def _field_values(self) -> Any:
        """Return the ordered ``struct.pack`` args tuple, or dict for UboField.

        Default implementation reads each declared field from ``self``
        with ``getattr``.  Pad fields (names starting with ``_``) are
        emitted as ``0`` (legacy tuple form).  For the UboField-list
        layout the default ``params_to_bytes`` builds the values dict
        directly from attribute lookup, so subclasses only need to
        override this when fields need coercion (bool → u32, tuples →
        vec3, etc.) — return a dict in that case.
        """
        layout = self.PARAMS_LAYOUT
        if layout is None:
            return ()
        if self._is_ubo_field_layout(layout):
            return {
                f.name: (0 if f.name.startswith("_") else getattr(self, f.name))
                for f in layout
            }
        _fmt, fields = layout
        out: list[Any] = []
        for name in fields:
            if name.startswith("_"):
                out.append(0)
            else:
                out.append(getattr(self, name))
        return tuple(out)

    def pack_params(self) -> bytes:
        """Alias for :meth:`params_to_bytes` matching the
        :class:`PostProcessParams` protocol.

        Third-party / extension passes that don't inherit from
        :class:`PostProcessPassBase` only need to implement
        ``pack_params`` to satisfy the structural type used by the
        executor's UBO splice helper. The base class provides this alias
        so every shipped pass conforms without code changes.
        """
        return self.params_to_bytes()

    # ---- params dict (executor-side packing route) ---------------------

    def params_dict(self) -> dict[str, Any]:
        """Return the executor ``params`` dict (UBO + binding sideband).

        Default implementation returns ``{}``; subclasses that take the
        executor-packing route (no ``PARAMS_LAYOUT``) override this to
        return the same dict their hand-rolled ``make_pass`` previously
        produced.  Subclasses with ``PARAMS_LAYOUT`` declared do *not*
        need to override — the bytes go through ``raw_params_bytes``
        and ``params`` carries only sideband data.
        """
        return {}

    # ---- pass factory ---------------------------------------------------

    def make_pass(self, **bindings: Any) -> PostProcessPass:
        """Build the :class:`PostProcessPass` record for the executor.

        When ``PARAMS_LAYOUT`` is declared, the UBO is packed directly
        and handed to ``raw_params_bytes`` — the executor's splice
        helper still patches dispatch-time fields (width/height) by
        byte offset, so this path is byte-for-byte compatible with the
        old hand-rolled ``struct.pack`` calls.

        When ``PARAMS_LAYOUT`` is ``None`` (legacy executor-pack
        route), the ``params_dict()`` becomes the ``params`` field and
        the executor's ``_make_params_buffer`` handles layout.

        Keyword args matching :attr:`EXTRA_BINDINGS` names are merged
        into the params sideband dict.  Unknown kwargs raise
        ``TypeError`` so a typo (e.g. ``albedo_text=`` instead of
        ``albedo_tex=``) fails loudly at call time.

        Subclasses with non-trivial binding setup (renamed kwargs,
        defaults, etc.) should override this and call
        ``super().make_pass(**bindings)`` to get the base record.
        """
        extra = tuple(self.EXTRA_BINDINGS)
        unknown = [k for k in bindings if k not in extra]
        if unknown:
            raise TypeError(
                f"{type(self).__name__}.make_pass: unknown binding "
                f"kwargs {unknown!r}; expected one of {list(extra)!r}"
            )

        raw: Optional[bytes]
        if self.PARAMS_LAYOUT is not None:
            raw = self.params_to_bytes()
            params: dict[str, Any] = self.params_dict()
        else:
            raw = None
            params = self.params_dict()

        if extra:
            params = dict(params)
            for name in extra:
                if name in bindings:
                    params[name] = bindings[name]

        return PostProcessPass(
            shader_path=self.SHADER,
            label=self.label,
            entry_point=self.ENTRY,
            raw_params_bytes=raw,
            params=params if params else {},
            depends_on=list(self.DEPENDS_ON),
        )


__all__ = ["PostProcessParams", "PostProcessPassBase"]
