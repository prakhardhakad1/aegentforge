"""Async-path integration test (httpx AsyncClient + pytest-asyncio): a run
executes to completion entirely on the caller's event loop."""

from __future__ import annotations

import asyncio
from typing import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient

from app.db.base import init_db
from app.main import app


@pytest.fixture()
async def async_client() -> AsyncIterator[AsyncClient]:
    init_db()  # ASGITransport does not run lifespan; ensure schema + seeds
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


async def test_run_lifecycle_on_async_client(async_client: AsyncClient) -> None:
    created = await async_client.post(
        "/api/missions", json={"goal": "Async client lifecycle mission"}
    )
    assert created.status_code == 201
    mission_id = created.json()["id"]

    started = await async_client.post(f"/api/missions/{mission_id}/runs", json={})
    assert started.status_code == 201
    run_id = started.json()["id"]

    final_status = None
    for _ in range(200):
        snapshot = (await async_client.get(f"/api/runs/{run_id}")).json()
        final_status = snapshot["run"]["status"]
        if final_status in ("succeeded", "failed", "partial"):
            break
        await asyncio.sleep(0.05)

    assert final_status == "succeeded"
    snapshot = (await async_client.get(f"/api/runs/{run_id}")).json()
    assert snapshot["events"]
    assert snapshot["events"][-1]["type"] == "run_finished"

    events_response = await async_client.get(
        f"/api/runs/{run_id}/events", params={"after_seq": 1}
    )
    assert events_response.status_code == 200
    assert events_response.json()["events"][0]["seq"] == 2
