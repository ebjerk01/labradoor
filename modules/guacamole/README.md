# guacamole: terminals and consoles

Puts a **terminal** (SSH/telnet) or **console** (RDP/VNC) button on every machine that has an
[Apache Guacamole](https://guacamole.apache.org/) connection: containers, VMs and hypervisor nodes alike. It also
shows how many sessions are open now, and who opened a console from lab lately.

## How a console opens

```
browser ──POST /api/m/guacamole/api/open/<connection>/<object>──▶ gateway ──signed──▶ connector ──▶ Guacamole REST
   ▲            (route + role + _protect, audit log entry)          (owner, or admin with a grant;   (lab-svc: READ only)
   │                                                                 logs it, answers the client URL)
   └── window.open(<public_url>/#/client/<id>) ── Guacamole signs the viewer in with THEIR OWN account (SSO)
```

1. The button calls `POST /api/open/<connection id>/<object id>`. The gateway checks the route (owner; admins see
   below; guests never reach the module) and the installation's `_protect` list, and writes the audit entry
   `open console · POST /api/open/19/workstation · 200` with the user and the time.
2. The connector checks the caller once more, records the open (user, machine, connection name, protocol, how it
   was allowed) in `/var/lib/lab-connectors/guacamole/opened.jsonl`, logs it, and answers the Guacamole client URL of
   exactly that connection.
3. The browser shows it in a window of its own (one per connection, re-used when clicked again). Guacamole signs the
   viewer in with **their own Guacamole account** (on this lab: Authentik SSO), so Guacamole's per-user permissions
   still decide what opens, and Guacamole's connection history names the real person.

**Nothing secret reaches the browser.** lab mints no Guacamole token: the client URL alone opens nothing, the
service user's token stays in the connector, and the SSH keys/passwords stay in Guacamole. The connection list the
module loads every 15 s carries no client URLs; only the audited open route hands one out.

## Who may open what

| | |
|---|---|
| owner | every connection lab can see; a **protected** machine (see `_protect`) asks once more before it opens |
| admin | nothing, unless the owner turns on **Admins may ask for terminals** (connection settings). Then the button says *ask owner*: an owner approval of `POST /api/grant/<connection>/<object>` gives that admin that one connection for **Admin grant (minutes)** (default 30). The owner sees live grants in the machine panel and can revoke them. Grants live in the connector's memory (a restart drops them). A protected machine never gets a button for admins |
| guest | never: the module is owner/admin only and the connector refuses every other role |

Owner-only machines are set per installation in Settings → `~/modules` → guacamole → **owner-only paths**
(`_protect`), one entry per Guacamole connection id: `/api/open/19/**`. The Guacamole connection id is the number in
the connection's admin URL (or in `lab-admin audit` after one open).

Admins with their own Guacamole account can still open the connections Guacamole gives them directly in Guacamole:
lab's rules come on top of Guacamole's, they don't replace them. Keep Guacamole's permissions in line with the
`_protect` list.

## Why not an embedded terminal

Evaluated for the first version (2026-11-16):

- **Guacamole in an iframe** needs the reverse proxy to allow framing by lab (`frame-ancestors`) on Guacamole *and*
  on the identity provider (its login page would load in the frame), plus `frame-src` in lab's CSP. A lab-minted
  Guacamole token would avoid the login, but it would be the service user's: every session would run as that user in
  Guacamole's history, and the token would open *every* connection that user can read (an admin with a grant could
  open any machine). Not worth weakening two proxies for.
- **A native xterm.js terminal** through the gateway needs a new SSH key on the lab host that is root everywhere,
  WebSockets in the gateway (it has none) through the reverse proxy, and a terminal stack of our own to audit.

The separate window keeps lab's CSP as it is (no `frame-src` at all) and adds no credential anywhere.

## Config

| field | |
|---|---|
| `url`, `username`, `password` | Guacamole's base URL as the lab host reaches it, and a service user with READ on the connections and no system permissions |
| `public_url` | where browsers open consoles (default `url`) |
| `admin_terminals` | admins may ask for time-limited terminals (default off) |
| `grant_minutes` | how long an admin's grant lasts, 5–240 (default 30) |

Setting `aliases`: for connections whose name doesn't say which object they belong to (`cisco vwlc=vwlc810`). A
`(CT 112)` / `(VM 123)` hint in the name maps to that Proxmox guest, otherwise the name's first word is the object id.

## Routes

| route | who | |
|---|---|---|
| `GET /api/connections` | owner, admin | the connection tree (names, protocol, active count), no URLs |
| `GET /api/sessions[?id=]` | owner (all), admin (own) | live grants + the last opens |
| `POST /api/open/*/*` | owner; admin with a grant | the client URL, audited |
| `POST /api/grant/*/*` | owner-only (admins: approval) | the approved run stores the grant |
| `POST /api/sessions/revoke` | owner-only | `{user?, id?}`, drops matching grants |
