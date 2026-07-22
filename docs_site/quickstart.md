# Quickstart

Install the engine:

```bash
pip install "pharos-engine[editor]"
```

Run the ragdoll demo (headless):

```bash
python PharosEngineExamples/examples/hello_ragdoll.py --no-gif
```

Boot the notebook editor:

```bash
python -c "import pharos_engine as pe; pe.Engine().run_editor()"
```

## Two-line render

```python
from pharos_engine import App
app = App()
app.load_model("bunny.obj").move_to(0.0, 0.0, 0.0)
app.run(max_frames=1)
```

## Remote control (Sprint 6)

```python
from pharos_engine import App
app = App(enable_http=True, http_port=8787)
# curl http://localhost:8787/api/health → {"status":"ok"}
```

Then open `docs/http_bridge_example.html` in a browser and paste
the token from `~/.pharos/http_token`.

See [Extensions](extensions.md) for writing plugins that add panels,
themes, importers, or HTTP routes.
