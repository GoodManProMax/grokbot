#!/usr/bin/env python3
"""Regenerate calendars/us-market-events.ics.

- Rebuilds NYSE full holidays + common early closes for current/next year
- Keeps existing CPI/PPI/FOMC/earnings events from the current ICS when
  free refresh is unavailable (does not invent earnings dates)
- Optional FINNHUB_API_KEY: refresh earnings for a watchlist of tickers
- Optional free scrape of BLS CPI/PPI release schedule and Fed FOMC dates
"""
from __future__ import annotations

import os
import re
import sys
import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "calendars" / "us-market-events.ics"
USER_AGENT = "grokbot-us-market-updater/1.0 (+https://github.com/GoodManProMax/grokbot)"
TICKERS = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA", "NFLX",
    "AMD", "AVGO", "ORCL", "INTC", "QCOM", "MU", "TSM", "MRVL",
]


def http_get(url: str, timeout: int = 45) -> str | None:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        print(f"warn: GET {url}: {e}", file=sys.stderr)
        return None


def fold_ics_line(key: str, value: str, limit: int = 73) -> str:
    raw = f"{key}:{value}"
    if len(raw) <= limit:
        return raw
    parts = [raw[:limit]]
    rest = raw[limit:]
    while rest:
        parts.append(" " + rest[: limit - 1])
        rest = rest[limit - 1 :]
    return "\n".join(parts)


def escape_text(s: str) -> str:
    return (
        s.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\n", "\\n")
    )


def nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    """weekday: Mon=0 .. Sun=6; n: 1..5 or -1 for last."""
    if n > 0:
        d = date(year, month, 1)
        while d.weekday() != weekday:
            d += timedelta(days=1)
        d += timedelta(weeks=n - 1)
        return d
    # last
    if month == 12:
        d = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        d = date(year, month + 1, 1) - timedelta(days=1)
    while d.weekday() != weekday:
        d -= timedelta(days=1)
    return d


def easter_sunday(year: int) -> date:
    """Anonymous Gregorian algorithm."""
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    el = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * el) // 451
    month = (h + el - 7 * m + 114) // 31
    day = ((h + el - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def observed(d: date) -> date:
    if d.weekday() == 5:  # Sat -> Fri
        return d - timedelta(days=1)
    if d.weekday() == 6:  # Sun -> Mon
        return d + timedelta(days=1)
    return d


def nyse_holidays(year: int) -> list[tuple[date, str, str]]:
    """Return (date, uid_slug, summary) for full closes and early closes."""
    items: list[tuple[date, str, str, str]] = []
    # full closes
    items.append((observed(date(year, 1, 1)), f"nyse-newyear-{year}", "🏖 New Year’s Day 元旦（美股休市）", "full"))
    items.append((nth_weekday(year, 1, 0, 3), f"nyse-mlk-{year}", "🏖 MLK Day 马丁·路德·金日（美股休市）", "full"))
    items.append((nth_weekday(year, 2, 0, 3), f"nyse-presidents-{year}", "🏖 Presidents’ Day 总统日（美股休市）", "full"))
    good_friday = easter_sunday(year) - timedelta(days=2)
    items.append((good_friday, f"nyse-goodfriday-{year}", "🏖 Good Friday 耶稣受难日（美股休市）", "full"))
    items.append((nth_weekday(year, 5, 0, -1), f"nyse-memorial-{year}", "🏖 Memorial Day 阵亡将士纪念日（美股休市）", "full"))
    items.append((observed(date(year, 6, 19)), f"nyse-juneteenth-{year}", "🏖 Juneteenth（美股休市·观察日）", "full"))
    items.append((observed(date(year, 7, 4)), f"nyse-independence-{year}", "🏖 Independence Day（美股休市·观察日）", "full"))
    items.append((nth_weekday(year, 9, 0, 1), f"nyse-labor-{year}", "🏖 Labor Day 劳工节（美股休市）", "full"))
    thanks = nth_weekday(year, 11, 3, 4)
    items.append((thanks, f"nyse-thanksgiving-{year}", "🏖 Thanksgiving 感恩节（美股休市）", "full"))
    items.append((thanks + timedelta(days=1), f"nyse-thanksgiving-fri-{year}", "🏖 Thanksgiving Friday（美股早收）", "early"))
    items.append((observed(date(year, 12, 25)), f"nyse-christmas-{year}", "🏖 Christmas 圣诞节（美股休市·观察日）", "full"))
    # Christmas Eve early close when weekday
    eve = date(year, 12, 24)
    if eve.weekday() < 5:
        items.append((eve, f"nyse-christmas-eve-{year}", "🏖 Christmas Eve（美股早收）", "early"))

    out = []
    for d0, slug, summary, kind in items:
        out.append((d0, slug, summary, kind))
    return out


def parse_existing_events(text: str) -> dict[str, str]:
    """Map UID -> full VEVENT block (including BEGIN/END)."""
    events: dict[str, str] = {}
    for m in re.finditer(r"BEGIN:VEVENT\r?\n(.*?)END:VEVENT", text, re.S):
        block = "BEGIN:VEVENT\n" + m.group(1).rstrip("\n") + "\nEND:VEVENT"
        uid_m = re.search(r"^UID:(.*)$", block, re.M)
        if not uid_m:
            continue
        uid = uid_m.group(1).strip()
        # unfold UID if folded on next lines starting with space — rare
        events[uid] = block
    return events


def make_allday_event(uid: str, d0: date, summary: str, description: str, categories: str) -> str:
    now = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    d1 = d0 + timedelta(days=1)
    lines = [
        "BEGIN:VEVENT",
        f"UID:{uid}",
        f"DTSTAMP:{now}",
        fold_ics_line("SUMMARY", escape_text(summary)),
        fold_ics_line("DESCRIPTION", escape_text(description)),
        f"DTSTART;VALUE=DATE:{d0.strftime('%Y%m%d')}",
        f"DTEND;VALUE=DATE:{d1.strftime('%Y%m%d')}",
        f"CATEGORIES:{categories}",
        "STATUS:CONFIRMED",
        "BEGIN:VALARM",
        "ACTION:DISPLAY",
        fold_ics_line("DESCRIPTION", escape_text(summary)),
        "TRIGGER:-P1D",
        "END:VALARM",
        "END:VEVENT",
    ]
    return "\n".join(lines)


def make_timed_event(
    uid: str,
    start: datetime,
    end: datetime,
    summary: str,
    description: str,
    categories: str,
) -> str:
    now = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    fmt = "%Y%m%dT%H%M%S"
    lines = [
        "BEGIN:VEVENT",
        f"UID:{uid}",
        f"DTSTAMP:{now}",
        fold_ics_line("SUMMARY", escape_text(summary)),
        fold_ics_line("DESCRIPTION", escape_text(description)),
        f"DTSTART;TZID=America/New_York:{start.strftime(fmt)}",
        f"DTEND;TZID=America/New_York:{end.strftime(fmt)}",
        f"CATEGORIES:{categories}",
        "STATUS:CONFIRMED",
        "BEGIN:VALARM",
        "ACTION:DISPLAY",
        fold_ics_line("DESCRIPTION", escape_text(summary)),
        "TRIGGER:-P1D",
        "END:VALARM",
        "END:VEVENT",
    ]
    return "\n".join(lines)


def refresh_holidays(events: dict[str, str]) -> int:
    today = date.today()
    years = {today.year, today.year + 1}
    n = 0
    for y in sorted(years):
        for d0, slug, summary, kind in nyse_holidays(y):
            uid = f"{slug}@us-market-events"
            if kind == "early":
                desc = "NYSE 早收（通常 13:00 ET）。日期按常规日历推算，请以交易所公告为准。"
                cat = "HOLIDAY,EARLY_CLOSE"
            else:
                desc = "NYSE 全天休市。日期按常规观察日规则推算，请以交易所公告为准。"
                cat = "HOLIDAY,NYSE"
            events[uid] = make_allday_event(uid, d0, summary, desc, cat)
            n += 1
    return n


def try_refresh_bls_cpi_ppi(events: dict[str, str]) -> tuple[int, int]:
    """Best-effort parse of BLS release schedule pages. Soft-fail."""
    cpi_n = ppi_n = 0
    # CPI schedule often lists dates like "September 11, 2026"
    month_map = {
        "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
        "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
    }

    def parse_schedule(html: str, kind: str) -> list[tuple[date, str]]:
        found: list[tuple[date, str]] = []
        # Match "Month DD, YYYY" near release rows
        for m in re.finditer(
            r"\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2}),\s+(20\d{2})\b",
            html,
            re.I,
        ):
            mon = month_map[m.group(1).lower()]
            d0 = date(int(m.group(3)), mon, int(m.group(2)))
            # Heuristic: only future-ish and typical release weekdays
            if d0 < date.today() - timedelta(days=30):
                continue
            if d0 > date.today() + timedelta(days=400):
                continue
            found.append((d0, m.group(0)))
        # de-dupe preserve order
        seen = set()
        out = []
        for d0, label in found:
            if d0 in seen:
                continue
            seen.add(d0)
            out.append((d0, label))
        return out

    cpi_html = http_get("https://www.bls.gov/schedule/news_release/cpi.htm")
    if cpi_html:
        for d0, _ in parse_schedule(cpi_html, "CPI")[:18]:
            uid = f"cpi-{d0.strftime('%Y%m%d')}@us-market-events"
            # reference month approx prior month
            ref = d0.replace(day=1) - timedelta(days=1)
            summary = f"🇺🇸 CPI 消费者物价指数（{ref.strftime('%B %Y')}）"
            desc = (
                "BLS 官方发布时间 08:30 ET（北京约 20:30）。核心通胀关键数据。"
                "来源：https://www.bls.gov/schedule/news_release/cpi.htm"
            )
            start = datetime(d0.year, d0.month, d0.day, 8, 30)
            end = datetime(d0.year, d0.month, d0.day, 9, 30)
            events[uid] = make_timed_event(uid, start, end, summary, desc, "MACRO,CPI")
            cpi_n += 1

    ppi_html = http_get("https://www.bls.gov/schedule/news_release/ppi.htm")
    if ppi_html:
        for d0, _ in parse_schedule(ppi_html, "PPI")[:18]:
            uid = f"ppi-{d0.strftime('%Y%m%d')}@us-market-events"
            ref = d0.replace(day=1) - timedelta(days=1)
            summary = f"🇺🇸 PPI 生产者物价指数（{ref.strftime('%B %Y')}）"
            desc = (
                "BLS 官方发布时间 08:30 ET。来源：https://www.bls.gov/schedule/news_release/ppi.htm"
            )
            start = datetime(d0.year, d0.month, d0.day, 8, 30)
            end = datetime(d0.year, d0.month, d0.day, 9, 30)
            events[uid] = make_timed_event(uid, start, end, summary, desc, "MACRO,PPI")
            ppi_n += 1
    return cpi_n, ppi_n


def try_refresh_fomc(events: dict[str, str]) -> int:
    html = http_get("https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm")
    if not html:
        return 0
    n = 0
    # Look for patterns like "January 27-28, 2026" or "March 17-18"
    for m in re.finditer(
        r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2})\s*[-–]\s*(\d{1,2}),\s*(20\d{2})",
        html,
        re.I,
    ):
        month_map = {
            "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
            "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
        }
        y = int(m.group(4))
        mon = month_map[m.group(1).lower()]
        end_day = int(m.group(3))
        d0 = date(y, mon, end_day)  # decision day usually last day
        if d0 < date.today() - timedelta(days=14):
            continue
        if d0 > date.today() + timedelta(days=450):
            continue
        uid = f"fomc-{d0.strftime('%Y%m%d')}@us-market-events"
        summary = f"🏛️ FOMC 利率决议（{d0.strftime('%Y-%m-%d')}）"
        desc = (
            "美联储 FOMC 决议日，声明通常约 14:00 ET。来源：https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
        )
        start = datetime(d0.year, d0.month, d0.day, 14, 0)
        end = datetime(d0.year, d0.month, d0.day, 15, 0)
        events[uid] = make_timed_event(uid, start, end, summary, desc, "MACRO,FOMC")
        n += 1
    return n


def try_finnhub_earnings(events: dict[str, str]) -> int:
    key = os.environ.get("FINNHUB_API_KEY", "").strip()
    if not key:
        print("info: FINNHUB_API_KEY not set; keeping existing earnings events")
        return 0
    today = date.today()
    end = today + timedelta(days=180)
    n = 0
    for symbol in TICKERS:
        q = urllib.parse.urlencode(
            {
                "symbol": symbol,
                "from": today.isoformat(),
                "to": end.isoformat(),
                "token": key,
            }
        )
        raw = http_get(f"https://finnhub.io/api/v1/calendar/earnings?{q}")
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        for row in data.get("earningsCalendar") or []:
            ds = row.get("date")
            if not ds:
                continue
            try:
                d0 = date.fromisoformat(ds)
            except ValueError:
                continue
            hour = (row.get("hour") or "").lower()
            if hour == "bmo":
                when = "盘前"
                start = datetime(d0.year, d0.month, d0.day, 8, 0)
                end = datetime(d0.year, d0.month, d0.day, 9, 0)
            else:
                when = "盘后"
                start = datetime(d0.year, d0.month, d0.day, 16, 30)
                end = datetime(d0.year, d0.month, d0.day, 17, 30)
            uid = f"earnings-{symbol.lower()}-{d0.strftime('%Y%m%d')}@us-market-events"
            summary = f"📈 {symbol} 财报（{when}·Finnhub）"
            desc = f"Finnhub earnings calendar；请以公司 IR 公告为准。symbol={symbol} date={ds} hour={hour or 'n/a'}"
            events[uid] = make_timed_event(uid, start, end, summary, desc, f"EARNINGS,{symbol}")
            n += 1
    return n


def event_sort_key(block: str):
    m = re.search(r"DTSTART(?:;[^:]*)?:([0-9]{8})", block)
    if m:
        return m.group(1)
    return "99999999"


def render_calendar(events: dict[str, str]) -> str:
    header = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Grok Bot//US Market Events//ZH
CALSCALE:GREGORIAN
METHOD:PUBLISH
X-WR-CALNAME:美股大事件（PPI/CPI/FOMC/科技财报）
X-WR-CALDESC:FOMC、CPI、PPI、主要科技财报与美股休市日。宏观日期来自美联储/BLS；财报日期多为预估，请以公司公告为准。时区 America/New_York。
X-WR-TIMEZONE:America/New_York
REFRESH-INTERVAL;VALUE=DURATION:P1D
BEGIN:VTIMEZONE
TZID:America/New_York
BEGIN:DAYLIGHT
TZOFFSETFROM:-0500
TZOFFSETTO:-0400
TZNAME:EDT
DTSTART:19700308T020000
RRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=2SU
END:DAYLIGHT
BEGIN:STANDARD
TZOFFSETFROM:-0400
TZOFFSETTO:-0500
TZNAME:EST
DTSTART:19701101T020000
RRULE:FREQ=YEARLY;BYMONTH=11;BYDAY=1SU
END:STANDARD
END:VTIMEZONE
"""
    blocks = sorted(events.values(), key=event_sort_key)
    return header + "\n".join(blocks) + "\nEND:VCALENDAR\n"


def normalize(text: str) -> str:
    out = []
    for line in text.splitlines():
        if line.startswith("DTSTAMP:"):
            continue
        out.append(line.rstrip())
    return "\n".join(out)


def main() -> int:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    old = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
    events = parse_existing_events(old) if old else {}
    print(f"loaded existing events: {len(events)}")

    h = refresh_holidays(events)
    print(f"holidays upserted: {h}")
    cpi_n, ppi_n = try_refresh_bls_cpi_ppi(events)
    print(f"bls cpi upserted: {cpi_n}, ppi upserted: {ppi_n}")
    f = try_refresh_fomc(events)
    print(f"fomc upserted: {f}")
    e = try_finnhub_earnings(events)
    print(f"finnhub earnings upserted: {e}")

    new_text = render_calendar(events)
    changed = normalize(old) != normalize(new_text)
    OUT.write_text(new_text, encoding="utf-8")
    print(f"wrote {OUT} events={len(events)} changed={'yes' if changed else 'no'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
