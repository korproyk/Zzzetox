"""Sleep score helpers shared with rankings API (mirrors templates/index.html logic)."""

from __future__ import annotations

from datetime import datetime

_HOUR_EPS = 1.0 / 3600.0


def recommended_sleep_range_hours(age: int | None) -> tuple[float, float]:
    if age is None:
        return (8.0, 10.0)
    if age < 6:
        return (9.0, 12.0)
    if age <= 12:
        return (9.0, 12.0)
    if age <= 17:
        return (8.0, 10.0)
    return (7.0, 9.0)


def bed_at_to_sleep_hours(iso: str) -> float | None:
    try:
        d = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    h = d.hour + d.minute / 60 + d.second / 3600
    if h < 12:
        h += 24
    return h


def recommended_bedtime_sleep_hours(age: int | None) -> float:
    if age is None:
        a = 16
    else:
        a = min(40, max(13, int(age)))
    if a <= 15:
        return 21.5
    if a <= 18:
        return 22.0
    if a <= 22:
        return 22.5
    return 23.0


def sleep_score_from_bedtime_diff_hours(diff: float) -> int:
    d = max(0.0, diff)
    if d < 1:
        s = 100 - 10 * d
    elif d < 2:
        s = 89 - 19 * (d - 1)
    elif d < 4:
        s = 69 - (19 / 2) * (d - 2)
    elif d < 6:
        s = 49 - (19 / 2) * (d - 4)
    else:
        s = max(1.0, 29 - 7 * (d - 6))
    return round(min(100, max(1, s)))


def is_near_zero_sleep_hours(hours: float) -> bool:
    return hours <= _HOUR_EPS


def duration_hours_score(hours: float, lo: float, hi: float) -> int:
    if is_near_zero_sleep_hours(hours):
        return 0
    if hours < lo:
        return round(25 + (hours / lo) * 75)
    if hours > hi:
        return max(45, round(100 - min(50, (hours - hi) * 8)))
    return 100


def zero_sleep_special_score(history: list, dur_lo: float) -> int:
    list_slice = history[-7:] if history else []
    hours_list = [max(0.0, float(e.get("durationMs") or 0) / 3_600_000) for e in list_slice]
    zero_nights = sum(1 for h in hours_list if is_near_zero_sleep_hours(h))
    avg_h = sum(hours_list) / len(hours_list) if hours_list else 0.0
    lo = float(dur_lo) or 7.0

    if is_near_zero_sleep_hours(avg_h):
        if zero_nights >= 2 or (len(list_slice) >= 3 and zero_nights / len(list_slice) >= 0.5):
            return 0
        return 1
    if avg_h >= lo:
        return 5
    if avg_h >= lo * 0.65:
        return 4
    if avg_h >= 4:
        return 3
    return 2


def compute_latest_sleep_score(age: int | None, bucket: dict) -> int | None:
    history = bucket.get("history") if isinstance(bucket.get("history"), list) else []
    if not history:
        return None
    latest = history[-1]
    if not isinstance(latest, dict) or not latest.get("bedAt"):
        return None
    actual_h = bed_at_to_sleep_hours(str(latest["bedAt"]))
    rec_h = recommended_bedtime_sleep_hours(age)
    if actual_h is None:
        return None
    hours_slept = max(0.0, float(latest.get("durationMs") or 0) / 3_600_000)
    dur_lo, dur_hi = recommended_sleep_range_hours(age)

    if is_near_zero_sleep_hours(hours_slept):
        return zero_sleep_special_score(history, dur_lo)

    diff_h = abs(actual_h - rec_h)
    bedtime_score = sleep_score_from_bedtime_diff_hours(diff_h)
    duration_score = duration_hours_score(hours_slept, dur_lo, dur_hi)
    return round((bedtime_score + duration_score) / 2)
