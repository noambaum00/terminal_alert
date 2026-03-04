#!/usr/bin/env python3
"""
Israel Home Front Command – Live Alert Monitor
A ctop-style full-screen terminal dashboard that polls the OREF alerts API
and displays rocket/missile/threat alerts in real time.

Usage:
    python3 alert_watch.py
    python3 alert_watch.py --interval 3   # poll every 3 seconds (default: 5)

Press  q  or  Ctrl-C  to quit.
"""

import argparse
import sys
import time
from collections import deque
from datetime import datetime

import requests
from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich import box

# ---------------------------------------------------------------------------
# OREF API endpoints
# ---------------------------------------------------------------------------
ALERTS_URL = "https://www.oref.org.il/WarningMessages/alert/alerts.json"
HISTORY_URL = "https://www.oref.org.il/WarningMessages/alert/alertsHistory.json"

HEADERS = {
    "Referer": "https://www.oref.org.il/",
    "X-Requested-With": "XMLHttpRequest",
    "Accept": "application/json",
}

# Max number of history entries kept in memory during the session
MAX_HISTORY = 50

# Human-readable category labels
CATEGORY_LABELS = {
    "1": "🚀 Rockets / Missiles",
    "2": "✈️  Hostile Aircraft",
    "3": "🌍 Earthquake",
    "4": "☣️  Hazardous Materials",
    "5": "🌊 Tsunami",
    "6": "🔫 Terrorist Incursion",
    "7": "☢️  Unconventional Missile",
    "13": "☢️  Radiological Event",
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
    """Return the server-side alert history list (may be empty)."""
    try:
        resp = requests.get(HISTORY_URL, headers=HEADERS, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, list):
            return data
        return []
    except requests.RequestException:
        return []


# ---------------------------------------------------------------------------
# UI helpers
# ---------------------------------------------------------------------------

def make_header(poll_count: int, last_update: str, interval: int) -> Panel:
    title = Text("🇮🇱  Israel Home Front Command — Live Alert Monitor", style="bold white")
    subtitle = Text(
        f"  Polling every {interval}s  │  Polls: {poll_count}  │  Last update: {last_update}  │  [dim]q / Ctrl-C to quit[/dim]",
        style="dim cyan",
    )
    combined = Text.assemble(title, "\n", subtitle)
    return Panel(combined, style="bold blue", box=box.HEAVY)


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
    cat_label = CATEGORY_LABELS.get(cat, f"Category {cat}")
    title_he = alert.get("title", "")
    desc_he = alert.get("desc", "")
    areas = alert.get("data", [])

    area_text = Text()
    for i, area in enumerate(areas):
        if i:
            area_text.append("  •  ", style="bright_red")
        area_text.append(area, style="bold bright_yellow")

    content = Text()
    content.append(f"  {cat_label}\n", style="bold bright_red")
    if title_he:
        content.append(f"  {title_he}\n", style="bright_yellow")
    if desc_he:
        content.append(f"  {desc_he}\n", style="yellow")
    content.append("\n  Affected areas:\n  ", style="white")
    content.append_text(area_text)

    return Panel(
        content,
        title=f"[bold red blink]⚠  ACTIVE ALERT — {len(areas)} area(s)[/bold red blink]",
        border_style="bright_red",
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
    table.add_column("Category", style="bright_red", min_width=24)
    table.add_column("Areas", style="yellow")

    if not session_history:
        table.add_row("—", "No alerts recorded yet", "—")
    else:
        for entry in reversed(session_history):
            table.add_row(
                entry["time"],
                entry["category"],
                entry["areas"],
            )

    return Panel(
        table,
        title="[bold cyan]Session Alert History[/bold cyan]",
        border_style="cyan",
        box=box.ROUNDED,
    )


def make_server_history_table(server_history: list[dict]) -> Panel:
    table = Table(
        box=box.SIMPLE_HEAVY,
        show_header=True,
        header_style="bold magenta",
        expand=True,
        show_lines=False,
    )
    table.add_column("Time", style="dim", width=19, no_wrap=True)
    table.add_column("Category", style="bright_red", min_width=24)
    table.add_column("Areas", style="yellow")

    if not server_history:
        table.add_row("—", "No server history available", "—")
    else:
        for entry in server_history[:20]:
            cat = str(entry.get("cat", ""))
            cat_label = CATEGORY_LABELS.get(cat, f"Cat {cat}")
            areas = ", ".join(entry.get("data", []))
            ts = entry.get("alertDate", entry.get("date", ""))
            table.add_row(ts or "—", cat_label, areas or "—")

    return Panel(
        table,
        title="[bold magenta]Server Alert History (last 20)[/bold magenta]",
        border_style="magenta",
        box=box.ROUNDED,
    )


def build_layout(
    poll_count: int,
    last_update: str,
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

    layout["header"].update(make_header(poll_count, last_update, interval))
    layout["alert"].update(make_alert_panel(current_alert))
    layout["session_hist"].update(make_session_history_table(session_history))
    layout["server_hist"].update(make_server_history_table(server_history))

    return layout


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def run(interval: int) -> None:
    console = Console()
    session_history: deque = deque(maxlen=MAX_HISTORY)
    last_alert_id: str | None = None
    poll_count = 0
    server_history: list[dict] = []

    # Initial server history fetch
    server_history = fetch_history()

    with Live(console=console, screen=True, refresh_per_second=2) as live:
        while True:
            poll_count += 1
            last_update = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            current_alert = fetch_current_alert()

            # Record new unique alert in session history
            if current_alert:
                alert_id = current_alert.get("id", "")
                if alert_id != last_alert_id:
                    last_alert_id = alert_id
                    cat = str(current_alert.get("cat", ""))
                    session_history.append(
                        {
                            "time": last_update,
                            "category": CATEGORY_LABELS.get(cat, f"Cat {cat}"),
                            "areas": ", ".join(current_alert.get("data", [])),
                        }
                    )
                    # Refresh server history when a new alert fires
                    server_history = fetch_history()
            else:
                last_alert_id = None

            layout = build_layout(
                poll_count=poll_count,
                last_update=last_update,
                interval=interval,
                current_alert=current_alert,
                session_history=session_history,
                server_history=server_history,
            )
            live.update(layout)

            # Sleep in small increments so we can react to Ctrl-C quickly
            for _ in range(interval * 4):
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
        default=5,
        metavar="SECONDS",
        help="Polling interval in seconds (default: 5)",
    )
    args = parser.parse_args()

    if args.interval < 1:
        print("Error: interval must be at least 1 second.", file=sys.stderr)
        sys.exit(1)

    try:
        run(args.interval)
    except KeyboardInterrupt:
        pass  # clean exit on Ctrl-C / q (handled by terminal)


if __name__ == "__main__":
    main()
