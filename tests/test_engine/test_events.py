"""Tests for EventManager and RoastEvent."""

import pytest

from roastmaster.engine.events import EventManager, EventType, RoastEvent

# ---------------------------------------------------------------------------
# Manual event marking
# ---------------------------------------------------------------------------


def test_mark_event_returns_roast_event():
    em = EventManager()
    ev = em.mark_event(EventType.FIRST_CRACK, elapsed=300.0, temperature=195.0)
    assert isinstance(ev, RoastEvent)
    assert ev.event_type == EventType.FIRST_CRACK
    assert ev.elapsed == pytest.approx(300.0)
    assert ev.temperature == pytest.approx(195.0)


def test_mark_event_stores_event():
    em = EventManager()
    em.mark_event(EventType.DROP, elapsed=600.0, temperature=210.0)
    assert len(em.events) == 1


def test_mark_multiple_different_events():
    em = EventManager()
    em.mark_event(EventType.CHARGE, elapsed=0.0, temperature=160.0)
    em.mark_event(EventType.FIRST_CRACK, elapsed=300.0, temperature=195.0)
    em.mark_event(EventType.DROP, elapsed=480.0, temperature=210.0)
    assert len(em.events) == 3


# ---------------------------------------------------------------------------
# get_event
# ---------------------------------------------------------------------------


def test_get_event_returns_correct_event():
    em = EventManager()
    em.mark_event(EventType.FIRST_CRACK, elapsed=300.0, temperature=195.0)
    ev = em.get_event(EventType.FIRST_CRACK)
    assert ev is not None
    assert ev.event_type == EventType.FIRST_CRACK
    assert ev.elapsed == pytest.approx(300.0)


def test_get_event_returns_none_when_not_recorded():
    em = EventManager()
    assert em.get_event(EventType.SECOND_CRACK) is None


def test_get_event_with_multiple_events():
    em = EventManager()
    em.mark_event(EventType.CHARGE, elapsed=0.0, temperature=165.0)
    em.mark_event(EventType.DROP, elapsed=500.0, temperature=212.0)
    assert em.get_event(EventType.CHARGE) is not None
    assert em.get_event(EventType.DROP) is not None
    assert em.get_event(EventType.FIRST_CRACK) is None


# ---------------------------------------------------------------------------
# Duplicate event handling (last-write-wins)
# ---------------------------------------------------------------------------


def test_duplicate_event_replaces_previous():
    em = EventManager()
    em.mark_event(EventType.FIRST_CRACK, elapsed=300.0, temperature=195.0)
    em.mark_event(EventType.FIRST_CRACK, elapsed=310.0, temperature=196.0)
    # Only one event of that type should exist
    assert len([e for e in em.events if e.event_type == EventType.FIRST_CRACK]) == 1


def test_duplicate_event_keeps_latest_values():
    em = EventManager()
    em.mark_event(EventType.FIRST_CRACK, elapsed=300.0, temperature=195.0)
    em.mark_event(EventType.FIRST_CRACK, elapsed=310.0, temperature=196.0)
    ev = em.get_event(EventType.FIRST_CRACK)
    assert ev is not None
    assert ev.elapsed == pytest.approx(310.0)
    assert ev.temperature == pytest.approx(196.0)


def test_total_event_count_with_duplicate():
    em = EventManager()
    em.mark_event(EventType.CHARGE, elapsed=0.0, temperature=160.0)
    em.mark_event(EventType.FIRST_CRACK, elapsed=300.0, temperature=195.0)
    em.mark_event(EventType.FIRST_CRACK, elapsed=310.0, temperature=196.0)
    assert len(em.events) == 2


# ---------------------------------------------------------------------------
# Turning point auto-detection
# ---------------------------------------------------------------------------


def _feed_decreasing_then_increasing(
    em: EventManager,
    start_temp: float = 170.0,
    drop_by: float = 20.0,
    n_drop: int = 8,
    n_rise: int = 5,
    sample_interval: float = 5.0,
) -> list[RoastEvent | None]:
    """Feed BT that first drops then rises, return all update_bt return values."""
    results = []
    elapsed = 0.0
    temp = start_temp
    step = drop_by / n_drop

    for _ in range(n_drop):
        results.append(em.update_bt(elapsed, temp))
        elapsed += sample_interval
        temp -= step

    # Now rise
    for _ in range(n_rise):
        results.append(em.update_bt(elapsed, temp))
        elapsed += sample_interval
        temp += step

    return results


def test_turning_point_detected():
    em = EventManager()
    results = _feed_decreasing_then_increasing(em)
    detected = [r for r in results if r is not None]
    assert len(detected) == 1
    assert detected[0].event_type == EventType.TURNING_POINT


def test_turning_point_stored_in_events():
    em = EventManager()
    _feed_decreasing_then_increasing(em)
    tp = em.get_event(EventType.TURNING_POINT)
    assert tp is not None


def test_turning_point_temperature_is_minimum():
    em = EventManager()
    _feed_decreasing_then_increasing(em, start_temp=170.0, drop_by=20.0, n_drop=8)
    tp = em.get_event(EventType.TURNING_POINT)
    assert tp is not None
    # TP temperature should be at or near the minimum of the BT series
    assert tp.temperature <= 170.0


def test_no_turning_point_if_bt_never_rises():
    em = EventManager()
    # Feed only descending data — no turning point should be detected
    elapsed = 0.0
    temp = 170.0
    for _ in range(20):
        result = em.update_bt(elapsed, temp)
        assert result is None
        elapsed += 5.0
        temp -= 1.0
    assert em.get_event(EventType.TURNING_POINT) is None


def test_no_turning_point_on_insufficient_rise():
    """Only 2 rising readings (< _TP_CONFIRM_READINGS=3) should not trigger TP."""
    em = EventManager()
    # Drop for a while
    elapsed = 0.0
    temp = 170.0
    for _ in range(8):
        em.update_bt(elapsed, temp)
        elapsed += 5.0
        temp -= 2.0
    # Only 2 rising readings
    for _ in range(2):
        em.update_bt(elapsed, temp)
        elapsed += 5.0
        temp += 2.0
    assert em.get_event(EventType.TURNING_POINT) is None


def test_turning_point_only_detected_once():
    em = EventManager()
    results = _feed_decreasing_then_increasing(em, n_rise=10)
    detected = [r for r in results if r is not None]
    assert len(detected) == 1


def test_update_bt_returns_none_before_tp():
    em = EventManager()
    elapsed = 0.0
    temp = 170.0
    # Feed descending values — should all return None
    for _ in range(5):
        result = em.update_bt(elapsed, temp)
        assert result is None
        elapsed += 5.0
        temp -= 2.0


# ---------------------------------------------------------------------------
# Reset
# ---------------------------------------------------------------------------


def test_reset_clears_events():
    em = EventManager()
    em.mark_event(EventType.FIRST_CRACK, elapsed=300.0, temperature=195.0)
    em.reset()
    assert em.events == []


def test_reset_clears_bt_history():
    em = EventManager()
    _feed_decreasing_then_increasing(em)
    em.reset()
    assert em._bt_history == []


def test_reset_allows_new_tp_detection():
    em = EventManager()
    _feed_decreasing_then_increasing(em)
    em.reset()
    results = _feed_decreasing_then_increasing(em)
    detected = [r for r in results if r is not None]
    assert len(detected) == 1


def test_reset_clears_tp_detected_flag():
    em = EventManager()
    _feed_decreasing_then_increasing(em)
    assert em._tp_detected is True
    em.reset()
    assert em._tp_detected is False


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_single_sample_returns_none():
    em = EventManager()
    result = em.update_bt(0.0, 170.0)
    assert result is None


def test_flat_temperature_no_tp():
    em = EventManager()
    elapsed = 0.0
    for _ in range(10):
        result = em.update_bt(elapsed, 170.0)
        assert result is None
        elapsed += 5.0


def test_all_event_types_can_be_manually_marked():
    em = EventManager()
    for i, event_type in enumerate(EventType):
        em.mark_event(event_type, elapsed=float(i * 60), temperature=float(150 + i * 5))
    for event_type in EventType:
        assert em.get_event(event_type) is not None
