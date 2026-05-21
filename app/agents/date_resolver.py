from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

# ── Egypt timezone (Africa/Cairo handles DST automatically) ───────────────────
EGYPT_TZ = ZoneInfo("Africa/Cairo")

# ── Arabic and English keyword lists ─────────────────────────────────────────
TODAY_KW     = ["النهارده", "اليوم", "today", "اليوم ده"]
YESTERDAY_KW = ["امس", "أمس", "yesterday", "البارح", "إمبارح"]
WEEK_KW      = ["الأسبوع", "الأسبوع ده", "هذا الأسبوع", "this week", "week", "أسبوع"]
MONTH_KW     = ["الشهر", "الشهر ده", "هذا الشهر", "this month", "month", "شهر"]
HALF_YEAR_KW = ["نصف سنة", "6 شهور", "ستة شهور", "half year", "6 months"]
YEARLY_KW    = ["سنة", "سنوي", "yearly", "annual", "year", "سنه"]


def detect_date_intent(user_message: str) -> str | None:
    """
    Detects the appropriate query_key from the user message.
    Supports both Arabic and English keywords.
    Returns None if no date/period keyword is found.
    """
    msg = user_message.lower()
    # Order matters: yesterday before today, yearly before half-year
    if any(k in msg for k in YESTERDAY_KW):
        return "total_yesterday"
    if any(k in msg for k in TODAY_KW):
        return "total_today"
    if any(k in msg for k in YEARLY_KW):
        return "report_yearly"
    if any(k in msg for k in HALF_YEAR_KW):
        return "report_half_year"
    if any(k in msg for k in MONTH_KW):
        return "total_this_month"
    if any(k in msg for k in WEEK_KW):
        return "total_this_week"
    return None


def resolve_date_params(query_key: str, current_date: datetime) -> dict:
    """
    Computes date params using Egypt local time (Africa/Cairo).
    This ensures "today" / "yesterday" match what the user sees on their phone,
    not UTC — which would cause off-by-one errors after midnight in Egypt.
    """
    # Convert UTC → Egypt local time first
    egypt_now = current_date.astimezone(EGYPT_TZ)
    today = egypt_now.date()

    mapping = {
        "total_today":      {"target_date": today},
        "total_yesterday":  {"target_date": today - timedelta(days=1)},
        "total_this_week":  {"since": today - timedelta(days=today.weekday())},
        "total_this_month": {"since": today.replace(day=1)},
        "report_half_year": {"since": today - timedelta(days=182)},
        "report_yearly":    {"since": today - timedelta(days=365)},
    }
    return mapping.get(query_key, {})


def has_date_keyword(user_message: str) -> bool:
    """Returns True if the message contains any recognizable date/period keyword."""
    msg = user_message.lower()
    all_kw = TODAY_KW + YESTERDAY_KW + WEEK_KW + MONTH_KW + HALF_YEAR_KW + YEARLY_KW
    return any(k in msg for k in all_kw)


def get_current_datetime_egypt() -> datetime:
    """Returns current datetime in Egypt timezone."""
    return datetime.now(EGYPT_TZ)


def get_current_datetime_utc() -> datetime:
    """Returns current UTC datetime (timezone-aware)."""
    return datetime.now(timezone.utc)
