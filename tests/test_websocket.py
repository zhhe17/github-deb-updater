"""Exercise a real HTTP upgrade so missing server protocol dependencies fail CI."""

import asyncio
import json
import socket
import unittest
from unittest.mock import patch

import uvicorn
from fastapi import FastAPI
from websockets import connect

from app.routers import updates


class WebSocketTests(unittest.IsolatedAsyncioTestCase):
    async def test_upgrade_route_accepts_websocket(self):
        app = FastAPI()
        app.include_router(updates.router)
        server = uvicorn.Server(
            uvicorn.Config(app, lifespan="off", log_level="error")
        )
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
            task = asyncio.create_task(server.serve(sockets=[listener]))
            try:
                async def wait_started():
                    while not server.started:
                        if task.done():
                            await task
                            self.fail("Server stopped before startup")
                        await asyncio.sleep(0.01)

                await asyncio.wait_for(wait_started(), timeout=5)
                # A missing package exercises the real route without installing anything.
                with patch.object(updates.config, "get_package", return_value=None):
                    async with connect(
                        f"ws://127.0.0.1:{port}/updates/ws/upgrade/test-missing",
                        open_timeout=5,
                    ) as websocket:
                        message = await asyncio.wait_for(websocket.recv(), timeout=5)
                        self.assertEqual(
                            json.loads(message),
                            {"status": "error", "message": "软件包不存在"},
                        )
                        await asyncio.wait_for(websocket.wait_closed(), timeout=5)
                        self.assertEqual(websocket.close_code, 1000)
            finally:
                server.should_exit = True
                await asyncio.wait_for(task, timeout=5)
