#!/usr/bin/env python3
"""
Israel Home Front Command – Live Alert Monitor
A ctop-style full-screen terminal dashboard that polls the OREF alerts API
and displays rocket/missile/threat alerts in real time.

Usage:
    python3 alert_watch.py
    python3 alert_watch.py --interval 30   # poll every 30 seconds (default: 30)

Press  q  or  Ctrl-C  to quit.
"""

import argparse
import json
import sys
import time
from collections import deque
from datetime import datetime
from pathlib import Path

import requests
from rich.align import Align
from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich import box

# ---------------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------------
ALERTS_URL = "https://www.oref.org.il/WarningMessages/alert/alerts.json"
HISTORY_URL = "https://api.tzevaadom.co.il/alerts-history/"

HEADERS = {
    "Referer": "https://www.oref.org.il/",
    "X-Requested-With": "XMLHttpRequest",
    "Accept": "application/json",
}

# Max number of session-history entries kept in memory
MAX_HISTORY = 50

# Default shelter time (seconds) when a city is not found in cities.json
DEFAULT_EVAC_TIME = 90

# ---------------------------------------------------------------------------
# Category system (tzevaadom threat codes 0-7)
# ---------------------------------------------------------------------------
# Labels keyed by tzevaadom threat code
CATEGORY_LABELS: dict[int, str] = {
    0: "🚀 Rockets",
    1: "☣️  Hazardous Materials",
    2: "🔫 Terrorist Infiltration",
    3: "🌍 Earthquake",
    4: "🌊 Tsunami",
    5: "✈️  Unmanned Aircraft",
    6: "☢️  Non-Conventional Missile",
    7: "☢️  Radiological Event",
}

# Hex colours (from tzevaadom source)
CATEGORY_COLORS: dict[int, str] = {
    0: "#FF0000",  # Rockets
    1: "#9335ee",  # Hazardous Materials
    2: "#FFD500",  # Terrorist Infiltration
    3: "#00FF55",  # Earthquake
    4: "#0080FF",  # Tsunami
    5: "#FF8000",  # Unmanned Aircraft
    6: "#ee35a8",  # Non-Conventional Missile
    7: "#ee35a8",  # Radiological Event
}

# Map OREF alert `cat` value → tzevaadom threat code
OREF_CAT_TO_THREAT: dict[str, int] = {
    "1":  0,  # Rockets/Missiles
    "2":  5,  # Hostile Aircraft → Unmanned Aircraft
    "3":  3,  # Earthquake
    "4":  1,  # Hazardous Materials
    "5":  4,  # Tsunami
    "6":  5,  # Hostile Aircraft Intrusion → Unmanned Aircraft
    "7":  6,  # Unconventional Missile
    "13": 7,  # Radiological Event
}

# Home Front Command shelter instructions per threat code (Hebrew)
CATEGORY_INSTRUCTIONS: dict[int, str] = {
    0: "היכנסו מיד למרחב המוגן וישהו בו {time} שניות",
    1: "הישארו בבית, סגרו חלונות ודלתות והכניסו בעלי חיים",
    2: "היכנסו מיד למרחב המוגן וישהו בו {time} שניות",
    3: "עמדו ליד קיר פנימי תחתון — הרחיקו מחלונות ומחפצים כבדים",
    4: "התרחקו מיידית מהחוף לשטח גבוה",
    5: "היכנסו מיד למרחב המוגן",
    6: "היכנסו מיד למרחב המוגן וישהו בו 10 דקות",
    7: "הישארו בבית, סגרו חלונות ודלתות",
}


# ---------------------------------------------------------------------------
# Data fetching
# ---------------------------------------------------------------------------

def fetch_current_alert(timeout: int = 5) -> dict | None:
    """Return the current active alert dict, or None if no active alert."""
    try:
        resp = requests.get(ALERTS_URL, headers=HEADERS, timeout=timeout)
        resp.raise_for_status()
        raw = resp.text.strip()
        if not raw or raw in ("null", "[]", "{}"):
            return None
        data = resp.json()
        # data must have a non-empty 'data' list to be considered active
        if isinstance(data, dict) and data.get("data"):
            return data
        return None
    except requests.RequestException:
        return None


def fetch_history(timeout: int = 5) -> list[dict]:
    """Fetch alert history from the tzevaadom API.

    Returns a list of group dicts.  Each group has an ``alerts`` list whose
    entries contain: ``time`` (Unix seconds), ``cities`` (list of Hebrew
    locality names), ``threat`` (int, tzevaadom threat code 0-7), ``isDrill``.
    """
    try:
        resp = requests.get(HISTORY_URL, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        return data if isinstance(data, list) else []
    except (requests.RequestException, ValueError):
        return []


def fetch_cities() -> dict[str, dict]:
    """Load the bundled tzevaadom locality list from *cities.json*.

    Returns a dict keyed by Hebrew city name.  Each value contains at least
    ``evac_time`` (shelter seconds), ``area`` (int area-ID), ``en`` (English
    name).
    """
    cities_file = Path(__file__).parent / "cities.json"
    try:
        with open(cities_file, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def load_areas() -> dict[int, str]:
    """Load area-ID → Hebrew name mapping from *areas.json*.

    Hebrew names are used throughout the TUI to match the Hebrew city names
    returned by the OREF and tzevaadom APIs.
    """
    areas_file = Path(__file__).parent / "areas.json"
    try:
        with open(areas_file, encoding="utf-8") as fh:
            raw = json.load(fh)
        return {int(k): v["he"] for k, v in raw.items()}
    except (OSError, ValueError):
        return {}


def get_matching_cities(alert: dict | None, watch_cities: list[str]) -> list[str]:
    """Return the subset of *watch_cities* that appear in the alert's area list."""
    if not alert or not watch_cities:
        return []
    alert_areas = {a.strip() for a in alert.get("data", [])}
    return [c for c in watch_cities if c.strip() in alert_areas]


# ---------------------------------------------------------------------------
# UI helpers
# ---------------------------------------------------------------------------

def make_header(poll_count: int, now: datetime, interval: int) -> Panel:
    left = Text.assemble(
        Text("🇮🇱  Israel Home Front Command — Live Alert Monitor\n", style="bold white"),
        Text(
            f"  Polling every {interval}s  │  Polls: {poll_count}"
            f"  │  Last fetch: {now.strftime('%Y-%m-%d %H:%M:%S')}"
            f"  │  [dim]q / Ctrl-C to quit[/dim]",
            style="dim cyan",
        ),
    )
    clock = Text.assemble(
        Text(now.strftime("%H:%M:%S") + "\n", style="bold bright_white"),
        Text(now.strftime("%Y-%m-%d"), style="dim cyan"),
    )
    grid = Table.grid(expand=True)
    grid.add_column(ratio=4)
    grid.add_column(justify="right", ratio=1)
    grid.add_row(left, clock)
    return Panel(grid, style="bold blue", box=box.HEAVY)


def make_alert_panel(alert: dict | None) -> Panel:
    if alert is None:
        content = Text("✅  No active alerts", style="bold green", justify="center")
        return Panel(
            content,
            title="[bold green]Current Alert Status[/bold green]",
            border_style="green",
            box=box.DOUBLE,
            padding=(1, 4),
        )

    cat = str(alert.get("cat", ""))
    threat = OREF_CAT_TO_THREAT.get(cat, 0)
    color = CATEGORY_COLORS.get(threat, "#FF0000")
    cat_label = CATEGORY_LABELS.get(threat, f"Category {cat}")
    title_he = alert.get("title", "")
    desc_he = alert.get("desc", "")
    areas = alert.get("data", [])

    area_text = Text()
    for i, area in enumerate(areas):
        if i:
            area_text.append("  •  ", style=color)
        area_text.append(area, style=f"bold {color}")

    content = Text()
    content.append(f"  {cat_label}\n", style=f"bold {color}")
    if title_he:
        content.append(f"  {title_he}\n", style="bright_yellow")
    if desc_he:
        content.append(f"  {desc_he}\n", style="yellow")
    content.append("\n  Affected areas:\n  ", style="white")
    content.append_text(area_text)

    return Panel(
        content,
        title=f"[bold blink]⚠  ACTIVE ALERT — {len(areas)} area(s)[/bold blink]",
        border_style=color,
        box=box.DOUBLE_EDGE,
        padding=(1, 2),
    )


def make_session_history_table(session_history: deque) -> Panel:
    table = Table(
        box=box.SIMPLE_HEAVY,
        show_header=True,
        header_style="bold cyan",
        expand=True,
        show_lines=False,
    )
    table.add_column("Time", style="dim", width=19, no_wrap=True)
    table.add_column("Category", min_width=24)
    table.add_column("Cities", style="yellow")
    table.add_column("Description", style="dim yellow")

    if not session_history:
        table.add_row("—", "No alerts recorded yet", "—", "—")
    else:
        for entry in reversed(session_history):
            color = entry.get("color", "#FF0000")
            table.add_row(
                entry["time"],
                f"[bold {color}]{entry['category']}[/]",
                entry["areas"],
                entry.get("desc", ""),
            )

    return Panel(
        table,
        title="[bold cyan]Session Alert History[/bold cyan]",
        border_style="cyan",
        box=box.ROUNDED,
    )


def make_server_history_table(history_groups: list[dict]) -> Panel:
    table = Table(
        box=box.SIMPLE_HEAVY,
        show_header=True,
        header_style="bold magenta",
        expand=True,
        show_lines=False,
    )
    table.add_column("Time", style="dim", width=19, no_wrap=True)
    table.add_column("Threat", min_width=26)
    table.add_column("Cities", style="yellow")

    # Flatten groups → individual alerts, skip drills, newest first
    flat: list[dict] = []
    for group in history_groups:
        for alert in group.get("alerts", []):
            if not alert.get("isDrill"):
                flat.append(alert)
    flat.sort(key=lambda a: a.get("time", 0), reverse=True)

    if not flat:
        table.add_row("—", "No history available", "—")
    else:
        for alert in flat[:20]:
            ts = datetime.fromtimestamp(alert["time"]).strftime("%Y-%m-%d %H:%M:%S")
            threat = alert.get("threat", 0)
            color = CATEGORY_COLORS.get(threat, "#FF0000")
            label = CATEGORY_LABELS.get(threat, f"Threat {threat}")
            cities = ", ".join(alert.get("cities", []))
            table.add_row(ts, f"[bold {color}]{label}[/]", cities or "—")

    return Panel(
        table,
        title="[bold magenta]Alert History — tzevaadom[/bold magenta]",
        border_style="magenta",
        box=box.ROUNDED,
    )


def make_warning_overlay(
    alert: dict,
    matching_cities: list[str],
    city_data: dict,
    areas: dict[int, str],
) -> Panel:
    """Full-screen warning panel shown when a watched locality is under alert."""
    cat = str(alert.get("cat", ""))
    threat = OREF_CAT_TO_THREAT.get(cat, 0)
    color = CATEGORY_COLORS.get(threat, "#FF0000")
    cat_label = CATEGORY_LABELS.get(threat, f"Category {cat}")
    title_he = alert.get("title", "")

    # Shortest evac_time among the matched cities (fall back to 90 s)
    evac_times = [
        city_data[c]["evac_time"]
        for c in matching_cities
        if c in city_data and city_data[c].get("evac_time")
    ]
    evac_time = min(evac_times) if evac_times else DEFAULT_EVAC_TIME
    instructions_tmpl = CATEGORY_INSTRUCTIONS.get(threat, "היכנסו מיד למרחב המוגן!")
    instructions = instructions_tmpl.format(time=evac_time)

    content = Text(justify="center")
    content.append("\n")
    content.append("🚨  אזעקה פעילה  🚨\n", style=f"bold {color} blink")
    content.append(f"\n{cat_label}\n", style=f"bold {color}")
    if title_he:
        content.append(f"{title_he}\n", style="yellow")
    content.append("\n")
    content.append("יישובים מעוקבים בסכנה:\n", style="bold white")
    for city in matching_cities:
        area_id = city_data.get(city, {}).get("area", 0)
        area_name = areas.get(area_id, "")
        suffix = f"  ({area_name})" if area_name else ""
        content.append(f"  📍 {city}{suffix}\n", style=f"bold {color}")
    content.append("\n")
    content.append("📋 הנחיות פיקוד העורף:\n", style="bold cyan")
    content.append(f"  {instructions}\n", style="bold bright_white")

    return Panel(
        Align.center(content, vertical="middle"),
        title=f"[bold blink]⚠   ALERT  —  אזעקה   ⚠[/bold blink]",
        border_style=color,
        box=box.DOUBLE_EDGE,
        padding=(1, 4),
    )


def build_layout(
    poll_count: int,
    now: datetime,
    interval: int,
    current_alert: dict | None,
    session_history: deque,
    server_history: list[dict],
) -> Layout:
    layout = Layout()

    layout.split_column(
        Layout(name="header", size=5),
        Layout(name="alert", size=10),
        Layout(name="body"),
    )

    layout["body"].split_row(
        Layout(name="session_hist"),
        Layout(name="server_hist"),
    )

    layout["header"].update(make_header(poll_count, now, interval))
    layout["alert"].update(make_alert_panel(current_alert))
    layout["session_hist"].update(make_session_history_table(session_history))
    layout["server_hist"].update(make_server_history_table(server_history))

    return layout


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def run(interval: int, watch_cities: list[str]) -> None:
    console = Console()
    session_history: deque = deque(maxlen=MAX_HISTORY)
    last_alert_id: str | None = None
    poll_count = 0

    # Load area names and city data once at startup
    areas = load_areas()
    city_data: dict = fetch_cities() if watch_cities else {}

    # Initial history fetch
    server_history: list[dict] = fetch_history()

    with Live(console=console, screen=True, refresh_per_second=1) as live:
        while True:
            poll_count += 1

            current_alert = fetch_current_alert()

            # Record new unique alert in session history
            if current_alert:
                alert_id = current_alert.get("id", "")
                if alert_id != last_alert_id:
                    last_alert_id = alert_id
                    cat = str(current_alert.get("cat", ""))
                    threat = OREF_CAT_TO_THREAT.get(cat, 0)
                    session_history.append(
                        {
                            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            "category": CATEGORY_LABELS.get(threat, f"Cat {cat}"),
                            "color": CATEGORY_COLORS.get(threat, "#FF0000"),
                            "areas": ", ".join(current_alert.get("data", [])),
                            "desc": current_alert.get("desc", ""),
                        }
                    )
                    # Refresh history when a new alert fires
                    server_history = fetch_history()
            else:
                last_alert_id = None

            # Decide what to display this cycle
            matching = get_matching_cities(current_alert, watch_cities)

            if matching:
                # ── Full-screen warning overlay for watched localities ──────
                overlay = make_warning_overlay(current_alert, matching, city_data, areas)
                ticks = interval * 4
                for _ in range(ticks):
                    live.update(overlay)
                    time.sleep(0.25)
            else:
                # ── Normal dashboard layout ───────────────────────────────
                layout = build_layout(
                    poll_count=poll_count,
                    now=datetime.now(),
                    interval=interval,
                    current_alert=current_alert,
                    session_history=session_history,
                    server_history=server_history,
                )

                # Tick every 0.25 s so only the clock panel is refreshed between polls
                ticks = interval * 4
                for _ in range(ticks):
                    layout["header"].update(make_header(poll_count, datetime.now(), interval))
                    live.update(layout)
                    time.sleep(0.25)


def main() -> None:
    if sys.version_info < (3, 10):
        print("Error: Python 3.10 or newer is required.", file=sys.stderr)
        sys.exit(1)

    parser = argparse.ArgumentParser(
        description="Full-screen live terminal monitor for Israel OREF alerts."
    )
    parser.add_argument(
        "--interval",
        "-i",
        type=int,
        default=30,
        metavar="SECONDS",
        help="Polling interval in seconds (default: 30)",
    )
    parser.add_argument(
        "--cities",
        "-c",
        action="append",
        metavar="CITY",
        help=(
            "Hebrew locality name to watch for alerts. "
            "Can be used multiple times or as a comma-separated list. "
            "When a watched locality is alerted, a full-screen warning is shown. "
            "Example: -c 'תל אביב - יפו' -c 'ירושלים'"
        ),
    )
    parser.add_argument(
        "--list-cities",
        action="store_true",
        help="Print all known Israeli localities (Hebrew names) and exit.",
    )
    args = parser.parse_args()

    if args.interval < 1:
        print("Error: interval must be at least 1 second.", file=sys.stderr)
        sys.exit(1)

    # ── --list-cities mode ─────────────────────────────────────────────────
    if args.list_cities:
        city_data = fetch_cities()
        if not city_data:
            print("Error: cities.json not found next to alert_watch.py.", file=sys.stderr)
            sys.exit(1)
        areas = load_areas()
        print(f"{'Locality (Hebrew)':<40}  {'English':<28}  {'Area':<22}  Shelter (s)")
        print("-" * 100)
        for name, info in sorted(city_data.items()):
            en = info.get("en", "")
            area_id = info.get("area", 0)
            area_he = areas.get(area_id, "")
            evac = info.get("evac_time", "—")
            print(f"{name:<40}  {en:<28}  {area_he:<22}  {evac}")
        sys.exit(0)

    # ── Parse watched cities ───────────────────────────────────────────────
    watch_cities: list[str] = []
    if args.cities:
        for entry in args.cities:
            watch_cities.extend(c.strip() for c in entry.split(",") if c.strip())

    try:
        run(args.interval, watch_cities)
    except KeyboardInterrupt:
        pass  # clean exit on Ctrl-C


if __name__ == "__main__":
    main()
