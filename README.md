# terminal_alert

A **ctop-style full-screen terminal dashboard** that watches for Israel Home Front Command (OREF) alerts and shows them **live** in your terminal.

## Features

- 🚨 Real-time polling of the official OREF alerts API
- Full-screen rich TUI (like `ctop`) — auto-refreshes every few seconds
- **Current alert panel** — red/blinking when an alert is active, green when all-clear
- **Session history** — all alerts seen since you started the tool
- **Server history** — last 20 alerts from the OREF server
- Configurable polling interval
- Press `Ctrl-C` to quit cleanly

## Requirements

- Python 3.10+
- `rich` ≥ 13.0
- `requests` ≥ 2.28

## Installation

```bash
pip install -r requirements.txt
```

## Usage

```bash
# Default: poll every 5 seconds
python3 alert_watch.py

# Custom interval (e.g. every 3 seconds)
python3 alert_watch.py --interval 3
python3 alert_watch.py -i 3
```

Press **Ctrl-C** to exit.

## Data Source

- Current alerts: `https://www.oref.org.il/WarningMessages/alert/alerts.json`
- Alert history: `https://www.oref.org.il/WarningMessages/alert/alertsHistory.json`
