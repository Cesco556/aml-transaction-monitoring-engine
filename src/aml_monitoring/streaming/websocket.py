"""WebSocket alert notifications: broadcast new alerts to connected clients."""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect

from aml_monitoring.streaming.events import on_alert_created, remove_listener

log = logging.getLogger(__name__)


class AlertConnectionManager:
    """Manage WebSocket connections and broadcast alerts."""

    def __init__(self) -> None:
        self._connections: list[WebSocket] = []
        self._registered = False

    async def connect(self, websocket: WebSocket) -> None:
        """Accept a WebSocket connection and register for alerts."""
        await websocket.accept()
        self._connections.append(websocket)
        log.info("WebSocket client connected (%d total)", len(self._connections))
        if not self._registered:
            on_alert_created(self._on_alert)
            self._registered = True

    def disconnect(self, websocket: WebSocket) -> None:
        """Remove a disconnected client."""
        try:
            self._connections.remove(websocket)
        except ValueError:
            pass
        log.info("WebSocket client disconnected (%d remaining)", len(self._connections))
        if not self._connections and self._registered:
            remove_listener(self._on_alert)
            self._registered = False

    async def broadcast(self, data: dict[str, Any]) -> None:
        """Send alert data to all connected clients."""
        if not self._connections:
            return
        message = json.dumps(data, default=str)
        disconnected: list[WebSocket] = []
        for ws in self._connections:
            try:
                await ws.send_text(message)
            except Exception:
                disconnected.append(ws)
        for ws in disconnected:
            self.disconnect(ws)

    async def _on_alert(self, alert_data: dict[str, Any]) -> None:
        """Event bus callback — broadcast alert to all WebSocket clients."""
        await self.broadcast(alert_data)

    @property
    def connection_count(self) -> int:
        return len(self._connections)


# Singleton manager
alert_manager = AlertConnectionManager()


async def websocket_alerts_endpoint(websocket: WebSocket) -> None:
    """WebSocket endpoint handler for /ws/alerts."""
    await alert_manager.connect(websocket)
    try:
        while True:
            # Keep connection alive; client can send pings or messages
            await websocket.receive_text()
    except WebSocketDisconnect:
        alert_manager.disconnect(websocket)
    except Exception:
        alert_manager.disconnect(websocket)
