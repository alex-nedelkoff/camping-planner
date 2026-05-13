"""In-process pub/sub for SSE fan-out."""

import asyncio

import pytest

from app.services import broadcast


@pytest.mark.asyncio
async def test_subscriber_receives_published_event():
    bus = broadcast.Bus()
    q = bus.subscribe("t1")
    await bus.publish("t1", {"type": "food.upsert", "row": {"id": 1}})
    event = await asyncio.wait_for(q.get(), timeout=0.5)
    assert event["row"]["id"] == 1


@pytest.mark.asyncio
async def test_publish_to_other_trip_not_received():
    bus = broadcast.Bus()
    q = bus.subscribe("t1")
    await bus.publish("t2", {"type": "x"})
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(q.get(), timeout=0.1)


@pytest.mark.asyncio
async def test_full_queue_drops_for_that_subscriber_only():
    bus = broadcast.Bus(max_queue=2)
    slow = bus.subscribe("t1")
    fast = bus.subscribe("t1")
    for i in range(4):
        await bus.publish("t1", {"i": i})
    # fast consumer should still get the first 2 (the rest dropped for both)
    got = []
    try:
        while True:
            got.append(await asyncio.wait_for(fast.get(), timeout=0.05))
    except asyncio.TimeoutError:
        pass
    assert len(got) == 2  # capped at queue size
    assert slow.qsize() == 2


@pytest.mark.asyncio
async def test_unsubscribe_removes_queue():
    bus = broadcast.Bus()
    q = bus.subscribe("t1")
    bus.unsubscribe("t1", q)
    await bus.publish("t1", {"type": "x"})
    assert q.qsize() == 0
