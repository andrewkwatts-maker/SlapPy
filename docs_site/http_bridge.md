# HTTP bridge

The HTML5 buffer server (Sprint 6) exposes REST + WebSocket endpoints
into a running Pharos app.

## Enable

```python
from pharos_engine import App
app = App(enable_http=True, http_port=8787)
```

## Endpoints

| Method | Path                       | Notes |
| ------ | -------------------------- | ----- |
| GET    | `/api/health`              | Health check, no auth. |
| GET    | `/api/status`              | Frame + elapsed + running state. |
| GET    | `/api/scene`               | Counts of models / lights / cameras. |
| GET    | `/api/entities`            | Every model handle. |
| GET    | `/api/entity/{id}`         | One model handle. |
| GET    | `/api/frame.png`           | Last rendered frame (placeholder PNG). |
| GET    | `/api/themes`              | Every theme discovered by ThemeCatalog. |
| POST   | `/api/command`             | Dispatch a registered command. |
| WS     | `/ws/telemetry`            | Broadcast of every telemetry.emit. |
| WS     | `/ws/control`              | Bidirectional command channel. |

## Auth

Every request except `/api/health` needs `Authorization: Bearer
<token>`. The token lives at `~/.pharos/http_token` (0600 on POSIX),
generated on first boot via `secrets.token_urlsafe(32)`.

## Sample page

Open `docs/http_bridge_example.html` in any browser, point it at the
running app, and paste your token.
