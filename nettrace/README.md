# NetTrace — Vehicle Network Monitor

Monitor internet performance from a moving vehicle, correlate with GPS location, and identify connectivity dead zones across New Zealand.

## What it does

- **Latency / jitter / packet loss** — continuous `fping` probes to configurable targets (1.1.1.1, 8.8.8.8, or custom)
- **GPS tracking** — polls Starlink, 4G router, or USB GPS dongle; ties every network reading to a map coordinate
- **Route map** — Leaflet.js map showing your GPS track colour-coded by signal quality, with bad-spot markers
- **Traceroute** — periodic `mtr` runs with 24-hour history comparison to detect routing changes
- **Speed test** — on-demand via `speedtest-cli`, results mapped to GPS position
- **Bad spot detection** — automatic flagging when metrics exceed thresholds, with duration and GPS bounds
- **Grafana dashboards** — long-term graphing via Prometheus time-series storage

## Quick start

```bash
# Clone or copy the project to your vehicle's Linux box
git clone <repo-url> nettrace
cd nettrace

# Run the installer (Ubuntu/Debian)
sudo bash scripts/install.sh
```

The installer handles everything: system packages, Python venv, nginx, Docker (Prometheus + Grafana), and systemd service.

Once running, open `http://<vehicle-ip>` in a browser.

## Architecture

```
┌─────────────────────────────────────────────────────┐
│  Browser (any device on vehicle LAN / hotspot)      │
└───────────────┬─────────────────────────────────────┘
                │ :80
┌───────────────▼─────────────────────────────────────┐
│  nginx (reverse proxy)                              │
│    /         → Flask :5000                          │
│    /grafana/ → Grafana :3000                        │
│    /metrics  → Prometheus exporter :9101             │
└───────────────┬──────────┬──────────────────────────┘
                │          │
┌───────────────▼──┐  ┌────▼──────────────────────────┐
│  Flask + Gunicorn│  │  Prometheus :9090              │
│  (dashboard API) │  │    ← scrapes :9101 / 5s        │
│                  │  │                                │
│  Collector       │  │  Grafana :3000                 │
│  threads:        │  │    ← queries Prometheus        │
│   • fping loop   │  └───────────────────────────────┘
│   • mtr loop     │
│   • GPS poller   │        ┌─────────────────────┐
│   • interface    │───────►│  SQLite              │
│     detector     │        │  (traceroute history, │
│                  │        │   bad spots, speed    │
│  Prom exporter   │        │   test results)       │
│  :9101           │        └─────────────────────┘
└──────────────────┘
```

## Configuration

Edit `/opt/nettrace/config/nettrace.yaml` after install. Key sections:

### GPS source

Set `gps.source` to one of:

| Source       | When to use                                    |
|-------------|------------------------------------------------|
| `starlink`  | Starlink Dishy as primary link (gRPC at 192.168.100.1) |
| `router_api`| 4G router with GPS module (Peplink, Cradlepoint, etc) |
| `gpsd`      | USB GPS dongle via gpsd daemon                 |

### Ping targets

Add or remove targets under `ping.targets`:

```yaml
ping:
  targets:
    - host: "1.1.1.1"
      label: "Cloudflare"
    - host: "8.8.8.8"
      label: "Google DNS"
    - host: "9.9.9.9"
      label: "Quad9"
```

### Traceroute

Change the destination and schedule:

```yaml
traceroute:
  target: "202.37.17.237"
  run_interval_min: 5
  history_retention_hours: 24
```

### Bad spot thresholds

Tune what counts as a "bad spot":

```yaml
thresholds:
  latency_ms: 80
  jitter_ms: 25
  packet_loss_pct: 2.0
  sustained_sec: 10
```

After editing, restart: `sudo systemctl restart nettrace`

## Management

```bash
# Service status
sudo systemctl status nettrace

# Live logs
journalctl -u nettrace -f

# Restart after config change
sudo systemctl restart nettrace

# Restart Prometheus + Grafana
cd /opt/nettrace && sudo docker-compose restart

# View raw metrics
curl http://localhost:9101/metrics

# Query SQLite data
sqlite3 /opt/nettrace/data/nettrace.db "SELECT * FROM bad_spots ORDER BY start_time DESC LIMIT 10;"
```

## API endpoints

| Method | Path                      | Description                    |
|--------|---------------------------|--------------------------------|
| GET    | `/api/state`              | Live state (ping, GPS, etc)    |
| GET    | `/api/config`             | Current config                 |
| PUT    | `/api/config`             | Update config                  |
| GET/POST/DELETE | `/api/targets`   | Manage ping targets            |
| POST   | `/api/speedtest`          | Trigger speed test             |
| GET    | `/api/speedtest/history`  | Speed test results             |
| POST   | `/api/traceroute/run`     | Trigger traceroute             |
| GET    | `/api/traceroute/history` | Traceroute runs (24h)          |
| GET    | `/api/traceroute/compare` | Diff two runs (?a=ID&b=ID)     |
| GET    | `/api/badspots`           | Bad spot events                |
| GET    | `/api/ping/history`       | Ping history for graphing      |
| GET    | `/api/gps/track`          | GPS track with quality overlay |

## Offline map tiles

For areas with no connectivity, pre-cache OpenStreetMap tiles:

```bash
# Install a tile downloader
pip3 install mobac-cli  # or use MOBAC GUI

# Download tiles for your route corridor at zoom 10-16
# e.g. Auckland-Whangarei bounding box
# lat: -36.0 to -37.0, lon: 174.0 to 176.0
```

Then configure Leaflet to use local tile storage (modify dashboard.html tile URL).

## Uninstall

```bash
sudo bash /opt/nettrace/scripts/uninstall.sh
# or from source:
sudo bash scripts/uninstall.sh
```

## Requirements

- Ubuntu 22.04+ / Debian 12+ (other distros: adapt install.sh)
- Docker + Docker Compose
- Python 3.10+
- Network tools: fping, mtr
- GPS: Starlink dish, 4G router with GPS, or USB GPS dongle
