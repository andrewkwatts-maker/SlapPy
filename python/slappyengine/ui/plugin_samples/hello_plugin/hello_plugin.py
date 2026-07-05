"""Sample GG3 plugin: prints a greeting through each lifecycle hook.

Drop the containing directory into ``~/.slappyengine/extensions/`` to
see it auto-load in the editor.
"""
from __future__ import annotations

MESSAGES: list[str] = []


def on_load() -> None:
    """Called immediately after the entry module is imported."""
    msg = "Loaded from GG3 sample"
    MESSAGES.append(msg)
    print(msg)


def on_shell_ready() -> None:
    """Called after the editor shell has finished bootstrapping."""
    msg = "GG3 sample: shell ready"
    MESSAGES.append(msg)
    print(msg)


def on_unload() -> None:
    """Called when the registry unloads this plugin."""
    msg = "GG3 sample: unloading"
    MESSAGES.append(msg)
    print(msg)


def greet(name: str = "world") -> str:
    """Trivial capability entry point — used by find_by_capability tests."""
    return f"hello, {name}"
