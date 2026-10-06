"""
One business day with different hours (e.g. Saturday 9:00 AM – 3:00 PM while
the rest of the week runs to 4:00 PM).

Configured on WhatsApp Inbox Settings as `short_day` (3-letter day),
`short_day_start` (optional — falls back to the normal start) and
`short_day_end`. `whatsapp_utils.is_business_hours` swaps the window on that
day and `business_hours_label` renders it as its own part, e.g.
"Sat 9:00 AM – 3:00 PM, Sun–Thu 9:00 AM – 4:00 PM".

Import-cheap: no frappe here; whatsapp_utils binds the few primitives this
module needs via `bind()` when it is imported (no import cycle).
"""


import types

utils = None  # bound by whatsapp_utils at import (see its tail)


def bind(**helpers):
    global utils
    utils = types.SimpleNamespace(**helpers)


def _wu():
    return utils


def short_day_window(settings):
    """(day3, start, end) when a short day with a real window is configured,
    else None. `start` falls back to the normal business start."""
    wu = _wu()
    day = str(wu._g(settings, "short_day", "") or "").strip().lower()[:3]
    if day not in wu._DAY_TOKENS:
        return None
    start = wu._g(settings, "short_day_start") or wu._g(settings, "business_hours_start")
    end = wu._g(settings, "short_day_end")
    if wu.business_window_unset(start, end):
        return None
    return day, start, end


def window_for(now, settings, raw_start, raw_end):
    """The (start, end) pair that applies to `now`'s weekday."""
    short = short_day_window(settings)
    if short and now.strftime("%a").lower()[:3] == short[0]:
        return short[1], short[2]
    return raw_start, raw_end


def label(settings, lang, days):
    """Full business-hours label. Without a short day: the classic
    "Sat–Thu, 9:00 AM – 4:00 PM"; with one that is a business day: the short
    day first with its own hours, then the rest of the week with theirs."""
    wu = _wu()
    comma = "، " if lang == "ar" else ", "
    names = dict(zip(wu._WEEK_ORDER, wu._DAY_NAMES[lang]))
    start, end = wu._g(settings, "business_hours_start"), wu._g(settings, "business_hours_end")
    hours = "" if wu.business_window_unset(start, end) else (
        f"{wu.clock_12h(start, lang)} – {wu.clock_12h(end, lang)}")
    short = short_day_window(settings)
    if not (short and short[0] in days):
        parts = [p for p in (day_runs(days, names, comma), hours) if p]
        return comma.join(parts)
    rest = day_runs(days - {short[0]}, names, comma)
    short_hours = f"{wu.clock_12h(short[1], lang)} – {wu.clock_12h(short[2], lang)}"
    parts = [f"{names[short[0]]} {short_hours}"]
    if rest:
        parts.append(f"{rest} {hours}".strip())
    return comma.join(parts)


def day_runs(days, names, comma=", "):
    """"Sat–Mon, Wed–Thu": runs of consecutive business days (week from
    Saturday) collapse to First–Last; singles stay as they are."""
    wu = _wu()
    runs, run = [], []
    for day in wu._WEEK_ORDER + ("",):  # the "" sentinel flushes the last run
        if day in days:
            run.append(day)
        elif run:
            runs.append("–".join(dict.fromkeys((names[run[0]], names[run[-1]]))))
            run = []
    return comma.join(runs)
