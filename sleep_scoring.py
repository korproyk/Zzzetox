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


MIN_USER_AGE = 10
MAX_USER_AGE = 24
DEFAULT_USER_AGE = 18


def recommended_bedtime_sleep_hours(age: int | None) -> float:
    if age is None:
        a = DEFAULT_USER_AGE
    else:
        a = min(MAX_USER_AGE, max(MIN_USER_AGE, int(age)))
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


def _score_history_entry(age: int | None, history: list, index: int) -> int | None:
    if index < 0 or index >= len(history):
        return None
    entry = history[index]
    if not isinstance(entry, dict) or not entry.get("bedAt"):
        return None
    actual_h = bed_at_to_sleep_hours(str(entry["bedAt"]))
    if actual_h is None:
        return None
    rec_h = recommended_bedtime_sleep_hours(age)
    hours_slept = max(0.0, float(entry.get("durationMs") or 0) / 3_600_000)
    dur_lo, dur_hi = recommended_sleep_range_hours(age)
    prefix = history[: index + 1]

    if is_near_zero_sleep_hours(hours_slept):
        return zero_sleep_special_score(prefix, dur_lo)

    diff_h = abs(actual_h - rec_h)
    bedtime_score = sleep_score_from_bedtime_diff_hours(diff_h)
    duration_score = duration_hours_score(hours_slept, dur_lo, dur_hi)
    return round((bedtime_score + duration_score) / 2)


def compute_latest_sleep_score(age: int | None, bucket: dict) -> int | None:
    history = bucket.get("history") if isinstance(bucket.get("history"), list) else []
    if not history:
        return None
    return _score_history_entry(age, history, len(history) - 1)


def compute_best_sleep_score(age: int | None, bucket: dict) -> int | None:
    """Highest scorable night in history (used when the same account syncs from multiple devices)."""
    history = bucket.get("history") if isinstance(bucket.get("history"), list) else []
    if not history:
        return None
    best: int | None = None
    for i in range(len(history)):
        score = _score_history_entry(age, history, i)
        if score is None or score <= 0:
            continue
        best = score if best is None else max(best, score)
    return best


def _night_key(entry: dict) -> str:
    return f"{entry.get('bedAt') or ''}|{entry.get('wokeAt') or ''}"


def merge_sleep_buckets(
    a: dict | None,
    b: dict | None,
    age: int | None = None,
) -> dict:
    """Merge two device buckets; duplicate nights keep the higher-scoring row."""
    a = a if isinstance(a, dict) else {}
    b = b if isinstance(b, dict) else {}
    combined: dict[str, dict] = {}
    for entry in list(a.get("history") or []) + list(b.get("history") or []):
        if not isinstance(entry, dict):
            continue
        key = _night_key(entry)
        prev = combined.get(key)
        if prev is None:
            combined[key] = entry
            continue
        pair = [prev, entry]
        prev_score = _score_history_entry(age, pair, 0) or 0
        new_score = _score_history_entry(age, pair, 1) or 0
        combined[key] = entry if new_score >= prev_score else prev

    merged_history = sorted(combined.values(), key=lambda e: str(e.get("bedAt") or ""))
    active = a.get("activeStartAt") or b.get("activeStartAt")
    goal = a.get("sleepGoalHours")
    if goal is None:
        goal = b.get("sleepGoalHours")
    return {
        "activeStartAt": active,
        "history": merged_history,
        "sleepGoalHours": goal,
    }
