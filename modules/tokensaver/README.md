# tokenSaver (lab module `tokensaver`)

Shows the tokenSaver plugin's savings (calls / tokens / $ / time saved) from workstation's
Claude Code sessions.

- Data source: a small LAN endpoint on workstation, `http://192.0.2.53:8124` (systemd
  `tokensaver-stats.service`, script `/opt/tokensaver-stats/exporter.py`), which serves
  `tokensaver status` as JSON. Auth is `X-Api-Key` (token in `/opt/tokensaver-stats/.token`).
- `manifest.json` proxies to that endpoint via the gateway; no custom connector.
- Set the module config (URL + api_key) in lab Settings, or
  `lab-admin module-config tokensaver url=http://192.0.2.53:8124 api_key=<token>`.
- Read-only (GET only). Savings start at 0 until Claude Code sessions accrue on workstation.
