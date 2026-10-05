"""WS /api/runs/{run_id}/stream: history-first, replay, ping/pong, errors."""

from __future__ import annotations

import pytest
from conftest import demo_run
from fastapi.testclient import TestClient
from starlette.testclient import WebSocketDisconnect

_ = demo_run  # session fixture reference


def _drain_history(ws) -> list[dict]:
    """Read messages until a terminal event arrives; return them."""
    messages = [ws.receive_json()]
    while messages[-1].get("type") not in ("run_finished", "run_failed"):
        messages.append(ws.receive_json())
    return messages


def test_ws_sends_history_first(client: TestClient, demo_run) -> None:
    run_id = demo_run["run_id"]
    with client.websocket_connect(f"/api/runs/{run_id}/stream") as ws:
        messages = _drain_history(ws)
    assert messages[0]["type"] == "run_started"
    assert messages[0]["seq"] == 1
    assert messages[-1]["type"] == "run_finished"
    seqs = [m["seq"] for m in messages]
    assert seqs == sorted(seqs)


def test_ws_ping_pong(client: TestClient, demo_run) -> None:
    run_id = demo_run["run_id"]
    with client.websocket_connect(f"/api/runs/{run_id}/stream") as ws:
        _drain_history(ws)
        ws.send_json({"type": "ping"})
        pong = ws.receive_json()
    assert pong["type"] == "pong"
    assert pong["run_id"] == run_id
    assert pong["ts"].endswith("Z")


def test_ws_replay_after_seq(client: TestClient, demo_run) -> None:
    run_id = demo_run["run_id"]
    with client.websocket_connect(f"/api/runs/{run_id}/stream") as ws:
        _drain_history(ws)
        ws.send_json({"type": "replay", "after_seq": 0})
        replayed = _drain_history(ws)
    assert replayed[0]["seq"] == 1
    assert replayed[-1]["type"] == "run_finished"


def test_ws_replay_invalid_after_seq_gets_error(client: TestClient, demo_run) -> None:
    run_id = demo_run["run_id"]
    with client.websocket_connect(f"/api/runs/{run_id}/stream") as ws:
        _drain_history(ws)
        ws.send_json({"type": "replay", "after_seq": -5})
        error = ws.receive_json()
    assert error["type"] == "error"
    assert error["payload"]["error"] == "bad_replay"


def test_ws_unknown_message_type_gets_error(client: TestClient, demo_run) -> None:
    run_id = demo_run["run_id"]
    with client.websocket_connect(f"/api/runs/{run_id}/stream") as ws:
        _drain_history(ws)
        ws.send_json({"type": "dance"})
        error = ws.receive_json()
        assert error["type"] == "error"
        assert error["payload"]["error"] == "unknown_type"

        ws.send_json("this is not json")
        bad = ws.receive_json()
        assert bad["type"] == "error"
        assert bad["payload"]["error"] == "bad_message"


def test_ws_unknown_run_closes_4404(client: TestClient) -> None:
    with pytest.raises(WebSocketDisconnect) as excinfo:
        with client.websocket_connect("/api/runs/nope/stream") as ws:
            error = ws.receive_json()
            assert error["type"] == "error"
            assert error["payload"]["error"] == "not_found"
            ws.receive_json()  # next frame is the close
    assert excinfo.value.code == 4404


def test_ws_requires_api_key_when_set(client: TestClient, demo_run, override_settings) -> None:
    override_settings(api_key="ws-secret")
    run_id = demo_run["run_id"]

    # no key -> accept + error + close(4401)
    with pytest.raises(WebSocketDisconnect) as excinfo:
        with client.websocket_connect(f"/api/runs/{run_id}/stream") as ws:
            error = ws.receive_json()
            assert error["type"] == "error"
            assert error["payload"]["error"] == "unauthorized"
            ws.receive_json()  # next frame is the close
    assert excinfo.value.code == 4401

    # correct key via query param -> works
    with client.websocket_connect(
        f"/api/runs/{run_id}/stream?api_key=ws-secret"
    ) as ws:
        messages = _drain_history(ws)
    assert messages[0]["type"] == "run_started"

    # correct key via header -> works too
    with client.websocket_connect(
        f"/api/runs/{run_id}/stream",
        headers={"x-api-key": "ws-secret"},
    ) as ws:
        first = ws.receive_json()
    assert first["type"] == "run_started"
