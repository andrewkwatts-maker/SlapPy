# Extensions

See [`docs/EXTENSIONS.md`](../docs/EXTENSIONS.md) in the source tree
for the full plugin author guide, plus the working sample under
`extensions/example_mod/`.

## One-page summary

Declare an entry point in your `pyproject.toml`:

```toml
[project.entry-points."pharos_editor.plugins"]
my_mod = "my_mod:register"
```

Implement `register(registry)`:

```python
def register(registry):
    registry.register_panel("my_mod", make_panel)
    registry.register_theme("path/to/theme.yaml")
    registry.register_http_route("/api/mods/my/hello", handler)
    registry.register_command("my.greet", cmd)
```

Install + boot:

```bash
pip install ./my_mod
pharos-edit
```
