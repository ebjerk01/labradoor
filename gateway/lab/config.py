"""Settings from the environment (/etc/lab/lab.env)."""
import os


def _s(key, default=""):
    return os.environ.get(key, default)


def _b(key, default="0"):
    return _s(key, default).strip().lower() in ("1", "true", "yes", "on")


HOST = _s("LAB_HOST", "0.0.0.0")
PORT = int(_s("LAB_PORT", "8100"))
DB = _s("LAB_DB", "/var/lib/lab/lab.sqlite3")
STATIC_DIR = _s("LAB_STATIC", "/opt/lab/ui/dist")
MODULES_DIR = _s("LAB_MODULES", "/opt/lab/modules")
KEYS_DIR = _s("LAB_KEYS", "/etc/lab/keys")
BACKENDS_FILE = _s("LAB_BACKENDS", "/etc/lab/backends.json")      # optional per-site backend URL overrides
# modules installed from catalogs (docs/catalog.md): root's tree, read-only here; the core's own release key (its
# packages may replace a bundled module); the root helper that installs them
INSTALLED_DIR = _s("LAB_INSTALLED_MODULES", "/var/lib/lab-modules")
RELEASE_PUB = _s("LAB_RELEASE_PUB", "/etc/lab/release.pub")
MODULE_HELPER = _s("LAB_MODULE_HELPER", "/run/lab-module-helper.sock")
TOPOLOGY_FILE = _s("LAB_TOPOLOGY", "/etc/lab/topology.json")      # external/network part of the map
PUBLIC_URL = _s("LAB_PUBLIC_URL", "http://localhost:8100").rstrip("/")  # the address people open (the installer sets it)
BRAND = _s("LAB_BRAND", "labradoor")  # the name in the corner, the tab title and mails
OIDC_NAME = _s("LAB_OIDC_NAME")       # how the SSO button names the login service (default: its host)

OIDC_ISSUER = _s("LAB_OIDC_ISSUER")
OIDC_CLIENT_ID = _s("LAB_OIDC_CLIENT_ID")
OIDC_CLIENT_SECRET = _s("LAB_OIDC_CLIENT_SECRET")
OWNER_GROUP = _s("LAB_OWNER_GROUP", "lab-owners")
ADMIN_GROUP = _s("LAB_ADMIN_GROUP", "lab-admins")

SESSION_DAYS = int(_s("LAB_SESSION_DAYS", "14"))
COOKIE_SECURE = _b("LAB_COOKIE_SECURE", "1")
TRUST_PROXY = _b("LAB_TRUST_PROXY", "1")
# whose X-Real-IP / X-Forwarded-For counts (your reverse proxy); anyone else gets their socket address. Nothing by
# default. Loopback (127.0.0.0/8, ::1) counts only together with LAB_PROXY_SECRET: connectors run on this host as their
# own users and reach :8100 from 127.0.0.1 too, so a loopback address alone proves nothing (review 2026-11-15, L6).
TRUSTED_PROXIES = {a.strip() for a in _s("LAB_TRUSTED_PROXIES", "").split(",") if a.strip()}
# optional: the reverse proxy sends `X-Lab-Proxy-Secret: <this>`; when set, forwarded headers count only with it (from
# any trusted proxy). Required for a proxy on this host (loopback).
PROXY_SECRET = _s("LAB_PROXY_SECRET")
LOGIN_ATTEMPTS = int(_s("LAB_LOGIN_ATTEMPTS", "5"))
APPROVAL_HOURS = int(_s("LAB_APPROVAL_HOURS", "24"))
METRICS_ALLOW = [a.strip() for a in _s("LAB_METRICS_ALLOW", "127.0.0.1").split(",") if a.strip()]  # + your monitoring
HEALTH_INTERVAL = int(_s("LAB_HEALTH_INTERVAL", "30"))
# the gateway's own secret for delegation tokens (delegate.py): next to the DB, mode 600, never in the keys dir
SETUP_LINK_FILE = _s("LAB_SETUP_LINK_FILE", "/etc/lab/setup-link")  # first run: the owner link, root 0600 (lab-admin)
MASTER_KEY = _s("LAB_MASTER_KEY", "/etc/lab/master.key")  # seals module secrets (secretbox.py); keep a copy in the vault
DELEGATION_KEY = _s("LAB_DELEGATION_KEY", os.path.join(os.path.dirname(DB) or ".", "delegation.key"))

SMTP_HOST = _s("LAB_SMTP_HOST")
SMTP_PORT = int(_s("LAB_SMTP_PORT", "587"))
SMTP_USER = _s("LAB_SMTP_USER")
SMTP_PASSWORD = _s("LAB_SMTP_PASSWORD")
SMTP_FROM = _s("LAB_SMTP_FROM")
OWNER_EMAIL = _s("LAB_OWNER_EMAIL")
