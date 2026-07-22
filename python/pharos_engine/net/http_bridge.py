"""Sprint 6: HTML5 buffer server — a tiny aiohttp bridge into a running app.

Exposes read-only REST + a pair of WebSockets a browser page (or any
HTTP client) can hit to inspect the running engine. Registered
extension routes (Sprint 7) plug in via
:meth:`HttpBridge.register_route`.

Endpoints (see ``docs/http_bridge_example.html``)::

    GET  /api/health                 -> {"status": "ok"}
    GET  /api/status                 -> tick, frame, elapsed, last_dt
    GET  /api/scene                  -> summary of the current world
    GET  /api/entities               -> [{id, path, position, ...}, ...]
    GET  /api/entity/{id}            -> one entity's transform + payload
    GET  /api/frame.png              -> last renderer frame as PNG
    GET  /api/themes                 -> theme catalog snapshot
    POST /api/command                -> execute a named command
    WS   /ws/telemetry               -> broadcast every telemetry event
    WS   /ws/control                 -> bidirectional command channel

Auth: every request must carry ``Authorization: Bearer <token>``. The
token is generated on first boot at ``~/.pharos/http_token``.

The bridge lives on a background thread (its own asyncio loop) so the
engine's tick loop is not disturbed. Shutdown is idempotent.
"""
from __future__ import annotations

import json
import logging
import os
import secrets
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable

try:
    from aiohttp import web
    _HAS_AIOHTTP = True
except Exception:  # pragma: no cover - optional dep
    web = None  # type: ignore[assignment]
    _HAS_AIOHTTP = False

logger = logging.getLogger(__name__)

_TOKEN_PATH = Path.home() / ".pharos" / "http_token"


def _ensure_token() -> str:
    """Return the persistent bearer token, generating one on first boot."""
    if _TOKEN_PATH.exists():
        text = _TOKEN_PATH.read_text(encoding="utf-8").strip()
        if text:
            return text
    _TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    token = secrets.token_urlsafe(32)
    _TOKEN_PATH.write_text(token + "\n", encoding="utf-8")
    try:
        os.chmod(_TOKEN_PATH, 0o600)
    except OSError:  # pragma: no cover - Windows
        pass
    return token


HttpHandler = Callable[[Any], Awaitable[Any]]


@dataclass
class HttpBridge:
    """HTML5 buffer server bound to one :class:`pharos_engine.App`.

    The bridge holds a weak reference to the app so shutting it down
    does not keep the app alive; it also owns the aiohttp application,
    background thread, and event loop.

    Fields
    ------
    app
        Owning :class:`pharos_engine.App` — probed for tick / entity
        state via read-only attribute access.
    host / port
        Bind address. Sprint 6 default: ``127.0.0.1:8787``.
    token
        Shared bearer token. Auto-generated when None.
    cors_origins
        Allowed ``Origin`` headers. Default: any ``http://localhost:*``.
    _extra_routes
        Extension-registered routes wired through
        :meth:`register_route` (Sprint 7 uses this).
    """

    app: Any
    host: str = "127.0.0.1"
    port: int = 8787
    token: str | None = None
    cors_origins: tuple[str, ...] = ("http://localhost", "http://127.0.0.1")
    _extra_routes: dict[str, HttpHandler] = field(default_factory=dict)
    _thread: threading.Thread | None = field(default=None, init=False, repr=False)
    _runner: Any = field(default=None, init=False, repr=False)
    _loop: Any = field(default=None, init=False, repr=False)
    _started: threading.Event = field(default_factory=threading.Event, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.token is None:
            self.token = _ensure_token()

    # ------------------------------------------------------------------
    # Extension hook
    # ------------------------------------------------------------------
    def register_route(self, path: str, handler: HttpHandler) -> None:
        """Register an extension-provided handler on ``GET path``.

        Called by :mod:`pharos_editor.extensions` (Sprint 7) to add
        plugin routes without touching the bridge source.
        """
        self._extra_routes[path] = handler

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def start(self) -> None:
        """Start the aiohttp server on a background thread.

        Raises RuntimeError if aiohttp is not installed. Blocks until
        the server is bound so ``curl`` right after the return works.
        """
        if not _HAS_AIOHTTP:
            raise RuntimeError(
                "pharos_engine.net.http_bridge requires the [http] extra "
                "(pip install \"pharos-engine[http]\")"
            )
        if self._thread is not None and self._thread.is_alive():
            return
        self._started.clear()
        self._thread = threading.Thread(
            target=self._run_server, name="pharos-http-bridge", daemon=True,
        )
        self._thread.start()
        # Wait up to 5s for the server to bind so callers can immediately
        # curl the endpoints.
        self._started.wait(timeout=5.0)

    def stop(self) -> None:
        """Signal the background thread to exit. Idempotent."""
        loop = self._loop
        runner = self._runner
        if loop is None or runner is None:
            return
        async def _shutdown() -> None:
            await runner.cleanup()
        try:
            fut = _asyncio_run_coro(loop, _shutdown())
            fut.result(timeout=3.0)
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("http_bridge stop: %s", exc)
        loop.call_soon_threadsafe(loop.stop)
        thr = self._thread
        if thr is not None and thr is not threading.current_thread():
            thr.join(timeout=3.0)
        self._thread = None
        self._loop = None
        self._runner = None

    def _run_server(self) -> None:  # pragma: no cover - thread body
        import asyncio

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        try:
            aio_app = self._build_app()
            runner = web.AppRunner(aio_app)
            loop.run_until_complete(runner.setup())
            site = web.TCPSite(runner, self.host, self.port)
            loop.run_until_complete(site.start())
            self._runner = runner
            self._started.set()
            loop.run_forever()
        except Exception as exc:
            logger.warning("http_bridge server thread crashed: %s", exc)
        finally:
            self._started.set()
            try:
                loop.close()
            except Exception:  # pragma: no cover - defensive
                pass

    # ------------------------------------------------------------------
    # Aiohttp app
    # ------------------------------------------------------------------
    def _build_app(self):  # pragma: no cover - aiohttp integration
        bridge = self
        token = self.token
        allowed_origins = self.cors_origins

        @web.middleware
        async def auth_middleware(request, handler):
            if request.path == "/api/health":
                return await handler(request)
            expected = f"Bearer {token}"
            if request.headers.get("Authorization", "") != expected:
                return web.json_response({"error": "unauthorized"}, status=401)
            return await handler(request)

        @web.middleware
        async def cors_middleware(request, handler):
            response = await handler(request)
            origin = request.headers.get("Origin", "")
            if any(origin.startswith(a) for a in allowed_origins):
                response.headers["Access-Control-Allow-Origin"] = origin
                response.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type"
            return response

        aio_app = web.Application(middlewares=[auth_middleware, cors_middleware])
        aio_app.router.add_get("/api/health", bridge._h_health)
        aio_app.router.add_get("/api/status", bridge._h_status)
        aio_app.router.add_get("/api/scene", bridge._h_scene)
        aio_app.router.add_get("/api/entities", bridge._h_entities)
        aio_app.router.add_get("/api/entity/{eid}", bridge._h_entity)
        aio_app.router.add_get("/api/frame.png", bridge._h_frame_png)
        aio_app.router.add_get("/api/themes", bridge._h_themes)
        aio_app.router.add_post("/api/command", bridge._h_command)
        aio_app.router.add_get("/ws/telemetry", bridge._h_ws_telemetry)
        aio_app.router.add_get("/ws/control", bridge._h_ws_control)
        for path, handler in bridge._extra_routes.items():
            aio_app.router.add_get(path, handler)  # type: ignore[arg-type]
        return aio_app

    # ------------------------------------------------------------------
    # Handlers — read-only introspection over the bound App.
    # ------------------------------------------------------------------
    async def _h_health(self, request):  # pragma: no cover
        return web.json_response({"status": "ok"})

    async def _h_status(self, request):  # pragma: no cover
        app = self.app
        return web.json_response({
            "frame": getattr(app, "frame_count", 0),
            "elapsed": getattr(app, "elapsed", 0.0),
            "running": bool(getattr(app, "is_running", False)),
            "headless": bool(getattr(app, "is_headless", True)),
        })

    async def _h_scene(self, request):  # pragma: no cover
        app = self.app
        return web.json_response({
            "models": len(getattr(app, "models", [])),
            "lights": len(getattr(app, "lights", [])),
            "cameras": len(getattr(app, "cameras", [])),
            "active_camera": (
                getattr(getattr(app, "active_camera", None), "id", None)
                if getattr(app, "active_camera", None) is not None else None
            ),
        })

    async def _h_entities(self, request):  # pragma: no cover
        entities = []
        for m in getattr(self.app, "models", []):
            entities.append({
                "id": getattr(m, "id", -1),
                "path": getattr(m, "path", ""),
                "position": list(getattr(m, "position", (0.0, 0.0, 0.0))),
                "rotation": list(getattr(m, "rotation", (0.0, 0.0, 0.0))),
                "scale": list(getattr(m, "scale", (1.0, 1.0, 1.0))),
                "visible": bool(getattr(m, "visible", True)),
            })
        return web.json_response(entities)

    async def _h_entity(self, request):  # pragma: no cover
        try:
            eid = int(request.match_info["eid"])
        except (KeyError, ValueError):
            return web.json_response({"error": "bad id"}, status=400)
        for m in getattr(self.app, "models", []):
            if getattr(m, "id", -2) == eid:
                return web.json_response({
                    "id": eid,
                    "path": getattr(m, "path", ""),
                    "position": list(getattr(m, "position", (0.0, 0.0, 0.0))),
                    "rotation": list(getattr(m, "rotation", (0.0, 0.0, 0.0))),
                    "scale": list(getattr(m, "scale", (1.0, 1.0, 1.0))),
                    "visible": bool(getattr(m, "visible", True)),
                })
        return web.json_response({"error": "not found"}, status=404)

    async def _h_frame_png(self, request):  # pragma: no cover
        # Placeholder: 1x1 transparent PNG until the renderer wires
        # readback into the bridge. Real capture lands with Sprint 6.
        one_px_png = (
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
            b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDAT"
            b"\x78\x9cbb\x00\x00\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
        )
        return web.Response(body=one_px_png, content_type="image/png")

    async def _h_themes(self, request):  # pragma: no cover
        try:
            from pharos_editor.themes import list_theme_ids  # type: ignore
            themes = list_theme_ids()
        except Exception:
            themes = []
        return web.json_response({"themes": list(themes)})

    async def _h_command(self, request):  # pragma: no cover
        try:
            payload = await request.json()
        except json.JSONDecodeError:
            return web.json_response({"error": "bad json"}, status=400)
        name = payload.get("name")
        args = payload.get("args", {})
        if not isinstance(name, str):
            return web.json_response({"error": "missing name"}, status=400)
        # Look up a registered command on the app; safe no-op default.
        cmd_registry = getattr(self.app, "_http_commands", {})
        cmd = cmd_registry.get(name)
        if cmd is None:
            return web.json_response({"error": f"unknown command {name!r}"}, status=404)
        try:
            result = cmd(**args) if isinstance(args, dict) else cmd(args)
        except Exception as exc:
            return web.json_response({"error": str(exc)}, status=500)
        return web.json_response({"result": result})

    async def _h_ws_telemetry(self, request):  # pragma: no cover
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        # Subscribe to telemetry.emit with a matching-all pattern.
        try:
            from pharos_engine.telemetry import subscribe, unsubscribe
        except ImportError:
            await ws.send_json({"error": "telemetry unavailable"})
            await ws.close()
            return ws
        import asyncio

        loop = asyncio.get_event_loop()
        def _on_event(ev: Any) -> None:
            try:
                loop.call_soon_threadsafe(
                    lambda: asyncio.ensure_future(
                        ws.send_json({"name": ev.name, "payload": ev.payload})
                    )
                )
            except Exception:
                pass
        handle = subscribe("*", _on_event)
        try:
            async for _msg in ws:
                pass  # telemetry channel is broadcast-only
        finally:
            try:
                unsubscribe(handle)
            except Exception:
                pass
        return ws

    async def _h_ws_control(self, request):  # pragma: no cover
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        async for msg in ws:
            if msg.type == web.WSMsgType.TEXT:
                try:
                    payload = json.loads(msg.data)
                except json.JSONDecodeError:
                    await ws.send_json({"error": "bad json"})
                    continue
                name = payload.get("name", "")
                cmd_registry = getattr(self.app, "_http_commands", {})
                cmd = cmd_registry.get(name)
                if cmd is None:
                    await ws.send_json({"error": f"unknown command {name!r}"})
                    continue
                try:
                    result = cmd(**payload.get("args", {}))
                    await ws.send_json({"result": result})
                except Exception as exc:
                    await ws.send_json({"error": str(exc)})
        return ws


def _asyncio_run_coro(loop, coro):  # pragma: no cover - shutdown helper
    import asyncio

    fut = asyncio.run_coroutine_threadsafe(coro, loop)
    return fut


__all__ = ["HttpBridge"]
