#!/usr/bin/env python3
"""Regenerate calendars/us-market-events.ics.

- Rebuilds NYSE full holidays + common early closes for current/next year
- Keeps existing CPI/PPI/FOMC/earnings events from the current ICS when
  free refresh is unavailable (does not invent earnings dates)
- Optional FINNHUB_API_KEY: refresh earnings for a watchlist of tickers
- Refreshes official high-impact US macro dates: BLS CPI (and core CPI,
  same release), PPI, Employment Situation; BEA PCE/core PCE and GDP;
  Census advance retail sales; ISM PMI when the official calendar lists
  them; DOL weekly claims on the published Thursday 08:30 ET rule;
  Fed FOMC decisions (no duplicates) and minutes
"""
from __future__ import annotations

import os
import re
import sys
import json
import zlib
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


def nyse_holidays(year: int) -> list[tuple[date, str, str, str]]:
    """Return (date, uid_slug, summary, kind) for full closes and early closes."""
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
    christmas = observed(date(year, 12, 25))
    items.append((christmas, f"nyse-christmas-{year}", "🏖 Christmas 圣诞节（美股休市·观察日）", "full"))
    # Weekday Christmas Eve is an early close, unless that day is already the observed full close.
    eve = date(year, 12, 24)
    if eve.weekday() < 5 and eve != christmas:
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
    status: str = "CONFIRMED",
    alarm: bool = True,
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
        f"STATUS:{status}",
    ]
    if alarm:
        lines.extend(
            [
                "BEGIN:VALARM",
                "ACTION:DISPLAY",
                fold_ics_line("DESCRIPTION", escape_text(summary)),
                "TRIGGER:-P1D",
                "END:VALARM",
            ]
        )
    lines.append("END:VEVENT")
    return "\n".join(lines)


def vevent_start_date(block: str) -> date | None:
    match = re.search(r"^DTSTART(?:;[^:]*)?:(\d{8})", block, re.M)
    if not match:
        return None
    return datetime.strptime(match.group(1), "%Y%m%d").date()


def holiday_dates(events: dict[str, str], uid_prefix: str) -> set[date]:
    found: set[date] = set()
    for uid, block in events.items():
        if not uid.startswith(uid_prefix):
            continue
        start = vevent_start_date(block)
        if start is not None:
            found.add(start)
    return found


def drop_nyse_overlapping_hol(events: dict[str, str], covered: set[date]) -> None:
    """Drop later nyse- copies when an earlier hol- event already covers that day."""
    for uid in list(events):
        if not uid.startswith("nyse-"):
            continue
        start = vevent_start_date(events[uid])
        if start in covered:
            del events[uid]


def refresh_holidays(events: dict[str, str]) -> int:
    # hol- is the kept market-holiday set. Do not write a second nyse- event on the same day.
    covered = holiday_dates(events, "hol-")
    drop_nyse_overlapping_hol(events, covered)
    today = date.today()
    years = {today.year, today.year + 1}
    n = 0
    for y in sorted(years):
        for d0, slug, summary, kind in nyse_holidays(y):
            if d0 in covered:
                continue
            uid = f"{slug}@us-market-events"
            if kind == "early":
                desc = "NYSE 早收（通常 13:00 ET）。日期按常规日历推算，请以交易所公告为准。"
                cat = "HOLIDAY,EARLY_CLOSE"
            else:
                desc = "NYSE 全天休市。日期按常规观察日规则推算，请以交易所公告为准。"
                cat = "HOLIDAY,NYSE"
            block = make_allday_event(uid, d0, summary, desc, cat)
            if upsert_event(events, uid, block):
                n += 1
    return n


MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7, "aug": 8,
    "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}
FOMC_URL = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
BLS_CPI_URL = "https://www.bls.gov/schedule/news_release/cpi.htm"
BLS_PPI_URL = "https://www.bls.gov/schedule/news_release/ppi.htm"
BLS_EMP_URL = "https://www.bls.gov/schedule/news_release/empsit.htm"
BEA_URLS = (
    "https://www.bea.gov/news/schedule",
    "https://www.bea.gov/news/schedule/next-year",
)
CENSUS_RETAIL_URL = "https://www.census.gov/retail/release_schedule.html"
ISM_URL = "https://www.ismworld.org/supply-management-news-and-reports/reports/rob-report-calendar/"
DOL_CLAIMS_URL = "https://www.dol.gov/ui/data.pdf"
# Official pages list through late 2027; the Jan 2028 FOMC meeting is already
# on the Fed calendar, so minutes for that meeting can fall in early 2028.
MACRO_UNTIL = date(2028, 3, 31)
CLAIMS_UNTIL = date(2027, 12, 31)


def http_get_bytes(url: str, timeout: int = 45) -> bytes | None:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except Exception as e:
        print(f"warn: GET {url}: {e}", file=sys.stderr)
        return None


def parse_clock(hour: str, minute: str, ampm: str) -> tuple[int, int] | None:
    h = int(hour)
    m = int(minute)
    ap = ampm.upper()
    if ap == "PM" and h != 12:
        h += 12
    if ap == "AM" and h == 12:
        h = 0
    if not (0 <= h <= 23 and 0 <= m <= 59):
        return None
    return h, m


def in_macro_window(d0: date, until: date = MACRO_UNTIL) -> bool:
    return date.today() <= d0 <= until


def zh_ym(year: int, month: int) -> str:
    return f"{year}年{month}月"


def upsert_event(events: dict[str, str], uid: str, block: str) -> bool:
    old = events.get(uid)
    if old is not None and normalize(old) == normalize(block):
        return False
    events[uid] = block
    return True


def add_release(
    events: dict[str, str],
    uid: str,
    d0: date,
    hour: int,
    minute: int,
    summary: str,
    description: str,
    categories: str,
    hours: float = 1,
    status: str = "CONFIRMED",
    until: date = MACRO_UNTIL,
) -> bool:
    if not in_macro_window(d0, until):
        return False
    start = datetime(d0.year, d0.month, d0.day, hour, minute)
    end = start + timedelta(minutes=int(hours * 60))
    block = make_timed_event(uid, start, end, summary, description, categories, status=status)
    return upsert_event(events, uid, block)


def parse_bls_release_table(html: str) -> list[tuple[date, date, int, int]]:
    """Rows of (reference month, release date, hour, minute) from a BLS schedule table."""
    rows: list[tuple[date, date, int, int]] = []
    for m in re.finditer(
        r"<tr[^>]*>\s*<td>\s*([A-Za-z]+)\s+(20\d{2})\s*</td>\s*"
        r"<td>\s*([A-Za-z]+)\.?\s+(\d{1,2}),\s*(20\d{2})\s*</td>\s*"
        r"<td>\s*(\d{1,2}):(\d{2})\s*([AP]M)\s*</td>",
        html,
        re.I,
    ):
        ref_mon = MONTHS.get(m.group(1).lower())
        rel_mon = MONTHS.get(m.group(3).lower()[:3])
        clock = parse_clock(m.group(6), m.group(7), m.group(8))
        if not ref_mon or not rel_mon or not clock:
            continue
        ref = date(int(m.group(2)), ref_mon, 1)
        rel = date(int(m.group(5)), rel_mon, int(m.group(4)))
        rows.append((ref, rel, clock[0], clock[1]))
    return rows


def clock_note(hour: int, minute: int) -> str:
    return (
        f"官方发布时间 {hour:02d}:{minute:02d} America/New_York"
        "（夏令时北京时间 20:30，冬令时 21:30）。"
        if (hour, minute) == (8, 30)
        else f"官方发布时间 {hour:02d}:{minute:02d} America/New_York。"
    )


def try_refresh_bls_cpi_ppi(events: dict[str, str]) -> tuple[int, int]:
    """Upsert CPI, core CPI, and PPI from the BLS release tables. Soft-fail.

    Core CPI is not a separate BLS schedule row; it is published in the CPI news release.
    Existing headline CPI/PPI events are left in place when the release date is unchanged.
    """
    cpi_n = ppi_n = 0
    cpi_html = http_get(BLS_CPI_URL)
    if cpi_html:
        for ref, rel, hour, minute in parse_bls_release_table(cpi_html):
            if not in_macro_window(rel):
                continue
            if (hour, minute) != (8, 30):
                print(f"warn: unexpected CPI clock {hour:02d}:{minute:02d} on {rel}", file=sys.stderr)
            uid = f"cpi-{rel.strftime('%Y%m%d')}@us-market-events"
            if uid not in events:
                summary = f"🇺🇸 美国CPI（{zh_ym(ref.year, ref.month)}）"
                desc = clock_note(hour, minute) + f"来源：{BLS_CPI_URL}"
                if add_release(events, uid, rel, hour, minute, summary, desc, "MACRO,CPI"):
                    cpi_n += 1
            core_uid = f"cpi-core-{rel.strftime('%Y%m%d')}@us-market-events"
            summary = f"🇺🇸 美国核心CPI（{zh_ym(ref.year, ref.month)}）"
            desc = (
                clock_note(hour, minute)
                + "核心 CPI 与整体 CPI 同一份 BLS 新闻稿，不单独排期。"
                + f"来源：{BLS_CPI_URL}"
            )
            if add_release(events, core_uid, rel, hour, minute, summary, desc, "MACRO,CPI"):
                cpi_n += 1

    ppi_html = http_get(BLS_PPI_URL)
    if ppi_html:
        for ref, rel, hour, minute in parse_bls_release_table(ppi_html):
            if not in_macro_window(rel):
                continue
            uid = f"ppi-{rel.strftime('%Y%m%d')}@us-market-events"
            if uid in events:
                continue
            summary = f"🇺🇸 美国PPI（{zh_ym(ref.year, ref.month)}）"
            desc = clock_note(hour, minute) + f"来源：{BLS_PPI_URL}"
            if add_release(events, uid, rel, hour, minute, summary, desc, "MACRO,PPI"):
                ppi_n += 1
    return cpi_n, ppi_n


def try_refresh_bls_employment(events: dict[str, str]) -> int:
    html = http_get(BLS_EMP_URL)
    if not html:
        return 0
    n = 0
    for ref, rel, hour, minute in parse_bls_release_table(html):
        uid = f"empsit-{rel.strftime('%Y%m%d')}@us-market-events"
        summary = f"🇺🇸 美国非农与失业率（{zh_ym(ref.year, ref.month)}）"
        desc = (
            clock_note(hour, minute)
            + "BLS Employment Situation（非农就业、失业率）。"
            + f"来源：{BLS_EMP_URL}"
        )
        if add_release(events, uid, rel, hour, minute, summary, desc, "MACRO,EMPLOYMENT"):
            n += 1
    return n


def parse_bea_schedule(html: str) -> list[tuple[date, int, int, str]]:
    year_m = re.search(r'id="release-schedule-table".{0,1200}?Year\s+(20\d{2})', html, re.S)
    table_m = re.search(r'id="release-schedule-table".*?</table>', html, re.S)
    if not year_m or not table_m:
        return []
    year = int(year_m.group(1))
    out: list[tuple[date, int, int, str]] = []
    for m in re.finditer(
        r'<div class="release-date">\s*([A-Za-z]+)\s+(\d{1,2})\s*</div>\s*'
        r'<small class="text-muted">\s*(\d{1,2}):(\d{2})\s*([AP]M)\s*</small>'
        r'.*?<td class="release-title[^"]*"[^>]*>\s*([^<]+?)\s*</td>',
        table_m.group(0),
        re.S,
    ):
        mon = MONTHS.get(m.group(1).lower())
        clock = parse_clock(m.group(3), m.group(4), m.group(5))
        if not mon or not clock:
            continue
        try:
            d0 = date(year, mon, int(m.group(2)))
        except ValueError:
            continue
        title = re.sub(r"\s+", " ", m.group(6)).strip()
        out.append((d0, clock[0], clock[1], title))
    return out


def try_refresh_bea(events: dict[str, str]) -> tuple[int, int]:
    """PCE, core PCE, and GDP advance/second/third estimates from the BEA schedule."""
    rows: list[tuple[date, int, int, str]] = []
    seen: set[tuple[date, str]] = set()
    for url in BEA_URLS:
        html = http_get(url)
        if not html:
            continue
        for row in parse_bea_schedule(html):
            key = (row[0], row[3])
            if key in seen:
                continue
            seen.add(key)
            rows.append(row)
    pce_n = gdp_n = 0
    kind_zh = {"Advance": "初值", "Second": "修正值", "Third": "终值"}
    for d0, hour, minute, title in rows:
        if title.startswith("Personal Income and Outlays"):
            ref_m = re.search(r"Personal Income and Outlays,\s+([A-Za-z]+)\s+(20\d{2})", title)
            if not ref_m:
                continue
            mon = MONTHS.get(ref_m.group(1).lower())
            if not mon:
                continue
            label = zh_ym(int(ref_m.group(2)), mon)
            base = (
                clock_note(hour, minute)
                + "BEA《Personal Income and Outlays》。PCE 与核心 PCE 同一份新闻稿，核心 PCE 不单独排期。"
                + "来源：https://www.bea.gov/news/schedule"
            )
            slug = d0.strftime("%Y%m%d")
            if add_release(
                events,
                f"pce-{slug}@us-market-events",
                d0, hour, minute,
                f"🇺🇸 美国PCE（{label}）",
                base,
                "MACRO,PCE",
            ):
                pce_n += 1
            if add_release(
                events,
                f"pce-core-{slug}@us-market-events",
                d0, hour, minute,
                f"🇺🇸 美国核心PCE（{label}）",
                base,
                "MACRO,PCE",
            ):
                pce_n += 1
            continue
        gdp_m = re.search(
            r"^GDP \((Advance|Second|Third) Estimate\).*?([1-4])(?:st|nd|rd|th) Quarter(?: and Year)? (20\d{2})",
            title,
        )
        if not gdp_m:
            continue
        kind = kind_zh[gdp_m.group(1)]
        label = f"{gdp_m.group(3)}年Q{gdp_m.group(2)}{kind}"
        desc = (
            clock_note(hour, minute)
            + f"BEA GDP {kind}（{title}）。"
            + "来源：https://www.bea.gov/news/schedule"
        )
        uid = f"gdp-{d0.strftime('%Y%m%d')}-{gdp_m.group(1).lower()}@us-market-events"
        if add_release(events, uid, d0, hour, minute, f"🇺🇸 美国GDP（{label}）", desc, "MACRO,GDP"):
            gdp_n += 1
    return pce_n, gdp_n


def try_refresh_retail(events: dict[str, str]) -> int:
    html = http_get(CENSUS_RETAIL_URL)
    if not html or "Advance Monthly Retail Trade Report" not in html:
        return 0
    part = html.split("Advance Monthly Retail Trade Report", 1)[1]
    part = re.split(r"Monthly Retail Trade Report", part, maxsplit=1)[0]
    time_m = re.search(r"Release Date at\s+(\d{1,2}):(\d{2})\s*([ap]m)", part, re.I)
    if not time_m:
        return 0
    clock = parse_clock(time_m.group(1), time_m.group(2), time_m.group(3))
    if not clock:
        return 0
    n = 0
    for m in re.finditer(
        r"<td[^>]*>\s*([A-Za-z]+)\s+(20\d{2})\s*</td>\s*"
        r"<td[^>]*>\s*([A-Za-z]+)\s+(\d{1,2}),\s*(20\d{2})\s*</td>",
        part,
        re.I,
    ):
        ref_mon = MONTHS.get(m.group(1).lower())
        rel_mon = MONTHS.get(m.group(3).lower())
        if not ref_mon or not rel_mon:
            continue
        ref = date(int(m.group(2)), ref_mon, 1)
        rel = date(int(m.group(5)), rel_mon, int(m.group(4)))
        uid = f"retail-{rel.strftime('%Y%m%d')}@us-market-events"
        summary = f"🇺🇸 美国零售销售（{zh_ym(ref.year, ref.month)}）"
        desc = (
            clock_note(clock[0], clock[1])
            + "Census 提前零售与餐饮销售（Advance Monthly Retail Trade）。"
            + f"来源：{CENSUS_RETAIL_URL}"
        )
        if add_release(events, uid, rel, clock[0], clock[1], summary, desc, "MACRO,RETAIL"):
            n += 1
    return n


def parse_ism_calendar(html: str) -> list[tuple[date, str]]:
    if not re.search(r"10:00\s*a\.?\s*m\.?", html, re.I):
        return []
    out: list[tuple[date, str]] = []
    for year_m in re.finditer(r"(20\d{2})\s+ISM(?:(?!20\d{2}\s+ISM).)*", html, re.S):
        year = int(year_m.group(1))
        for row in re.finditer(
            r"<th[^>]*>\s*([A-Za-z]+)\s+20\d{2}\s*</th>\s*"
            r"<td>\s*(\d{1,2})(?:<[^>]+>)*</td>\s*<td>\s*(\d{1,2})",
            year_m.group(0),
            re.I,
        ):
            mon = MONTHS.get(row.group(1).lower())
            if not mon:
                continue
            for day_s, kind in ((row.group(2), "mfg"), (row.group(3), "svc")):
                try:
                    out.append((date(year, mon, int(day_s)), kind))
                except ValueError:
                    continue
    return out


def try_refresh_ism(events: dict[str, str]) -> int:
    html = http_get(ISM_URL)
    if not html:
        return 0
    n = 0
    titles = {"mfg": "美国ISM制造业PMI", "svc": "美国ISM服务业PMI"}
    for d0, kind in parse_ism_calendar(html):
        ref = d0.replace(day=1) - timedelta(days=1)
        uid = f"ism-{kind}-{d0.strftime('%Y%m%d')}@us-market-events"
        summary = f"🇺🇸 {titles[kind]}（{zh_ym(ref.year, ref.month)}）"
        desc = (
            "官方发布时间 10:00 America/New_York。"
            "ISM 日历表列出的发布日（制造业为当月第一个工作日，服务业为第三个工作日；假日顺延以表内日期为准）。"
            f"来源：{ISM_URL}"
        )
        if add_release(events, uid, d0, 10, 0, summary, desc, "MACRO,ISM"):
            n += 1
    return n


def pdf_literal_text(pdf: bytes) -> str:
    chunks: list[bytes] = []
    for m in re.finditer(rb"stream\r?\n(.*?)\r?\nendstream", pdf, re.S):
        try:
            chunks.append(zlib.decompress(m.group(1)))
        except Exception:
            continue
    if not chunks:
        return ""
    raw = b"\n".join(chunks).decode("latin1", errors="replace")
    parts: list[str] = []
    for lit in re.findall(r"\((?:\\.|[^\\)])*\)", raw):
        s = lit[1:-1].replace(r"\(", "(").replace(r"\)", ")").replace(r"\\", "\\")
        parts.append(s)
    return "".join(parts)


def us_federal_holidays(year: int) -> set[date]:
    days = {
        observed(date(year, 1, 1)),
        nth_weekday(year, 1, 0, 3),
        nth_weekday(year, 2, 0, 3),
        nth_weekday(year, 5, 0, -1),
        observed(date(year, 6, 19)),
        observed(date(year, 7, 4)),
        nth_weekday(year, 9, 0, 1),
        nth_weekday(year, 10, 0, 2),
        observed(date(year, 11, 11)),
        nth_weekday(year, 11, 3, 4),
        observed(date(year, 12, 25)),
    }
    return days


def try_refresh_claims(events: dict[str, str]) -> int:
    """Thursday 08:30 ET claims. Holiday Thursdays are omitted until DOL publishes the shifted date."""
    pdf = http_get_bytes(DOL_CLAIMS_URL)
    if not pdf:
        return 0
    text = pdf_literal_text(pdf)
    if not re.search(r"8:30\s*A\.M\.\s*\(Eastern\)\s+Thursday", text, re.I):
        print("warn: DOL claims PDF did not confirm the Thursday 08:30 ET rule", file=sys.stderr)
        return 0
    if "UNEMPLOYMENT INSURANCE WEEKLY CLAIMS" not in text:
        print("warn: DOL claims PDF missing series title", file=sys.stderr)
        return 0
    holidays: set[date] = set()
    d0 = date.today()
    while d0.weekday() != 3:
        d0 += timedelta(days=1)
    n = 0
    while d0 <= CLAIMS_UNTIL:
        holidays.update(us_federal_holidays(d0.year))
        if d0 not in holidays:
            week_ending = d0 - timedelta(days=5)
            uid = f"claims-{d0.strftime('%Y%m%d')}@us-market-events"
            summary = f"🇺🇸 美国初请失业金（截至{zh_ym(week_ending.year, week_ending.month)}{week_ending.day}日）"
            desc = (
                "日期按劳工部常规规则推算，不是逐周预先公布的日程："
                "最新 Unemployment Insurance Weekly Claims 新闻稿写明 "
                "embargo until 8:30 a.m. (Eastern) Thursday。"
                "周四恰逢联邦假日时劳工部会改期，但未提前公布具体日期，该周不写入。"
                f"来源：{DOL_CLAIMS_URL}"
            )
            if add_release(
                events, uid, d0, 8, 30, summary, desc, "MACRO,CLAIMS",
                until=CLAIMS_UNTIL,
            ):
                n += 1
        d0 += timedelta(days=7)
    return n


def parse_fomc_meetings(html: str) -> list[dict]:
    meetings: list[dict] = []
    panel_re = re.compile(
        r"<h4>\s*<a[^>]*>\s*(20\d{2})\s+FOMC Meetings\s*</a>\s*</h4>(.*?)"
        r'(?=<div class="panel panel-default"|<p>Note:)',
        re.S,
    )
    row_re = re.compile(
        r'fomc-meeting__month[^"]*"[^>]*>\s*<strong>([^<]+)</strong>'
        r'.*?fomc-meeting__date[^"]*"[^>]*>\s*([^<]+)</div>(.*?)'
        r'(?=fomc-meeting__month|$)',
        re.S,
    )
    for panel in panel_re.finditer(html):
        year = int(panel.group(1))
        for row in row_re.finditer(panel.group(2)):
            month_name = row.group(1).strip()
            date_txt = row.group(2).strip()
            rest = row.group(3)
            parts = [p.strip().lower() for p in re.split(r"\s*/\s*", month_name)]
            start_mon = MONTHS.get(parts[0])
            end_mon = MONTHS.get(parts[-1])
            dm = re.search(r"(\d{1,2})\s*[-–]\s*(\d{1,2})", date_txt)
            if not start_mon or not end_mon or not dm:
                continue
            start_day = int(dm.group(1))
            end_day = int(dm.group(2))
            end_year = year + 1 if end_mon < start_mon else year
            try:
                decision = date(end_year, end_mon, end_day)
            except ValueError:
                continue
            released = None
            rel = re.search(r"Released\s+([A-Za-z]+)\s+(\d{1,2}),\s*(20\d{2})", rest)
            if rel:
                rel_mon = MONTHS.get(rel.group(1).lower())
                if rel_mon:
                    try:
                        released = date(int(rel.group(3)), rel_mon, int(rel.group(2)))
                    except ValueError:
                        released = None
            meetings.append(
                {
                    "year": year,
                    "decision": decision,
                    "strategy": "Monetary Policy Strategy Meeting" in rest,
                    "minutes": released,
                    "sep": "*" in date_txt,
                }
            )
    note = re.search(
        r"two-day meeting is scheduled for\s+([A-Za-z]+)\s+(\d{1,2})\s*[-–]\s*(\d{1,2}),\s*(20\d{2})",
        html,
    )
    if note:
        mon = MONTHS.get(note.group(1).lower())
        if mon:
            try:
                decision = date(int(note.group(4)), mon, int(note.group(3)))
            except ValueError:
                decision = None
            if decision and all(m["decision"] != decision for m in meetings):
                meetings.append(
                    {
                        "year": decision.year,
                        "decision": decision,
                        "strategy": False,
                        "minutes": None,
                        "sep": False,
                    }
                )
    return meetings


def try_refresh_fomc(events: dict[str, str]) -> int:
    """Add missing FOMC decisions and minutes. Do not duplicate an existing decision."""
    html = http_get(FOMC_URL)
    if not html:
        return 0
    meetings = parse_fomc_meetings(html)
    if not meetings:
        print("warn: parsed no FOMC meetings", file=sys.stderr)
        return 0
    three_weeks = "released three weeks after the date of the policy decision" in html.lower()
    n = 0
    official: dict[int, set[date]] = {}
    counts: dict[int, int] = {}
    for m in meetings:
        official.setdefault(m["year"], set()).add(m["decision"])
        counts[m["year"]] = counts.get(m["year"], 0) + 1
        decision: date = m["decision"]
        uid = f"fomc-{decision.strftime('%Y%m%d')}@us-market-events"
        if m["strategy"]:
            summary = "🏦 FOMC 策略会议（非利率决议）"
            desc = (
                f"美联储 {decision.year} 年日程将 {decision.isoformat()} 标为 "
                "Monetary Policy Strategy Meeting，不发布常规利率决议，官网未给出声明钟点，因此记为全天。"
                f"来源：{FOMC_URL}"
            )
            block = make_allday_event(uid, decision, summary, desc, "MACRO,FOMC")
            if upsert_event(events, uid, block):
                n += 1
        elif uid not in events and in_macro_window(decision):
            summary = "🏦 FOMC 利率决议"
            desc = (
                "决议通常 14:00 ET，发布会约 14:30 ET。"
                "日期在前一次会议确认前，美联储仍标为暂定。"
                f"来源：{FOMC_URL}"
            )
            if add_release(
                events, uid, decision, 14, 0, summary, desc, "MACRO,FOMC", hours=1.5,
            ):
                n += 1
        if m["strategy"] or not three_weeks:
            continue
        minutes_uid = f"fomc-minutes-{decision.strftime('%Y%m%d')}@us-market-events"
        if m["minutes"] is not None:
            minutes_day = m["minutes"]
            status = "CONFIRMED"
            summary = f"🏛️ FOMC 会议纪要（{zh_ym(decision.year, decision.month)}决议）"
            desc = f"美联储官网列出的纪要发布日，14:00 ET。来源：{FOMC_URL}"
        else:
            minutes_day = decision + timedelta(days=21)
            status = "TENTATIVE"
            summary = f"🏛️ FOMC 会议纪要（{zh_ym(decision.year, decision.month)}决议·暂定）"
            desc = (
                "美联储官网写明：纪要在政策决定日后三周发布，通常 14:00 ET。"
                "此具体日期尚未在 FOMC 日历单独列出，遇假日可能改期，以 federalreserve.gov 为准。"
                f"来源：{FOMC_URL}"
            )
        if add_release(
            events,
            minutes_uid,
            minutes_day,
            14,
            0,
            summary,
            desc,
            "MACRO,FOMC_MINUTES",
            status=status,
        ):
            n += 1

    for uid, block in list(events.items()):
        m = re.fullmatch(r"fomc-(\d{8})@us-market-events", uid)
        if not m or "STATUS:CANCELLED" in block:
            continue
        try:
            d0 = datetime.strptime(m.group(1), "%Y%m%d").date()
        except ValueError:
            continue
        if d0 < date.today() or counts.get(d0.year, 0) < 6:
            continue
        if d0 in official.get(d0.year, set()):
            continue
        summary = "🏦 FOMC 利率决议（已取消·日程已修订）"
        desc = (
            f"美联储现行 {d0.year} 年 FOMC 日历已不含 {d0.isoformat()}。"
            "保留本条是为了让已订阅的日历撤下旧决议，而不是另建一场会议。"
            f"来源：{FOMC_URL}"
        )
        start_m = re.search(r"DTSTART;TZID=America/New_York:(\d{8}T\d{6})", block)
        if start_m:
            start = datetime.strptime(start_m.group(1), "%Y%m%dT%H%M%S")
            end = start + timedelta(minutes=90)
        else:
            start = datetime(d0.year, d0.month, d0.day, 14, 0)
            end = start + timedelta(minutes=90)
        cancelled = make_timed_event(
            uid, start, end, summary, desc, "MACRO,FOMC", status="CANCELLED", alarm=False,
        )
        if upsert_event(events, uid, cancelled):
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
    name = "美股大事件（CPI/PCE/非农/FOMC/科技财报）"
    desc = (
        "FOMC、CPI/核心CPI、PCE/核心PCE、非农、GDP、PPI、零售销售、初请失业金、ISM、"
        "主要科技财报与美股休市日。宏观日期来自美联储/BLS/BEA/Census/DOL/ISM 官方日程；"
        "未单独公布的日期标为暂定。财报日期多为预估，请以公司公告为准。时区 America/New_York。"
    )
    header = "\n".join(
        [
            "BEGIN:VCALENDAR",
            "VERSION:2.0",
            "PRODID:-//Grok Bot//US Market Events//ZH",
            "CALSCALE:GREGORIAN",
            "METHOD:PUBLISH",
            fold_ics_line("X-WR-CALNAME", escape_text(name)),
            fold_ics_line("X-WR-CALDESC", escape_text(desc)),
            "X-WR-TIMEZONE:America/New_York",
            "REFRESH-INTERVAL;VALUE=DURATION:P1D",
            "BEGIN:VTIMEZONE",
            "TZID:America/New_York",
            "BEGIN:DAYLIGHT",
            "TZOFFSETFROM:-0500",
            "TZOFFSETTO:-0400",
            "TZNAME:EDT",
            "DTSTART:19700308T020000",
            "RRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=2SU",
            "END:DAYLIGHT",
            "BEGIN:STANDARD",
            "TZOFFSETFROM:-0400",
            "TZOFFSETTO:-0500",
            "TZNAME:EST",
            "DTSTART:19701101T020000",
            "RRULE:FREQ=YEARLY;BYMONTH=11;BYDAY=1SU",
            "END:STANDARD",
            "END:VTIMEZONE",
            "",
        ]
    )
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

    fixed = 0
    for uid, block in list(events.items()):
        if "北京约 20:30" in block:
            events[uid] = block.replace("北京约 20:30", "夏令时北京时间 20:30，冬令时 21:30")
            fixed += 1
    if fixed:
        print(f"corrected winter/summer Beijing time notes: {fixed}")

    h = refresh_holidays(events)
    print(f"holidays upserted: {h}")
    cpi_n, ppi_n = try_refresh_bls_cpi_ppi(events)
    print(f"bls cpi/core upserted: {cpi_n}, ppi upserted: {ppi_n}")
    emp_n = try_refresh_bls_employment(events)
    print(f"bls employment upserted: {emp_n}")
    pce_n, gdp_n = try_refresh_bea(events)
    print(f"bea pce/core upserted: {pce_n}, gdp upserted: {gdp_n}")
    retail_n = try_refresh_retail(events)
    print(f"census retail upserted: {retail_n}")
    ism_n = try_refresh_ism(events)
    print(f"ism upserted: {ism_n}")
    claims_n = try_refresh_claims(events)
    print(f"jobless claims upserted: {claims_n}")
    f = try_refresh_fomc(events)
    print(f"fomc decisions/minutes upserted: {f}")
    e = try_finnhub_earnings(events)
    print(f"finnhub earnings upserted: {e}")

    new_text = render_calendar(events)
    changed = normalize(old) != normalize(new_text)
    OUT.write_text(new_text, encoding="utf-8")
    print(f"wrote {OUT} events={len(events)} changed={'yes' if changed else 'no'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
