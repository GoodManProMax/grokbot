#!/usr/bin/env python3
"""Regenerate calendars/china-festival-solarterm.ics.

Mainland traditional / commemorative festivals that are not the seven State
Council statutory categories (元旦、春节、清明节、劳动节、端午节、中秋节、国庆节),
plus the 24 solar terms as all-day dates.

Dates are computed with lunar-python (6tail, MIT):
https://github.com/6tail/lunar-python
Solar terms are 定气: the Asia/Shanghai civil date of the instant the Sun's
apparent ecliptic longitude is a multiple of 15°, from the 寿星天文历
(ShouXingUtil, Beijing time). 清明 is included only as the solar term 清明;
冬至 is included only as the solar term 冬至.

Workflow pin: lunar-python==1.4.8
"""
from __future__ import annotations

import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from lunar_python import Lunar, LunarYear, Solar

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "calendars" / "china-festival-solarterm.ics"

# Traditional lunar festivals (non-leap month). Statutory 春节/端午/中秋 are omitted.
# note is extra gloss; the lunar date itself comes from lunar.toString().
LUNAR_FESTIVALS: tuple[tuple[int, int, str, str], ...] = (
    (12, 8, "腊八节", ""),
    (12, 23, "北方小年", "北方祭灶"),
    (12, 24, "南方小年", "南方祭灶"),
    (1, 7, "人日", ""),
    (1, 15, "元宵节", ""),
    (1, 25, "填仓节", ""),
    (2, 2, "龙抬头", ""),
    (3, 3, "上巳节", ""),
    (6, 6, "天贶节", ""),
    (7, 7, "七夕", ""),
    (7, 15, "中元节", ""),
    (9, 9, "重阳节", ""),
    (10, 1, "寒衣节", ""),
    (10, 15, "下元节", ""),
)

# Fixed Gregorian commemorative days commonly observed in mainland China.
# 元旦 / 劳动节 / 国庆节 are statutory and intentionally absent.
SOLAR_FESTIVALS: tuple[tuple[int, int, str], ...] = (
    (1, 10, "中国人民警察节"),
    (3, 8, "妇女节"),
    (3, 12, "植树节"),
    (3, 15, "消费者权益日"),
    (5, 4, "青年节"),
    (5, 12, "护士节"),
    (6, 1, "儿童节"),
    (7, 1, "建党节"),
    (8, 1, "建军节"),
    (8, 19, "中国医师节"),
    (9, 10, "教师节"),
    (9, 18, "九一八事变纪念日"),
    (9, 30, "烈士纪念日"),
    (11, 8, "记者节"),
    (12, 13, "国家公祭日"),
)

# Calendar order within a Gregorian year, with the Sun's apparent ecliptic longitude.
SOLAR_TERMS: tuple[tuple[str, int], ...] = (
    ("小寒", 285),
    ("大寒", 300),
    ("立春", 315),
    ("雨水", 330),
    ("惊蛰", 345),
    ("春分", 0),
    ("清明", 15),
    ("谷雨", 30),
    ("立夏", 45),
    ("小满", 60),
    ("芒种", 75),
    ("夏至", 90),
    ("小暑", 105),
    ("大暑", 120),
    ("立秋", 135),
    ("处暑", 150),
    ("白露", 165),
    ("秋分", 180),
    ("寒露", 195),
    ("霜降", 210),
    ("立冬", 225),
    ("小雪", 240),
    ("大雪", 255),
    ("冬至", 270),
)
SOLAR_TERM_NAMES = {name for name, _ in SOLAR_TERMS}

# Once per generated Gregorian year. 腊八 is lunar 12/8, about three weeks
# before 春节; a late-January 春节 puts it in the previous December, so a
# year inside the window can have none (2023's 腊八 was 2022-12-30).
EACH_YEAR_FESTIVALS = (
    "北方小年",
    "南方小年",
    "元宵节",
    "龙抬头",
    "上巳节",
    "七夕",
    "中元节",
    "重阳节",
    "寒衣节",
    "下元节",
    "教师节",
)
SPAN_FESTIVALS = ("腊八节",)

# Statutory categories and holiday-cn style labels. Matched as whole summaries
# or as substrings for the arrangement wording only.
FORBIDDEN_SUMMARIES = frozenset(
    {"元旦", "元旦节", "春节", "清明节", "劳动节", "国际劳动节", "端午节", "中秋节", "国庆节"}
)
FORBIDDEN_SUBSTRINGS = ("补班", "假期第")


def years_to_cover() -> list[int]:
    y = date.today().year
    return list(range(y - 3, y + 2))


def fold_ics_line(key: str, value: str, limit: int = 73) -> str:
    """RFC 5545 line folding for a KEY:value line."""
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


def solar_date_of(lunar: Lunar) -> date:
    solar = lunar.getSolar()
    return date(solar.getYear(), solar.getMonth(), solar.getDay())


def add_event(
    events: list[dict],
    d0: date,
    summary: str,
    description: str,
    kind: str,
) -> None:
    if summary in FORBIDDEN_SUMMARIES or any(bad in summary for bad in FORBIDDEN_SUBSTRINGS):
        raise RuntimeError(f"refusing statutory/makeup summary: {summary}")
    events.append(
        {
            "date": d0,
            "summary": summary,
            "description": description,
            "uid": f"{d0.strftime('%Y%m%d')}_{kind}_{summary}@grokbot-china",
            "kind": kind,
        }
    )


def lunar_festivals_for_years(years: set[int]) -> list[dict]:
    events: list[dict] = []
    lunar_years = range(min(years) - 1, max(years) + 1)
    for lunar_year in lunar_years:
        for month, day, summary, note in LUNAR_FESTIVALS:
            lunar = Lunar.fromYmd(lunar_year, month, day)
            d0 = solar_date_of(lunar)
            if d0.year not in years:
                continue
            extra = f"（{note}）" if note else ""
            desc = f"{summary}，农历{lunar.toString()}{extra}。传统节日，非国务院法定节假日。"
            add_event(events, d0, summary, desc, "festival")

        month12 = LunarYear.fromYear(lunar_year).getMonth(12)
        if month12 is None:
            raise RuntimeError(f"missing lunar month 12 for {lunar_year}")
        chuxi = Lunar.fromYmd(lunar_year, 12, month12.getDayCount())
        d0 = solar_date_of(chuxi)
        if d0.year in years:
            festivals = chuxi.getFestivals()
            if "除夕" not in festivals:
                raise RuntimeError(f"expected 除夕 on lunar {lunar_year}-12-{month12.getDayCount()}")
            desc = f"除夕，农历{chuxi.toString()}。传统节日，非国务院法定节假日。"
            add_event(events, d0, "除夕", desc, "festival")
    return events


def solar_festivals_for_years(years: list[int]) -> list[dict]:
    events: list[dict] = []
    for year in years:
        for month, day, summary in SOLAR_FESTIVALS:
            d0 = date(year, month, day)
            desc = f"{summary}，公历{month}月{day}日。纪念节日，非国务院法定节假日。"
            add_event(events, d0, summary, desc, "festival")
    return events


def _beijing_clock(solar: Solar) -> str:
    return f"{solar.getHour():02d}:{solar.getMinute():02d}"


def solar_terms_for_year(year: int) -> list[dict]:
    """定气 dates whose Beijing-time instant falls in this Gregorian year."""
    found: dict[str, tuple[date, str]] = {}
    # A lunar year's 节气 table spans the previous 大雪 through the next 惊蛰.
    for lunar_year in (year - 1, year, year + 1):
        julian_days = LunarYear.fromYear(lunar_year).getJieQiJulianDays()
        for i, name in enumerate(Lunar.JIE_QI_IN_USE):
            if name not in SOLAR_TERM_NAMES:
                continue
            solar = Solar.fromJulianDay(julian_days[i])
            if solar.getYear() != year:
                continue
            d0 = date(solar.getYear(), solar.getMonth(), solar.getDay())
            clock = _beijing_clock(solar)
            prev = found.get(name)
            if prev is not None and prev[0] != d0:
                raise RuntimeError(f"conflicting {name} in {year}: {prev[0]} vs {d0}")
            found[name] = (d0, clock)

    missing = [name for name, _ in SOLAR_TERMS if name not in found]
    if missing:
        raise RuntimeError(f"missing solar terms in {year}: {missing}")

    events: list[dict] = []
    for name, longitude in SOLAR_TERMS:
        d0, clock = found[name]
        desc = (
            f"{name}，二十四节气（定气，太阳视黄经{longitude}°）。"
            f"交节时刻 {d0.isoformat()} {clock}（北京时间）。"
            "寿星天文历，经 lunar-python 计算。"
        )
        add_event(events, d0, name, desc, "solarterm")
    return events


def hanshi_for_years(term_events: list[dict], years: set[int]) -> list[dict]:
    """寒食 is the civil day before 清明, matching lunar-python."""
    events: list[dict] = []
    for ev in term_events:
        if ev["summary"] != "清明" or ev["date"].year not in years:
            continue
        d0 = ev["date"] - timedelta(days=1)
        desc = "寒食节，清明前一日。传统节日，非国务院法定节假日。"
        add_event(events, d0, "寒食节", desc, "festival")
    return events


def build_events(years: list[int]) -> list[dict]:
    year_set = set(years)
    terms: list[dict] = []
    for year in years:
        terms.extend(solar_terms_for_year(year))
    events = []
    events.extend(lunar_festivals_for_years(year_set))
    events.extend(solar_festivals_for_years(years))
    events.extend(hanshi_for_years(terms, year_set))
    events.extend(terms)
    events.sort(key=lambda e: (e["date"], e["kind"], e["summary"]))
    _assert_coverage(events, years)
    return events


def _assert_coverage(events: list[dict], years: list[int]) -> None:
    by_year: dict[int, set[str]] = {y: set() for y in years}
    span_names: set[str] = set()
    uids: list[str] = []
    for ev in events:
        by_year.setdefault(ev["date"].year, set()).add(ev["summary"])
        span_names.add(ev["summary"])
        uids.append(ev["uid"])
        if ev["summary"] in FORBIDDEN_SUMMARIES or any(
            bad in ev["summary"] for bad in FORBIDDEN_SUBSTRINGS
        ):
            raise RuntimeError(f"forbidden event slipped through: {ev['summary']}")
    if len(uids) != len(set(uids)):
        raise RuntimeError("duplicate event UID")
    for year in years:
        names = by_year.get(year, set())
        missing_f = [name for name in EACH_YEAR_FESTIVALS if name not in names]
        missing_t = [name for name, _ in SOLAR_TERMS if name not in names]
        if missing_f or missing_t:
            raise RuntimeError(f"coverage {year} missing festivals={missing_f} terms={missing_t}")
        term_count = sum(1 for ev in events if ev["date"].year == year and ev["kind"] == "solarterm")
        if term_count != 24:
            raise RuntimeError(f"{year} solar term count {term_count} != 24")
    missing_span = [name for name in SPAN_FESTIVALS if name not in span_names]
    if missing_span:
        raise RuntimeError(f"missing from year span: {missing_span}")
    current = date.today().year
    current_names = by_year.get(current, set())
    if "重阳节" not in current_names or any(name not in current_names for name, _ in SOLAR_TERMS):
        raise RuntimeError(f"current year {current} missing 重阳节 or a solar term")


def render_ics(events: list[dict], year_span: str) -> str:
    now = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    today = date.today().isoformat()
    lines = [
        "BEGIN:VCALENDAR",
        "PRODID:-//Grok Bot//China Festivals And Solar Terms All-Day//CN",
        "VERSION:2.0",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:中国非法定节日与节气(全天)",
        "X-WR-TIMEZONE:Asia/Shanghai",
        fold_ics_line(
            "X-WR-CALDESC",
            "传统节日与纪念节日（不含国务院法定节假日及补班），另含二十四节气全天。"
            "农历换算与定气来自 lunar-python（6tail，MIT，寿星天文历，北京时间）；"
            f"覆盖约{year_span}。生成 {today}",
        ),
        "BEGIN:VTIMEZONE",
        "TZID:Asia/Shanghai",
        "X-LIC-LOCATION:Asia/Shanghai",
        "BEGIN:STANDARD",
        "TZOFFSETFROM:+0800",
        "TZOFFSETTO:+0800",
        "TZNAME:CST",
        "DTSTART:19700101T000000",
        "END:STANDARD",
        "END:VTIMEZONE",
    ]
    for ev in events:
        d0 = ev["date"]
        d1 = d0 + timedelta(days=1)
        stamp = d0.strftime("%Y%m%dT000000Z")
        lines.extend(
            [
                "BEGIN:VEVENT",
                f"DTSTART;VALUE=DATE:{d0.strftime('%Y%m%d')}",
                f"DTEND;VALUE=DATE:{d1.strftime('%Y%m%d')}",
                f"DTSTAMP:{stamp}",
                fold_ics_line("UID", ev["uid"]),
                f"CREATED:{now}",
                fold_ics_line("DESCRIPTION", escape_text(ev["description"])),
                f"LAST-MODIFIED:{now}",
                "SEQUENCE:0",
                "STATUS:CONFIRMED",
                fold_ics_line("SUMMARY", escape_text(ev["summary"])),
                "TRANSP:TRANSPARENT",
                "END:VEVENT",
            ]
        )
    lines.append("END:VCALENDAR")
    return "\n".join(lines) + "\n"


def normalize(text: str) -> str:
    """Ignore volatile timestamps when comparing change."""
    out = []
    for line in text.splitlines():
        if line.startswith("CREATED:") or line.startswith("LAST-MODIFIED:"):
            continue
        if line.startswith("X-WR-CALDESC:"):
            continue
        out.append(line.rstrip())
    return "\n".join(out)


def main() -> int:
    years = years_to_cover()
    events = build_events(years)
    if not events:
        print("error: no events generated", file=sys.stderr)
        return 1
    year_span = f"{min(years)}-{max(years)}"
    new_text = render_ics(events, year_span)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    old_text = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
    changed = normalize(old_text) != normalize(new_text)
    OUT.write_text(new_text, encoding="utf-8")
    festival_names = sorted({e["summary"] for e in events if e["kind"] == "festival"})
    print(
        f"wrote {OUT} events={len(events)} years={years} "
        f"festivals={len(festival_names)} solar_terms={len(SOLAR_TERMS) * len(years)} "
        f"changed={'yes' if changed else 'no'}"
    )
    print("festival names: " + "、".join(festival_names))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
