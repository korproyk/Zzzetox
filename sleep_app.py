"""
Sleep Challenge — Flask server
Serves templates/index.html from GET / via render_template, POST /api/ai-feedback,
and POST /api/validate-nickname (nickname policy).

Sleep level images: `level1.png`–`level5.png` in the same folder as this file are served at
`/static/images/levelN.png` (see `sleep_level_images_dispatch`); optional fallback in `static/images/`.

Time-based Start Bedtime / Wake Up button *widths* (3:1, 1:3, 1:1) live in the front end:
  templates/index.html — CSS `.sleep-controls` / `.bedtime-priority` / `.wakeup-priority`
  and JavaScript `getPriorityWindow()` + `setButtonPriorityStyles()`.

Login/signup password eye toggle (click to show/hide) is finalized in this file: see
`_inject_index_password_toggle` and `_INDEX_PASSWORD_TOGGLE_SCRIPT`.

Run:  python sleep_app.py
Then open http://127.0.0.1:5000/

OpenAI (Mac / zsh 예시)
-----------------------
  한 세션에서만 쓰기 (키는 히스토리에 남을 수 있음):
    export OPENAI_API_KEY='sk-...'
    cd /path/to/sleep_app && python sleep_app.py

  한 줄로 실행:
    OPENAI_API_KEY='sk-...' python sleep_app.py

  선택 모델 (기본 gpt-4o-mini):
    export OPENAI_MODEL='gpt-4o-mini'

  터미널을 열 때마다 자동 설정하려면 ~/.zshrc 에 export 줄을 추가한 뒤 source ~/.zshrc

키는 https://platform.openai.com/api-keys 에서 발급합니다. 로그에 API 키는 출력하지 않습니다.
"""

from __future__ import annotations

import json
import logging
import os
import re
import statistics
import urllib.error
import urllib.request
from pathlib import Path

from flask import Flask, abort, jsonify, render_template, request, send_from_directory, url_for

from account_store import get_account_store
from nickname_validation import FORBIDDEN_TERMS, nickname_validation_error

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent
TEMPLATES_DIR = ROOT / "templates"
STATIC_DIR = ROOT / "static"
app = Flask(
    __name__,
    template_folder=str(TEMPLATES_DIR),
    static_folder=str(STATIC_DIR),
    static_url_path="/static",
)

# Injected before </body> on GET /. Replaces each .password-toggle so only this logic runs:
# click count n — n=0: hidden + plain eye; n odd: visible + plain eye; n even (n>=2): hidden + eye with ~45° slash.
_INDEX_PASSWORD_TOGGLE_SCRIPT = """
<script>
(function () {
  function eye() {
    return '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7Z"/><circle cx="12" cy="12" r="3"/></svg>';
  }
  function eyeSlash() {
    return '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7Z"/><circle cx="12" cy="12" r="3"/><line x1="5" y1="19" x2="19" y2="5"/></svg>';
  }
  document.querySelectorAll(".password-toggle[data-password-for]").forEach(function (oldBtn) {
    var id = oldBtn.getAttribute("data-password-for");
    var input = document.getElementById(id);
    if (!input || !oldBtn.parentNode) return;
    var btn = oldBtn.cloneNode(false);
    btn.type = "button";
    btn.className = oldBtn.className;
    btn.setAttribute("data-password-for", id);
    oldBtn.parentNode.replaceChild(btn, oldBtn);
    var n = 0;
    function sync() {
      if (n === 0) {
        input.type = "password";
        btn.innerHTML = eye();
        btn.setAttribute("aria-label", "Show password");
        btn.setAttribute("aria-pressed", "false");
      } else if (n % 2 === 1) {
        input.type = "text";
        btn.innerHTML = eye();
        btn.setAttribute("aria-label", "Hide password");
        btn.setAttribute("aria-pressed", "true");
      } else {
        input.type = "password";
        btn.innerHTML = eyeSlash();
        btn.setAttribute("aria-label", "Show password");
        btn.setAttribute("aria-pressed", "false");
      }
    }
    sync();
    btn.addEventListener("click", function () {
      n += 1;
      sync();
    });
  });
})();
</script>
""".strip()


def _inject_index_password_toggle(html: str) -> str:
    """Append client script so password visibility + eye icons follow sleep_app rules."""
    if "_sleepAppPwToggleInjected" in html:
        return html
    marker = "<!--_sleepAppPwToggleInjected-->"
    needle = "</body>"
    i = html.lower().rfind(needle.lower())
    if i == -1:
        return html
    return html[:i] + marker + "\n" + _INDEX_PASSWORD_TOGGLE_SCRIPT + "\n" + html[i:]


@app.get("/static/images/<path:fname>")
def sleep_level_images_dispatch(fname: str):
    """
    Serve level1.png–level5.png from the app folder (same directory as sleep_app.py) first,
    then fall back to static/images/. Other files under /static/images/ are passed to the default static handler.
    """
    m = re.fullmatch(r"level([1-5])\.png", fname, re.IGNORECASE)
    if m:
        name = f"level{int(m.group(1))}.png"
        root_file = ROOT / name
        static_file = STATIC_DIR / "images" / name
        if root_file.is_file():
            return send_from_directory(str(ROOT), name, mimetype="image/png")
        if static_file.is_file():
            return send_from_directory(str(STATIC_DIR / "images"), name, mimetype="image/png")
        abort(404)
    return app.send_static_file(f"images/{fname}")


@app.route("/")
def index():
    sleep_level_image_urls = {
        str(i): url_for("static", filename=f"images/level{i}.png") for i in range(1, 6)
    }
    return _inject_index_password_toggle(
        render_template(
            "index.html",
            nickname_forbidden_terms=list(FORBIDDEN_TERMS),
            sleep_level_image_urls=sleep_level_image_urls,
        )
    )


@app.route("/api/health", methods=["GET"])
def api_health():
    """Frontend uses this to verify server-side accounts are available."""
    try:
        store = get_account_store()
        return jsonify(
            {
                "ok": True,
                "serverAuth": True,
                "userCount": store.count_users(),
                "dbPath": str(store.db_path),
            }
        )
    except Exception as exc:
        logger.exception("GET /api/health failed")
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.route("/api/validate-nickname", methods=["POST"])
def api_validate_nickname():
    """Final nickname check (same rules as client)."""
    body = request.get_json(silent=True) or {}
    name = body.get("name", "")
    err = nickname_validation_error(name)
    if err:
        return jsonify({"ok": False, "error": err})
    return jsonify({"ok": True})


def _normalize_email_api(email: str) -> str:
    return str(email or "").strip().lower()


def _auth_token_from_request() -> str | None:
    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip() or None
    return request.headers.get("X-Auth-Token", "").strip() or None


def _require_auth_email() -> str | tuple[dict, int]:
    token = _auth_token_from_request()
    if not token:
        return {"ok": False, "error": "Authentication required."}, 401
    email = get_account_store().resolve_token(token)
    if not email:
        return {"ok": False, "error": "Session expired. Please log in again."}, 401
    return email


def _auth_error_response(exc: Exception, action: str):
    logger.exception("Auth %s failed", action)
    return jsonify({"ok": False, "error": f"Server storage error during {action}. Try again."}), 500


@app.route("/api/auth/signup", methods=["POST"])
def api_auth_signup():
    """Register account on server (syncs across devices)."""
    body = request.get_json(silent=True) or {}
    email = _normalize_email_api(body.get("email", ""))
    name = str(body.get("name", "")).strip()
    country = str(body.get("country", "")).strip()
    password_hash = str(body.get("passwordHash", "")).strip()
    age = _parse_age(body.get("age"))

    if not email:
        return jsonify({"ok": False, "error": "Email is required."}), 400
    if not name:
        return jsonify({"ok": False, "error": "Nickname is required."}), 400
    if not password_hash:
        return jsonify({"ok": False, "error": "Password hash is required."}), 400
    if not country:
        return jsonify({"ok": False, "error": "Country is required."}), 400

    err = nickname_validation_error(name)
    if err:
        return jsonify({"ok": False, "error": err}), 400

    try:
        store = get_account_store()
        user = store.create_user(
            email=email,
            name=name,
            age=age,
            country=country,
            password_hash=password_hash,
            created_at=body.get("createdAt"),
        )
        token = store.issue_token(email)
    except ValueError as exc:
        if str(exc) == "email_already_registered":
            return jsonify({"ok": False, "error": "This email is already registered. Please log in."}), 409
        return _auth_error_response(exc, "signup")
    except Exception as exc:
        return _auth_error_response(exc, "signup")

    logger.info("POST /api/auth/signup email=%r db=%s", email, store.db_path)
    return jsonify({"ok": True, "user": user, "token": token})


@app.route("/api/auth/login", methods=["POST"])
def api_auth_login():
    """Verify credentials and return session token."""
    body = request.get_json(silent=True) or {}
    email = _normalize_email_api(body.get("email", ""))
    password_hash = str(body.get("passwordHash", "")).strip()

    if not email or not password_hash:
        return jsonify({"ok": False, "error": "Email and password are required."}), 400

    try:
        store = get_account_store()
        user = store.verify_login(email, password_hash)
        if not user:
            return jsonify({"ok": False, "error": "Account not found or incorrect password."}), 401
        token = store.issue_token(email)
        bucket = store.get_sleep_bucket(email)
    except Exception as exc:
        return _auth_error_response(exc, "login")

    logger.info("POST /api/auth/login email=%r db=%s", email, store.db_path)
    return jsonify({"ok": True, "user": user, "token": token, "sleepBucket": bucket})


@app.route("/api/auth/migrate-local", methods=["POST"])
def api_auth_migrate_local():
    """
    One-time upload of a device-only account created before server sync existed.
    Creates the server account if the email is not registered yet.
    """
    body = request.get_json(silent=True) or {}
    email = _normalize_email_api(body.get("email", ""))
    name = str(body.get("name", "")).strip()
    country = str(body.get("country", "")).strip()
    password_hash = str(body.get("passwordHash", "")).strip()
    age = _parse_age(body.get("age"))

    if not email or not password_hash or not name:
        return jsonify({"ok": False, "error": "Invalid migration payload."}), 400

    store = get_account_store()
    if store.get_user(email):
        user = store.verify_login(email, password_hash)
        if not user:
            return jsonify({"ok": False, "error": "Account exists with a different password."}), 409
        token = store.issue_token(email)
        return jsonify(
            {
                "ok": True,
                "user": user,
                "token": token,
                "sleepBucket": store.get_sleep_bucket(email),
                "migrated": False,
            }
        )

    try:
        user = store.create_user(
            email=email,
            name=name,
            age=age,
            country=country,
            password_hash=password_hash,
            created_at=body.get("createdAt"),
        )
    except ValueError:
        return jsonify({"ok": False, "error": "Migration failed."}), 409

    sleep_local = body.get("sleepBucket")
    if isinstance(sleep_local, dict):
        store.save_sleep_bucket(email, sleep_local)

    token = store.issue_token(email)
    logger.info("POST /api/auth/migrate-local email=%r", email)
    return jsonify(
        {
            "ok": True,
            "user": user,
            "token": token,
            "sleepBucket": store.get_sleep_bucket(email),
            "migrated": True,
        }
    )


@app.route("/api/account/sleep", methods=["GET", "PUT"])
def api_account_sleep():
    """Load or save sleep tracking data for the logged-in account."""
    auth = _require_auth_email()
    if isinstance(auth, tuple):
        payload, status = auth
        return jsonify(payload), status
    email = auth
    store = get_account_store()

    if request.method == "GET":
        return jsonify({"ok": True, "sleepBucket": store.get_sleep_bucket(email)})

    body = request.get_json(silent=True) or {}
    bucket = body.get("sleepBucket")
    if not isinstance(bucket, dict):
        return jsonify({"ok": False, "error": "sleepBucket object required."}), 400
    store.save_sleep_bucket(email, bucket)
    return jsonify({"ok": True})


def _hours(ms: float) -> float:
    return max(0.0, float(ms) / 3_600_000)


# Treat anything at or below ~1 second as zero sleep (invalid / missing night).
_HOUR_EPS = 1.0 / 3600.0


def _parse_age(age) -> int | None:
    if age is None or age == "":
        return None
    try:
        return int(float(age))
    except (TypeError, ValueError):
        return None


def recommended_sleep_range_hours(age: int | None) -> tuple[float, float]:
    """
    Age-based nightly sleep recommendations (hours), per product spec:
    - Ages 6–12: 9–12 h
    - Ages 13–17: 8–10 h  (13–18세 band, excluding 18 so 18+ can use adult range)
    - Age 18 and older: 7–9 h  (18세 이상)
    Unknown age defaults to 8–10 h (adolescent default for this app).
    Under 6: 9–12 h (same as 6–12 band).
    """
    if age is None:
        return (8.0, 10.0)
    if age < 6:
        return (9.0, 12.0)
    if 6 <= age <= 12:
        return (9.0, 12.0)
    if 13 <= age <= 17:
        return (8.0, 10.0)
    return (7.0, 9.0)


def _classify_sleep_hours(hours: float, rec_min: float, rec_max: float) -> str:
    """
    Returns: severe_shortage | insufficient | adequate | excessive
    Zero (or near-zero) sleep is always severe_shortage.
    """
    if hours <= _HOUR_EPS:
        return "severe_shortage"
    if hours < rec_min:
        return "insufficient"
    if hours > rec_max:
        return "excessive"
    return "adequate"


def _classification_label_en(kind: str) -> str:
    return {
        "severe_shortage": "severe insufficiency (0 h showing — no real sleep counted)",
        "insufficient": "below the age-based recommended range (insufficient)",
        "adequate": "within the age-based recommended range (adequate)",
        "excessive": "above the age-based recommended range (possibly excessive)",
    }[kind]


FEEDBACK_DISCLAIMER_EN = (
    "This is educational support, not medical advice. I am not a doctor and cannot diagnose conditions or prescribe "
    "treatment. If something about your sleep keeps worrying you, you might choose to speak with a parent, school "
    "counselor, or a healthcare professional — only if that feels right for you."
)

# Shown when ≥2 nights in the 7-night window are ~0 h (heuristic + required verbatim in OpenAI part 2 when flagged).
MULTIPLE_ZERO_NIGHTS_DATA_NOTICE_EN = (
    "When two or more nights in your recent window show about zero hours, there is a real chance those nights "
    "were not recorded rather than that you barely slept."
)


def _band_sentence(age_int: int | None, rec_lo: float, rec_hi: float) -> str:
    """Section 1: age-based guideline, conversational."""
    if age_int is None:
        return (
            f"1) Guideline: I do not know your age yet, so I am ballparking about "
            f"{rec_lo:.0f}–{rec_hi:.0f} hours a night — a typical range for teens."
        )
    if age_int < 6:
        return (
            f"1) Guideline: Around age {age_int}, many guides land near "
            f"{rec_lo:.0f}–{rec_hi:.0f} hours a night. Think soft target, not a test."
        )
    if 6 <= age_int <= 12:
        return (
            f"1) Guideline: Around age {age_int}, aim for about "
            f"{rec_lo:.0f}–{rec_hi:.0f} hours a night — busy weeks run a little over sometimes."
        )
    if 13 <= age_int <= 17:
        return (
            f"1) Guideline: Around age {age_int}, about "
            f"{rec_lo:.0f}–{rec_hi:.0f} hours a night is a fair sweet spot. Patterns beat one perfect night."
        )
    return (
        f"1) Guideline: Around age {age_int}, about "
        f"{rec_lo:.0f}–{rec_hi:.0f} hours a night is what a lot of handouts suggest for grown-ups."
    )


def _append_multi_zero_data_notice(
    text: str,
    *,
    multiple_zero_nights: bool,
    skip_because_both_logged_zeros: bool,
) -> str:
    """Append mandatory missing-data hint when ≥2 zero-hour nights; skip if both_logged_zeros block already covers it."""
    if not multiple_zero_nights or skip_because_both_logged_zeros:
        return text
    if MULTIPLE_ZERO_NIGHTS_DATA_NOTICE_EN in text:
        return text
    return f"{text} {MULTIPLE_ZERO_NIGHTS_DATA_NOTICE_EN}"


def _merged_sleep_status_paragraph(
    latest_h: float,
    avg_h: float,
    latest_cls: str,
    avg_cls: str,
    rec_lo: float,
    rec_hi: float,
    *,
    both_logged_zeros: bool,
    multiple_zero_nights: bool,
) -> str:
    """Section 2: current status; merges latest vs average when classification matches."""
    band = f"{rec_lo:.0f}–{rec_hi:.0f} hours"

    def short_label(cls: str) -> str:
        return {
            "severe_shortage": "way under what we would expect (almost no sleep showing)",
            "insufficient": "under the guideline range",
            "adequate": "inside the guideline range",
            "excessive": "above the guideline range",
        }[cls]

    if latest_cls == avg_cls:
        if latest_cls == "severe_shortage":
            if both_logged_zeros:
                return _append_multi_zero_data_notice(
                    (
                        f"2) Where things stand: Your last night and your recent average both read 0.0 h — "
                        f"well under the {band} that fits your age. "
                        "Since both your latest night and recent average show 0.0 hours, this may be missing or unrecorded "
                        "sleep data rather than actual sleep. "
                        "If you truly barely slept, that is serious — but two zeros in a row usually means the night never got recorded, not that you froze in place."
                    ),
                    multiple_zero_nights=multiple_zero_nights,
                    skip_because_both_logged_zeros=False,
                )
            return _append_multi_zero_data_notice(
                (
                    f"2) Where things stand: Your last night and your recent average both sit near zero — "
                    f"far under the {band} range. Quick gut check: does that match how you felt, or did a night never get saved?"
                ),
                multiple_zero_nights=multiple_zero_nights,
                skip_because_both_logged_zeros=False,
            )
        if latest_cls == "adequate":
            if abs(latest_h - avg_h) < 0.15:
                return _append_multi_zero_data_notice(
                    (
                        f"2) Where things stand: Last night and your recent average are both ~{latest_h:.1f} h — "
                        f"right in that {band} pocket for your age."
                    ),
                    multiple_zero_nights=multiple_zero_nights,
                    skip_because_both_logged_zeros=False,
                )
            return _append_multi_zero_data_notice(
                (
                    f"2) Where things stand: Last night ~{latest_h:.1f} h, recent average ~{avg_h:.1f} h — both inside the {band} band. Nice and steady."
                ),
                multiple_zero_nights=multiple_zero_nights,
                skip_because_both_logged_zeros=False,
            )
        if latest_cls == "insufficient":
            return _append_multi_zero_data_notice(
                (
                    f"2) Where things stand: Last night ~{latest_h:.1f} h, recent average ~{avg_h:.1f} h — both under the {band} guideline."
                ),
                multiple_zero_nights=multiple_zero_nights,
                skip_because_both_logged_zeros=False,
            )
        return _append_multi_zero_data_notice(
            (
                f"2) Where things stand: Last night ~{latest_h:.1f} h, recent average ~{avg_h:.1f} h — both above the top of the {band} range."
            ),
            multiple_zero_nights=multiple_zero_nights,
            skip_because_both_logged_zeros=False,
        )

    return _append_multi_zero_data_notice(
        (
            f"2) Where things stand: Last night ~{latest_h:.1f} h ({short_label(latest_cls)}), "
            f"recent average ~{avg_h:.1f} h ({short_label(avg_cls)}) — lined up next to the {band} guideline for your age."
        ),
        multiple_zero_nights=multiple_zero_nights,
        skip_because_both_logged_zeros=False,
    )


def _meaning_and_gentle_risks(
    latest_cls: str,
    avg_cls: str,
    *,
    both_logged_zeros: bool,
    multiple_zero_nights: bool,
    rec_lo: float,
    rec_hi: float,
) -> str:
    """Section 3: educational meaning; personalized, not medical."""
    shortage = {"severe_shortage", "insufficient"}
    touched_shortage = latest_cls in shortage or avg_cls in shortage
    touched_excess = latest_cls == "excessive" or avg_cls == "excessive"

    if both_logged_zeros:
        return (
            "3) Why it matters: Right now I barely have a story to react to — one honest bed-down / wake-up pair gives me something real to cheer or tweak. "
            "If you know you truly crashed that hard on sleep, lean on someone you trust in person; I am not a clinician."
        )
    if multiple_zero_nights:
        return (
            "3) Why it matters: I am not assuming this is mostly ‘short sleep’ yet — several near-zero nights in one window "
            "often mean nights never made it into the log. "
            "Once a few nights show believable hours, we can talk about real shortfall versus rhythm; until then, treat the zeros gently."
        )
    if touched_shortage:
        return (
            f"3) Why it matters: Nights under that {rec_lo:.0f}–{rec_hi:.0f} h band for you often feel like lighter focus, a quicker temper, or heavier eyelids at school — small stuff, not a verdict. "
            "Think of it as a gentle push toward more rest, not a label."
        )
    if touched_excess:
        return (
            "3) Why it matters: Long nights are often catch-up sleep. If days still feel foggy, nudge bedtime earlier a little at a time — tweak the rhythm, not the panic button."
        )
    return (
        "3) Why it matters: Hanging near your age band usually keeps daytime energy steadier. Treat these numbers like a compass, not a report card."
    )


def _practical_suggestions(
    latest_cls: str,
    avg_cls: str,
    *,
    both_logged_zeros: bool,
    multiple_zero_nights: bool,
) -> list[str]:
    """Section 4: three concrete, non-medical habits."""
    if both_logged_zeros or multiple_zero_nights:
        return [
            "Try one clean night in the app: hit Start Bedtime when you lie down, Wake Up when you rise — that fills in the hours.",
            "If you already did, glance at the times you pressed — one miss is usually why you see two zeros.",
            "When a real hour count shows up, tap for feedback again — then I can riff on your rhythm, not the zeros.",
        ]
    shortage = latest_cls in ("severe_shortage", "insufficient") or avg_cls in ("severe_shortage", "insufficient")
    if shortage:
        return [
            "Pick a wake-up time you can keep most days, then walk bedtime backward by 10–15 minutes at a time until it feels realistic.",
            "Dim the room and swap to calmer activities for 30–45 minutes before lights-out; let screens wait until morning.",
            "If you are still awake after ~20 minutes in bed, get up briefly, stretch or read something low-key, then slide back when sleepier.",
        ]
    if latest_cls == "excessive" or avg_cls == "excessive":
        return [
            "Try a little morning light soon after you wake up — it helps your body clock feel clear about “day” time.",
            "Keep naps short and earlier in the afternoon so they do not steal from your night sleep.",
            "Notice whether very late bedtimes are a habit; shifting them earlier by 15 minutes at a time is often easier than jumping an hour.",
        ]
    return [
        "Keep weekend wake times within about an hour of school days so Monday does not feel like jet lag.",
        "Hydrate through the day, but ease off caffeine in the late afternoon if you use it.",
        "When you can, a short walk or light movement helps your body feel ready for sleep later on.",
    ]


def _sleep_feedback_context(payload: dict) -> dict:
    """Shared facts for heuristic + OpenAI prompts."""
    name = (payload.get("name") or "there").strip()
    age_int = _parse_age(payload.get("age"))
    country = (payload.get("country") or "").strip()
    history = payload.get("history") or []
    if not isinstance(history, list):
        history = []

    durations: list[float] = []
    for row in history[-7:]:
        try:
            durations.append(float(row.get("durationMs", 0)))
        except (TypeError, ValueError):
            continue

    if not durations:
        return {
            "has_data": False,
            "name": name,
            "age": age_int,
            "country": country,
        }

    hours_list = [_hours(ms) for ms in durations]
    rec_lo, rec_hi = recommended_sleep_range_hours(age_int)
    latest_h = hours_list[-1]
    avg_h = statistics.mean(hours_list)
    latest_cls = _classify_sleep_hours(latest_h, rec_lo, rec_hi)
    avg_cls = _classify_sleep_hours(avg_h, rec_lo, rec_hi)
    both_logged_zeros = (
        latest_cls == "severe_shortage"
        and avg_cls == "severe_shortage"
        and latest_h <= _HOUR_EPS
        and avg_h <= _HOUR_EPS
    )
    zero_night_count = sum(1 for h in hours_list if h <= _HOUR_EPS)
    multiple_zero_nights = zero_night_count >= 2

    return {
        "has_data": True,
        "name": name,
        "age": age_int,
        "country": country,
        "rec_lo": rec_lo,
        "rec_hi": rec_hi,
        "hours_list": hours_list,
        "latest_h": latest_h,
        "avg_h": avg_h,
        "latest_cls": latest_cls,
        "avg_cls": avg_cls,
        "both_logged_zeros": both_logged_zeros,
        "zero_night_count": zero_night_count,
        "multiple_zero_nights": multiple_zero_nights,
    }


def _assessment_block_for_prompt(ctx: dict) -> str:
    if not ctx.get("has_data"):
        return "No nights with usable sleep hours in history."
    age = ctx["age"]
    age_note = f"{age} years" if age is not None else "unknown (default band 8–10 h used for recommendation)"
    both = ctx.get("both_logged_zeros")
    both_note = (
        "\nSpecial case: BOTH latest and window average are 0.0 h with severe_shortage — tell the user this often means "
        "a night never got saved or the hours did not stick; include the exact sentence: "
        "\"Since both your latest night and recent average show 0.0 hours, this may be missing or unrecorded sleep data rather than actual sleep.\" "
        "Then briefly note that if the zeros were literally true nights with no sleep, that would be a dangerous shortfall, but do not diagnose."
        if both
        else ""
    )
    multi = bool(ctx.get("multiple_zero_nights"))
    zn = int(ctx.get("zero_night_count", 0))
    multi_note = (
        f"\nSpecial case: multiple_zero_nights=true — in the up-to-7-night window, {zn} night(s) show about 0 h. "
        "Lead with the possibility that sleep was not recorded or saved for those nights; do NOT frame the overall story mainly as ordinary sleep deprivation. "
        "In part 2) Where things stand, you MUST include this exact sentence verbatim (copy exactly):\n"
        f"\"{MULTIPLE_ZERO_NIGHTS_DATA_NOTICE_EN}\"\n"
        "You may add one short friendly line after it, still avoiding a lecture."
        if multi
        else ""
    )
    return (
        f"Age: {age_note}.\n"
        f"Recommended nightly sleep for this age band: {ctx['rec_lo']:.0f}–{ctx['rec_hi']:.0f} hours.\n"
        f"Latest night: {ctx['latest_h']:.2f} h → {_classification_label_en(ctx['latest_cls'])} [code: {ctx['latest_cls']}].\n"
        f"Average over nights in window: {ctx['avg_h']:.2f} h → {_classification_label_en(ctx['avg_cls'])} [code: {ctx['avg_cls']}].\n"
        f"Nights at ~0 h in window: {zn} (multiple_zero_nights={multi}).\n"
        f"both_logged_zeros={bool(both)}\n"
        f"{both_note}"
        f"{multi_note}"
        "\nRules: If sleep is 0 h it MUST NOT be described as merely 'short sleep' or 'a little low'. "
        "Do not contradict the classification codes, but you may explain missed saves when both_logged_zeros is true. "
        "When multiple_zero_nights is true, prioritize missed recording over a shortage narrative unless the user clearly has solid hour totals."
    )


def _heuristic_feedback(payload: dict) -> str:
    ctx = _sleep_feedback_context(payload)
    name = ctx["name"]

    if not ctx.get("has_data"):
        return (
            f"Hi {name},\n\n"
            "I do not have enough nights to work with yet. Add a few when you go to bed and when you wake, and we can try again.\n\n"
            f"5) {FEEDBACK_DISCLAIMER_EN}"
        )

    age_int = ctx["age"]
    rec_lo, rec_hi = ctx["rec_lo"], ctx["rec_hi"]
    latest_h, avg_h = ctx["latest_h"], ctx["avg_h"]
    latest_cls, avg_cls = ctx["latest_cls"], ctx["avg_cls"]
    both_logged_zeros = bool(ctx.get("both_logged_zeros"))
    multiple_zero_nights = bool(ctx.get("multiple_zero_nights"))

    opening = f"Hi {name},\n\nHere is a quick read on how your nights look — coaching, not a clinic note.\n\n"

    s1 = _band_sentence(age_int, rec_lo, rec_hi)
    s2 = _merged_sleep_status_paragraph(
        latest_h,
        avg_h,
        latest_cls,
        avg_cls,
        rec_lo,
        rec_hi,
        both_logged_zeros=both_logged_zeros,
        multiple_zero_nights=multiple_zero_nights,
    )
    s3 = _meaning_and_gentle_risks(
        latest_cls,
        avg_cls,
        both_logged_zeros=both_logged_zeros,
        multiple_zero_nights=multiple_zero_nights,
        rec_lo=rec_lo,
        rec_hi=rec_hi,
    )
    tips = _practical_suggestions(
        latest_cls,
        avg_cls,
        both_logged_zeros=both_logged_zeros,
        multiple_zero_nights=multiple_zero_nights,
    )
    s4 = "4) Small steps that often help:\n" + "\n".join(f"• {t}" for t in tips)
    s5 = f"5) {FEEDBACK_DISCLAIMER_EN}"

    return opening + "\n\n".join([s1, s2, s3, s4, s5])


def _openai_feedback(payload: dict) -> str | None:
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        logger.info("OpenAI: skipped (OPENAI_API_KEY is not set)")
        return None

    name = (payload.get("name") or "User").strip()
    history = payload.get("history") or []
    lines = []
    for i, row in enumerate(history[-7:], 1):
        lines.append(
            f"Day {i}: duration={row.get('durationText')}, ms={row.get('durationMs')}, "
            f"bed={row.get('bedAt')}, woke={row.get('wokeAt')}"
        )
    block = "\n".join(lines) if lines else "(no nights listed)"

    ctx = _sleep_feedback_context(payload)
    assessment = _assessment_block_for_prompt(ctx)

    user_prompt = (
        f"You are a warm, conversational sleep coach (not a doctor). User nickname: {name}. "
        f"Age (may be null): {payload.get('age')}. Country (may be ANONYMOUS): {payload.get('country')}. "
        f"Here are up to 7 recent nights (newest last):\n{block}\n\n"
        "--- Pre-computed assessment (follow exactly; never call zero sleep 'average' or 'adequate') ---\n"
        f"{assessment}\n"
        "--- End assessment ---\n\n"
        "Write like a human coach talking out loud — warm, plain English, short sentences. Not an app manual. "
        "Avoid tech-y words such as timestamps, logged, data, cannot see, rows, fields — say it the way you would to a friend. "
        "Use the user's name only once or twice in the whole message (greeting counts). "
        "Do not diagnose, prescribe, or name medical conditions. Say clearly you are not a doctor and cannot diagnose or prescribe treatment. "
        "Use exactly this five-part structure, each part plain text (no markdown # headings):\n\n"
        "1) Guideline: a few short sentences — age-based recommended sleep hours, friendly tone.\n"
        "2) Where things stand: keep this tight (max ~3 short sentences). Compare latest vs average vs guideline. "
        "If both_logged_zeros is true, include the exact sentence: "
        "\"Since both your latest night and recent average show 0.0 hours, this may be missing or unrecorded sleep data rather than actual sleep.\" "
        "After that, one light human line is enough (e.g. maybe the buttons never stuck) — no lecture. "
        "If the pre-computed assessment shows multiple_zero_nights=true, you MUST also include this exact sentence verbatim in part 2) "
        f"(same wording, copy exactly): \"{MULTIPLE_ZERO_NIGHTS_DATA_NOTICE_EN}\" "
        "(If both_logged_zeros is also true, still include the multiple_zero_nights sentence when the assessment requires it — it is short and fine next to the other line.) "
        "If same bucket for latest and average, merge; no repetition.\n"
        "3) Why it matters: 2–4 short sentences, speak straight to them (you / your night). Skip stiff phrases like 'In your case, NAME,'. "
        "If both_logged_zeros, stay calm — you need real nights filled in before you coach the pattern. "
        "If multiple_zero_nights is true, favor 'maybe those nights did not save' over scolding about chronic sleep loss; do not treat several zeros mainly as ordinary sleep shortage. "
        "If sleep is short otherwise, tie focus, mood, or energy lightly to what they shared.\n"
        "4) Small steps: exactly three lines starting with '• ' — practical habits only, no medical instructions.\n"
        "5) Close with this exact disclaimer on its own line (copy verbatim, including line breaks if needed):\n"
        f"{FEEDBACK_DISCLAIMER_EN}\n\n"
        "Aim for about 160 words total, max ~200. No markdown headings."
    )

    model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
    body = json.dumps(
        {
            "model": model,
            "messages": [{"role": "user", "content": user_prompt}],
            "temperature": 0.65,
        }
    ).encode("utf-8")

    req = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}",
        },
        method="POST",
    )
    try:
        logger.info(
            "OpenAI: requesting chat.completions model=%s user=%r history_rows=%s prompt_chars=%s",
            model,
            name,
            len(history[-7:]) if isinstance(history, list) else 0,
            len(user_prompt),
        )
        with urllib.request.urlopen(req, timeout=45) as resp:
            raw = resp.read().decode("utf-8")
            status = getattr(resp, "status", None) or resp.getcode()
        data = json.loads(raw)
        text = data["choices"][0]["message"]["content"].strip()
        preview = (text[:240] + "…") if len(text) > 240 else text
        logger.info(
            "OpenAI: OK http_status=%s response_chars=%s preview=%r",
            status,
            len(text),
            preview,
        )
        return text
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")[:800]
        logger.warning("OpenAI: HTTP error status=%s body=%s", e.code, err_body)
        return None
    except urllib.error.URLError as e:
        logger.warning("OpenAI: URL error reason=%r", e.reason)
        return None
    except (KeyError, IndexError, json.JSONDecodeError) as e:
        logger.warning("OpenAI: bad response shape or JSON: %s", e)
        return None
    except TimeoutError:
        logger.warning("OpenAI: request timed out after 45s")
        return None


@app.route("/api/ai-feedback", methods=["POST"])
def ai_feedback():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"ok": False, "error": "JSON body required"}), 400

    user = (payload.get("name") or "?").strip()
    hist = payload.get("history") if isinstance(payload.get("history"), list) else []
    logger.info(
        "POST /api/ai-feedback user=%r history_len=%s openai_key_set=%s",
        user,
        len(hist),
        bool(os.environ.get("OPENAI_API_KEY", "").strip()),
    )
    ctx_log = _sleep_feedback_context(payload)
    if ctx_log.get("has_data"):
        logger.info(
            "Sleep assessment: age=%r recommended=%.0f–%.0f h latest=%.3f h (%s) avg=%.3f h (%s) "
            "zero_nights_in_window=%s multiple_zero_nights=%s",
            ctx_log.get("age"),
            ctx_log["rec_lo"],
            ctx_log["rec_hi"],
            ctx_log["latest_h"],
            ctx_log["latest_cls"],
            ctx_log["avg_h"],
            ctx_log["avg_cls"],
            ctx_log.get("zero_night_count"),
            ctx_log.get("multiple_zero_nights"),
        )

    text = _openai_feedback(payload)
    source = "openai"
    if not text:
        text = _heuristic_feedback(payload)
        source = "heuristic"
        logger.info("AI feedback: using heuristic fallback for user=%r", user)

    logger.info(
        "POST /api/ai-feedback done user=%r source=%s response_chars=%s",
        user,
        source,
        len(text or ""),
    )
    return jsonify({"ok": True, "text": text, "source": source})


@app.before_request
def _log_auth_routes_once():
    if not getattr(app, "_account_db_logged", False):
        try:
            store = get_account_store()
            logger.info("Account database ready: %s (users=%s)", store.db_path, store.count_users())
        except Exception:
            logger.exception("Account database failed to initialize")
        app._account_db_logged = True


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="127.0.0.1", port=port, debug=True)
