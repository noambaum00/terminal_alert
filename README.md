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

### 🍺 Homebrew (macOS — recommended)

```bash
brew tap noambaum00/terminal_alert https://github.com/noambaum00/terminal_alert
brew install --HEAD terminal-alert
```

After installation the `terminal-alert` command is available system-wide:

```bash
terminal-alert
terminal-alert --interval 10
```

### pip (manual)

```bash
pip install -r requirements.txt
```

## Usage

```bash
# Default: poll every 30 seconds
python3 alert_watch.py

# Custom interval (e.g. every 10 seconds)
python3 alert_watch.py --interval 10
python3 alert_watch.py -i 10
```

Press **Ctrl-C** to exit.

## Data Source

- Current alerts: `https://www.oref.org.il/WarningMessages/alert/alerts.json`
- Alert history: `https://www.oref.org.il/WarningMessages/alert/alertsHistory.json`
