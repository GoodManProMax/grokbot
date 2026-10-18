#!/usr/bin/env python3
"""Regenerate calendars/china-holiday-allday.ics from NateScarlet/holiday-cn JSON.

Public source: https://github.com/NateScarlet/holiday-cn
Writes all-day VEVENTs in a style close to the existing ShuYZ-derived ICS
(per-day events with 「假期/补班 第N天/共M天」 summaries).
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "calendars" / "china-holiday-allday.ics"
BASE = "https://raw.githubusercontent.com/NateScarlet/holiday-cn/master"
USER_AGENT = "grokbot-china-holiday-updater/1.0 (+https://github.com/GoodManProMax/grokbot)"


def fetch_json(url: str) -> dict | None:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
        print(f"warn: fetch failed {url}: {e}", file=sys.stderr)
        return None


def years_to_fetch() -> list[int]:
    y = date.today().year
    # Keep recent history (calendar subscribers often keep past events) + next year
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


def parse_ymd(s: str) -> date:
    return date.fromisoformat(s)


def build_events(years_data: list[dict]) -> list[dict]:
    """Return list of event dicts: date, summary, description, uid, is_off."""
    # Collect days keyed by (year_name_group): name + isOffDay across a year
    # For numbering 第N/共M, group within each year by (name, isOffDay).
    events: list[dict] = []
    for data in years_data:
        days = data.get("days") or []
        if not days:
            continue
        papers = data.get("papers") or []
        paper_note = ""
        if papers:
            paper_note = "放假通知: " + " ".join(papers)

        groups: dict[tuple[str, bool], list[dict]] = defaultdict(list)
        for d in days:
            name = d.get("name") or "节假日"
            is_off = bool(d.get("isOffDay"))
            groups[(name, is_off)].append(d)

        for (name, is_off), group in groups.items():
            group_sorted = sorted(group, key=lambda x: x["date"])
            total = len(group_sorted)
            kind = "假期" if is_off else "补班"
            for i, d in enumerate(group_sorted, start=1):
                d0 = parse_ymd(d["date"])
                summary = f"{name} {kind} 第{i}天/共{total}天"
                desc_parts = [f"{name}{'放假' if is_off else '补班'}（国务院安排，来源 holiday-cn）"]
                if paper_note:
                    desc_parts.append(paper_note)
                uid_kind = "holiday" if is_off else "work"
                uid = f"{d0.strftime('%Y%m%d')}_{uid_kind}_{name}@grokbot-china"
                events.append(
                    {
                        "date": d0,
                        "summary": summary,
                        "description": "\n\n".join(desc_parts),
                        "uid": uid,
                        "is_off": is_off,
                    }
                )
    events.sort(key=lambda e: (e["date"], 0 if e["is_off"] else 1, e["summary"]))
    return events


def render_ics(events: list[dict], year_span: str) -> str:
    now = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    today = date.today().isoformat()
    lines = [
        "BEGIN:VCALENDAR",
        "PRODID:-//Grok Bot//China Holidays All-Day//CN",
        "VERSION:2.0",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:中国放假与补班(全天)",
        "X-WR-TIMEZONE:Asia/Shanghai",
        fold_ics_line(
            "X-WR-CALDESC",
            f"基于 NateScarlet/holiday-cn；补班为全天；覆盖约{year_span}。生成 {today}",
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
                "TRANSP:TRANSPARENT" if ev["is_off"] else "TRANSP:OPAQUE",
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
    years_data: list[dict] = []
    fetched_years: list[int] = []
    for y in years_to_fetch():
        data = fetch_json(f"{BASE}/{y}.json")
        if not data:
            continue
        if not (data.get("days") or []):
            print(f"skip empty year {y}")
            continue
        years_data.append(data)
        fetched_years.append(y)

    if not years_data:
        print("error: no holiday data fetched", file=sys.stderr)
        return 1

    events = build_events(years_data)
    year_span = f"{min(fetched_years)}-{max(fetched_years)}"
    new_text = render_ics(events, year_span)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    old_text = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
    changed = normalize(old_text) != normalize(new_text)
    OUT.write_text(new_text, encoding="utf-8")
    print(
        f"wrote {OUT} events={len(events)} years={fetched_years} changed={'yes' if changed else 'no'}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
