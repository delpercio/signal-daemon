"""Regression tests for the delivery queue's accounting and retry behaviour."""

from unittest import mock

import pytest

from signal_daemon.queue import DeliveryQueue, QueueSender
from signal_daemon.schema import EventType, Provider, SignalEvent


def make_event(i: int) -> SignalEvent:
    event = SignalEvent(
        device_id="dev",
        provider=Provider.CLAUDE_CODE,
        session_id=f"s{i}",
        event_type=EventType.CONVERSATION_TURN,
        payload={"i": i},
    )
    event.compute_hashes()
    return event


@pytest.fixture
def queue(tmp_path):
    return DeliveryQueue(db_path=tmp_path / "q.db")


class _Response:
    def __init__(self, status_code, text="ok"):
        self.status_code = status_code
        self.text = text


class TestEnqueue:
    def test_roundtrip(self, queue):
        assert queue.enqueue_many([make_event(i) for i in range(5)]) == 5
        assert queue.pending_count() == 5

    def test_duplicate_event_id_rejected(self, queue):
        event = make_event(1)
        assert queue.enqueue(event) is True
        assert queue.enqueue(event) is False
        assert queue.pending_count() == 1

    def test_delivery_state_persists_across_connections(self, queue, tmp_path):
        queue.enqueue_many([make_event(i) for i in range(3)])
        rows = queue.fetch_batch(3)
        queue.mark_delivered([r["id"] for r in rows])

        reopened = DeliveryQueue(db_path=tmp_path / "q.db")
        assert reopened.pending_count() == 0
        assert reopened.stats()["delivered"] == 3


class TestDrainAccounting:
    """drain() previously reported batch_size per loop and dropped the last batch."""

    @pytest.mark.parametrize("count", [1, 7, 50, 120])
    def test_reports_exact_delivered_count(self, queue, count):
        queue.enqueue_many([make_event(i) for i in range(count)])
        sender = QueueSender(queue=queue, anton_url="http://x", api_key="k", batch_size=50)

        with mock.patch("httpx.post", return_value=_Response(200)):
            reported = sender.drain()

        assert reported == count
        assert queue.stats()["delivered"] == count
        assert queue.pending_count() == 0

    def test_empty_queue_reports_zero(self, queue):
        sender = QueueSender(queue=queue, anton_url="http://x", api_key="k")
        with mock.patch("httpx.post", return_value=_Response(200)) as post:
            assert sender.drain() == 0
        post.assert_not_called()


class TestPoisonEvents:
    """A permanently-rejected event must not block the queue forever."""

    def test_attempts_are_capped(self, queue):
        queue.enqueue_many([make_event(i) for i in range(3)])
        sender = QueueSender(
            queue=queue, anton_url="http://x", api_key="k", max_attempts=3
        )

        with mock.patch("httpx.post", return_value=_Response(400, "bad event")):
            for _ in range(5):
                sender.send_batch()

        assert queue.fetch_batch(10, max_attempts=3) == []
        assert queue.stuck_count(3) == 3

    def test_drain_terminates_on_permanent_failure(self, queue):
        queue.enqueue_many([make_event(i) for i in range(2)])
        sender = QueueSender(
            queue=queue,
            anton_url="http://x",
            api_key="k",
            max_attempts=2,
            retry_base=0.0,
            retry_max=0.0,
        )
        with mock.patch("httpx.post", return_value=_Response(500)):
            assert sender.drain(max_iterations=10) == 0
        assert queue.stuck_count(2) == 2

    def test_healthy_events_flow_past_a_stuck_one(self, queue):
        queue.enqueue(make_event(0))
        queue.db.execute("UPDATE events SET attempts = 99 WHERE id = 1")
        queue.enqueue_many([make_event(i) for i in range(1, 4)])

        sender = QueueSender(
            queue=queue, anton_url="http://x", api_key="k", max_attempts=10
        )
        with mock.patch("httpx.post", return_value=_Response(200)):
            assert sender.drain() == 3

        assert queue.stuck_count(10) == 1


class TestStats:
    def test_counts(self, queue):
        queue.enqueue_many([make_event(i) for i in range(4)])
        queue.mark_delivered([r["id"] for r in queue.fetch_batch(2)])
        stats = queue.stats()
        assert stats["total"] == 4
        assert stats["delivered"] == 2
        assert stats["pending"] == 2

    def test_stuck_count_disabled_when_no_cap(self, queue):
        queue.enqueue(make_event(0))
        assert queue.stuck_count(0) == 0
