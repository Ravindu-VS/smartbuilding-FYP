"""Shared fixtures for the test suite (run from the repository root: python -m pytest)."""
import asyncio
import os
import socket
import sys
import threading
import time

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture(scope="session")
def mqtt_broker():
    """An in-process MQTT broker (amqtt) on a free local port; yields (host, port)."""
    amqtt_broker = pytest.importorskip("amqtt.broker")
    port = free_port()
    cfg = {"listeners": {"default": {"type": "tcp", "bind": f"127.0.0.1:{port}"}}, "sys_interval": 0,
           "auth": {"allow-anonymous": True, "plugins": ["auth_anonymous"]}, "topic-check": {"enabled": False}}
    loop = asyncio.new_event_loop()
    broker = amqtt_broker.Broker(cfg, loop=loop)

    def run():
        asyncio.set_event_loop(loop)
        loop.run_until_complete(broker.start())
        loop.run_forever()

    threading.Thread(target=run, daemon=True).start()
    deadline = time.time() + 10
    while time.time() < deadline:
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.5).close()
            break
        except OSError:
            time.sleep(0.1)
    yield "127.0.0.1", port
    asyncio.run_coroutine_threadsafe(broker.shutdown(), loop)


def wait_for(cond, timeout=10.0, step=0.05):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if cond():
            return True
        time.sleep(step)
    return False
