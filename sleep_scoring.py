"""Sleep score helpers shared with rankings API (mirrors templates/index.html logic)."""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

_HOUR_EPS = 1.0 / 3600.0
MIN_VALID_SLEEP_HOURS = 0.5  # 30 minutes; shorter sleeps are invalid for scoring
MAX_SCORABLE_SLEEP_HOURS = 16.0
SLEEP_POINT_WINDOW_DAYS = 7
AROUND_RANKING_WINDOW_DAYS = 7
RANKING_WINDOW_DAYS = 28
RANKING_MIN_RECORDS = 3
RANKING_INELIGIBLE_MESSAGE = "Need at least 3 sleep records\nwithin the last 28 days."
AROUND_RANKING_INELIGIBLE_MESSAGE = "Need at least 3 sleep records\nwithin the last 7 days."


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


def is_valid_sleep_hours(hours: float) -> bool:
    """True when duration is scorable (≥30 min, finite, non-negative)."""
    if not math.isfinite(hours) or hours < 0:
        return False
    return hours >= MIN_VALID_SLEEP_HOURS


def clamp_sleep_point(score: float | int | None) -> int:
    if score is None or not math.isfinite(float(score)):
        return 0
    return int(round(max(0.0, min(100.0, float(score)))))


def effective_sleep_hours_from_ms(duration_ms: float | int | None) -> float:
    """Clamp abnormally long sleeps so scoring stays stable."""
    try:
        raw = float(duration_ms or 0)
    except (TypeError, ValueError):
        raw = 0.0
    if not math.isfinite(raw):
        return 0.0
    hours = max(0.0, raw / 3_600_000)
    if not math.isfinite(hours):
        return 0.0
    if hours > MAX_SCORABLE_SLEEP_HOURS:
        return MAX_SCORABLE_SLEEP_HOURS
    return hours


def parse_iso_datetime(iso: str | None) -> datetime | None:
    if not iso:
        return None
    try:
        return datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def parse_as_of_datetime(as_of: str | None) -> datetime:
    parsed = parse_iso_datetime(as_of) if as_of else None
    if parsed is not None:
        return parsed
    return datetime.now(timezone.utc)


def _to_utc_timestamp(dt: datetime) -> float:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc).timestamp()
    return dt.astimezone(timezone.utc).timestamp()


def history_indices_in_window(
    history: list,
    as_of: datetime,
    days: int = RANKING_WINDOW_DAYS,
) -> list[int]:
    """Indices of nights whose bedAt falls in (as_of - days, as_of] (UTC comparison)."""
    if not isinstance(history, list):
        return []
    end_ts = _to_utc_timestamp(as_of)
    start_ts = end_ts - days * 86400
    indices: list[int] = []
    for i, entry in enumerate(history):
        if not isinstance(entry, dict) or not entry.get("bedAt"):
            continue
        bed = parse_iso_datetime(str(entry["bedAt"]))
        if bed is None:
            continue
        bed_ts = _to_utc_timestamp(bed)
        if start_ts < bed_ts <= end_ts:
            indices.append(i)
    return indices


def duration_hours_score(hours: float, lo: float, hi: float) -> int:
    if is_near_zero_sleep_hours(hours):
        return 0
    if hours < lo:
        return round(25 + (hours / lo) * 75)
    if hours > hi:
        return max(45, round(100 - min(50, (hours - hi) * 8)))
    return 100


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
    hours_slept = effective_sleep_hours_from_ms(entry.get("durationMs"))
    if not is_valid_sleep_hours(hours_slept):
        return 0

    dur_lo, dur_hi = recommended_sleep_range_hours(age)
    diff_h = abs(actual_h - rec_h)
    bedtime_score = sleep_score_from_bedtime_diff_hours(diff_h)
    duration_score = duration_hours_score(hours_slept, dur_lo, dur_hi)
    return clamp_sleep_point((bedtime_score + duration_score) / 2)


def compute_latest_sleep_score(age: int | None, bucket: dict) -> int | None:
    history = bucket.get("history") if isinstance(bucket.get("history"), list) else []
    if not history:
        return None
    return _score_history_entry(age, history, len(history) - 1)


def compute_weekly_average_sleep_point(
    age: int | None,
    bucket: dict,
    as_of: datetime | None = None,
) -> int:
    """Average Sleep Point across scorable nights in the last 7 days (device asOf time)."""
    history = bucket.get("history") if isinstance(bucket.get("history"), list) else []
    if not history:
        return 0
    ref = as_of or datetime.now(timezone.utc)
    indices = history_indices_in_window(history, ref, SLEEP_POINT_WINDOW_DAYS)
    total = 0
    count = 0
    for i in indices:
        score = _score_history_entry(age, history, i)
        if score is None:
            continue
        total += int(score)
        count += 1
    if count == 0:
        return 0
    return round(total / count)


def ranking_user_stats(
    age: int | None,
    bucket: dict,
    as_of: datetime,
    window_days: int = RANKING_WINDOW_DAYS,
) -> dict | None:
    """Ranking stats for one user; None when fewer than RANKING_MIN_RECORDS in window."""
    history = bucket.get("history") if isinstance(bucket.get("history"), list) else []
    indices = history_indices_in_window(history, as_of, window_days)
    scores: list[int] = []
    for i in indices:
        entry = history[i]
        if not isinstance(entry, dict):
            continue
        hours = effective_sleep_hours_from_ms(entry.get("durationMs"))
        if not is_valid_sleep_hours(hours):
            continue
        score = _score_history_entry(age, history, i)
        if score is None:
            continue
        scores.append(int(score))
    if len(scores) < RANKING_MIN_RECORDS:
        return None
    weekly_sum = sum(scores)
    weekly_avg = round(weekly_sum / len(scores))
    return {
        "weekly_sum": weekly_sum,
        "weekly_avg": weekly_avg,
        "record_count": len(scores),
    }


def _users_for_ranking_window(
    participants: list[dict],
    as_of: datetime,
    window_days: int,
) -> list[dict]:
    users: list[dict] = []
    for row in participants:
        email = str(row.get("email") or "").strip().lower()
        if not email:
            continue
        age = row.get("age")
        if age is not None:
            try:
                age = int(age)
            except (TypeError, ValueError):
                age = None
        bucket = row.get("bucket") if isinstance(row.get("bucket"), dict) else {}
        stats = ranking_user_stats(age, bucket, as_of, window_days=window_days)
        if stats is None:
            continue
        country_raw = str(row.get("country") or "").strip()
        name = str(row.get("name") or "").strip() or "Sleeper"
        users.append(
            {
                "email": email,
                "name": name,
                "country": country_raw,
                "weeklySleepPoint": int(stats["weekly_sum"]),
                "weeklyAvg": int(stats["weekly_avg"]),
                "recordCount": int(stats["record_count"]),
            }
        )
    users.sort(
        key=lambda u: (
            -u["weeklySleepPoint"],
            -u["recordCount"],
            u["name"].lower(),
        )
    )
    return users


def _sleepers_from_users(users: list[dict], viewer_email_norm: str) -> list[dict]:
    sleepers: list[dict] = []
    for rank, u in enumerate(users, start=1):
        row: dict = {
            "rank": rank,
            "name": u["name"],
            "country": u["country"],
            "score": u["weeklySleepPoint"],
        }
        if viewer_email_norm and u["email"] == viewer_email_norm:
            row["email"] = u["email"]
        sleepers.append(row)
    return sleepers


def _viewer_from_users(
    users: list[dict],
    viewer_email_norm: str,
    ineligible_message: str,
) -> dict:
    viewer: dict = {
        "eligible": False,
        "message": ineligible_message,
        "rank": None,
        "score": None,
    }
    if not viewer_email_norm:
        return viewer
    for i, u in enumerate(users):
        if u["email"] != viewer_email_norm:
            continue
        return {
            "eligible": True,
            "message": "",
            "rank": i + 1,
            "score": u["weeklySleepPoint"],
        }
    return viewer


def build_ranking_leaderboard(
    participants: list[dict],
    as_of: datetime,
    viewer_email: str | None = None,
) -> dict:
    """Top Sleepers & nations: 28 days; Around Your Rank: 7 days."""
    viewer_email_norm = str(viewer_email or "").strip().lower()

    users_top = _users_for_ranking_window(participants, as_of, RANKING_WINDOW_DAYS)
    users_around = _users_for_ranking_window(participants, as_of, AROUND_RANKING_WINDOW_DAYS)

    sleepers = _sleepers_from_users(users_top, viewer_email_norm)
    around_sleepers = _sleepers_from_users(users_around, viewer_email_norm)

    by_country: dict[str, list[int]] = {}
    for u in users_top:
        country = u["country"]
        if not country:
            continue
        by_country.setdefault(country, []).append(int(u["weeklyAvg"]))

    nation_rows: list[dict] = []
    for country, avgs in by_country.items():
        nation_rows.append(
            {
                "country": country,
                "score": round(sum(avgs) / len(avgs)),
            }
        )
    nation_rows.sort(key=lambda x: (-x["score"], x["country"].lower()))

    nations: list[dict] = []
    for rank, row in enumerate(nation_rows[:50], start=1):
        nations.append({"rank": rank, "country": row["country"]})

    viewer = _viewer_from_users(users_around, viewer_email_norm, AROUND_RANKING_INELIGIBLE_MESSAGE)
    viewer_top = _viewer_from_users(users_top, viewer_email_norm, RANKING_INELIGIBLE_MESSAGE)

    return {
        "sleepers": sleepers[:50],
        "aroundSleepers": around_sleepers[:50],
        "nations": nations[:50],
        "viewer": viewer,
        "viewerTop": viewer_top,
    }


def compute_total_growth_points(age: int | None, bucket: dict) -> int:
    """Sum of Sleep Points for every recorded night since signup."""
    history = bucket.get("history") if isinstance(bucket.get("history"), list) else []
    total = 0
    for i in range(len(history)):
        score = _score_history_entry(age, history, i)
        if score is None or score <= 0:
            continue
        total += int(score)
    return total


def sum_hours_last_nights(
    history: list,
    nights: int = 7,
    as_of: datetime | None = None,
) -> float:
    ref = as_of or datetime.now(timezone.utc)
    indices = history_indices_in_window(history if isinstance(history, list) else [], ref, nights)
    total = 0.0
    for i in indices:
        entry = history[i]
        if not isinstance(entry, dict):
            continue
        total += effective_sleep_hours_from_ms(entry.get("durationMs"))
    return total


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
