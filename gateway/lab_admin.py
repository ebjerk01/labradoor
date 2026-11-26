#!/usr/bin/env python3
"""lab-admin — command line for the Labradoor gateway.

  lab-admin new-module ID [--name NAME] [--backend URL]   scaffold modules/ID from modules/_template
  lab-admin modules                                       list modules, validate manifests
  lab-admin keys                                          inventory: every key/token file, who uses it, orphans
  lab-admin config ID [KEY=VALUE | KEY=@FILE ...] [--clear KEY]
                                                          show / set a v2 module's per-installation config (secrets
                                                          are sealed with /etc/lab/master.key; @FILE reads a file)
  lab-admin keygen ID                                     create /etc/lab/keys/ID.key, print it for the backend
  lab-admin users | sessions                              accounts (local/sso, 2FA, disabled) / active sessions
  lab-admin revoke USER                                   end all of USER's sessions
  lab-admin passwd USER [--role owner|admin|guest]        set a local password (reads stdin); creates a local
                                                          account when USER is new (needs --role)
  lab-admin user USER --disable | --enable | --reset-2fa  lock/unlock an account, or turn its 2FA off (lost phone)
  lab-admin setup-link [--recover]                        first run: print a fresh one-time link (1 h) to create the
                                                          owner account and keep it in /etc/lab/setup-link (root 0600)
                                                          (root only; never while an owner is active; once an owner
                                                          has existed only with --recover — setup never reopens by
                                                          itself)
  lab-admin approvals [--all] | deny ID                   owner approvals (approve in the UI)
  lab-admin audit [-n N]                                  recent audit log
  lab-admin update --check | --status                     check the release index (signed) / show the update state
  lab-admin update [VERSION] [--yes]                      download, verify and install VERSION (default: the newest
                                                          allowed one) through the update helper, like Settings → ~/updates
  lab-admin rollback [RELEASE] [--with-db] [--list]       back to an earlier release (see deploy/lab-rollback)
  lab-admin publisher list | add FILE [--name N] [--allow-privileged] | remove N
  lab-admin publisher allow-privileged N | revoke-privileged N
                                                          trusted module publishers (/etc/lab/publishers.d; root
                                                          only): a catalog or package installs only when one of these
                                                          keys signed it (docs/catalog.md); modules with delegate /
                                                          uses_credentials_of only from the core key or a publisher
                                                          allowed for privileged modules
  lab-admin package [status] | check URL | install ID VERSION [--catalog URL] [--yes] | update ID VERSION [--yes]
                    | rollback ID | remove ID [--drop-config] | catalog-add URL | catalog-remove URL
                                                          modules from catalogs through the module helper, like
                                                          Settings → ~/catalogs (remove keeps the config unless
                                                          --drop-config); catalog-add/-remove edit the catalog list
                                                          Settings → ~/catalogs checks (adding verifies the catalog)

Run as root, every command that opens the database first drops to the gateway's user `lab`: /var/lib/lab is lab's, and
root must not open, write or chown files there that lab could have replaced with links (security review 2026-11-15, H2).
"""
import argparse
import json
import os
import re
import secrets
import shutil
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lab import auth, config  # noqa: E402
from lab.registry import ID_RE, Registry  # noqa: E402
from lab.store import Store  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _t(ts):
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(ts)) if ts else "-"


def new_module(args):
    mid = args.id
    if not ID_RE.match(mid):
        sys.exit("id: lowercase letters, digits and -, 2-31 chars, starting with a letter")
    mods = args.modules or os.path.join(REPO, "modules")
    src, dst = os.path.join(mods, "_template"), os.path.join(mods, mid)
    if os.path.exists(dst):
        sys.exit(f"{dst} exists")
    shutil.copytree(src, dst)
    name = args.name or mid.replace("-", " ").title()
    for root, _, files in os.walk(dst):
        for fn in files:
            p = os.path.join(root, fn)
            with open(p, encoding="utf-8") as f:
                s = f.read()
            s = s.replace("__ID__", mid).replace("__NAME__", name).replace("__BACKEND__", args.backend or "http://127.0.0.1:8080")
            with open(p, "w", encoding="utf-8") as f:
                f.write(s)
    print(f"created modules/{mid} (manifest v2 — reference: docs/modules.md)\n\nnext:\n"
          f"  1. modules/{mid}/manifest.json: kind, category, config fields (what each installation fills in), the backend\n"
          f"     template built from them, and EVERY backend route the UI may call (writes need min or owner_only + label)\n"
          f"  2. build the UI parts in modules/{mid}/ui/ (index.js lists facets, tiles, objects, search, ticker)\n"
          f"  3. a third-party API: keep backend.auth (the secret comes from config). Your own backend instead: drop\n"
          f"     backend.auth, copy sdk/python/labauth.py in, accept X-Lab-Auth, and run: lab-admin keygen {mid}\n"
          f"  4. deploy, then Settings → {mid} → connection (or: lab-admin config {mid} url=… api_key=@/path/to/file)")


def _registry(args):
    """Bundled modules + the ones installed from catalogs (the gateway's view, docs/catalog.md)."""
    return Registry(args.modules or config.MODULES_DIR, config.BACKENDS_FILE, installed_dir=config.INSTALLED_DIR,
                    abi_file=os.path.join(config.STATIC_DIR, "abi.json"), release_pub=config.RELEASE_PUB)


def modules(args):
    reg = _registry(args)
    v2cfg = {}
    if any(m.get("_v2") for m in reg.modules.values()) and os.path.exists(config.DB):
        stored = Store(config.DB).module_config()
        v2cfg = {mid: {k: ("<set>" if sec else v) for k, (v, sec) in kv.items()} for mid, kv in stored.items()}
        reg.apply(config=v2cfg)
    for m in reg.modules.values():
        auth = (m.get("backend") or m.get("_backend_tpl") or {}).get("auth")
        key = ("v2 (no backend)" if not m.get("_backend_tpl") else "v2 config" if m.get("backend")
               else "v2 NEEDS SETUP: " + ",".join(m.get("_missing") or []))
        if m.get("_backend_tpl") and not auth and not os.path.exists(os.path.join(config.KEYS_DIR, f"{m['id']}.key")):
            key += " · NO KEY"  # an own backend (signed X-Lab-Auth) needs lab-admin keygen
        print(f"{m['id']:<14} {m['name']:<24} {len(m['routes']):>3} routes  {(m.get('backend') or {}).get('url', '-'):<30} {key}")
    for name, err in reg.errors.items():
        print(f"{name:<14} ERROR {err}")
    if reg.errors:
        sys.exit(1)


def keys(args):
    """Every file in the keys dir, who uses it (module manifest, connector code, gateway code), its mode/owner/age —
    orphans (nothing references them) and missing keys; then the connectors' isolation: each runs as its own user
    lab-c-<id> that is NOT in group lab, no env files left in /etc/lab/connectors, no published secret view, and a
    master key only the gateway's group can read."""
    import grp
    import pwd
    root = os.path.dirname(os.path.abspath(__file__))
    reg = _registry(args)
    want = {}
    for m in reg.modules.values():
        # credentials live in the encrypted module config, not in files; an own backend has its HMAC <id>.key
        if (m.get("_backend_tpl") or {}) and not (m.get("_backend_tpl") or {}).get("auth"):
            want.setdefault(f"{m['id']}.key", []).append(f"module {m['id']}")
    sources = []  # (label, text) of code + env files that may name a key file
    cdir = os.path.join(os.path.dirname(root), "connectors")
    for cid in sorted(os.listdir(cdir)) if os.path.isdir(cdir) else []:
        for fn in os.listdir(os.path.join(cdir, cid)) if os.path.isdir(os.path.join(cdir, cid)) else []:
            if fn.endswith(".py") and not fn.startswith("test_"):
                with open(os.path.join(cdir, cid, fn), encoding="utf-8") as f:
                    sources.append((f"connector {cid}", f.read()))
    for fn in os.listdir(os.path.join(root, "lab")):
        if fn.endswith(".py"):
            with open(os.path.join(root, "lab", fn), encoding="utf-8") as f:
                sources.append((f"gateway {fn[:-3]}", f.read()))
    envdir = "/etc/lab/connectors"  # before step 15 connectors were configured here; nothing should be left
    envs = sorted(os.listdir(envdir)) if os.path.isdir(envdir) else []
    now, bad = time.time(), 0

    def meta(path):
        st = os.stat(path)
        return (f"{st.st_mode & 0o777:o} {pwd.getpwuid(st.st_uid).pw_name}:{grp.getgrgid(st.st_gid).gr_name}",
                f"{(now - st.st_mtime) / 86400:.0f}d")
    print(f"{'file':<26} {'mode':<16} {'age':>5}  used by")
    files = sorted(os.listdir(config.KEYS_DIR)) if os.path.isdir(config.KEYS_DIR) else []
    for fn in files:
        users = list(want.get(fn, []))
        users += sorted({label for label, text in sources if fn in text and label not in users})
        mode, age = meta(os.path.join(config.KEYS_DIR, fn))
        world = int(mode.split()[0], 8) & 0o007
        flag = ("" if users else "  ← ORPHAN (nothing references it)") + ("  ← WORLD-READABLE" if world else "")
        bad += (not users) + bool(world)
        print(f"{fn:<26} {mode:<16} {age:>5}  {', '.join(users) or '-'}{flag}")
    conn_ids = {mid for mid, m in reg.modules.items() if m.get("connector")}
    for fn, users in sorted(want.items()):
        if fn not in files:
            if fn[:-4] in conn_ids:  # a connector's key is made by the helper when the module is turned on
                print(f"{fn:<26} {'-':<16} {'':>5}  {', '.join(users)} (made when the module is turned on)")
                continue
            bad += 1
            print(f"{fn:<26} {'MISSING':<16} {'':>5}  {', '.join(users)}")
    if envs:
        print(f"\n{envdir}: connectors get their config from the gateway now — retire these (your password manager copy first):")
        for fn in envs:
            mode, age = meta(os.path.join(envdir, fn))
            bad += 1
            print(f"  {fn:<24} {mode:<16} {age:>5}  ← LEFTOVER")
    # connectors: own users, outside group lab (that group reads this dir and the master key)
    conns = sorted(mid for mid, m in reg.modules.items() if m.get("connector"))
    try:
        lab_members = set(grp.getgrnam("lab").gr_mem)
    except KeyError:
        lab_members = set()
    print(f"\n{'connector':<12} {'user':<18} state")
    for mid in conns:
        name = f"lab-c-{mid}"
        try:
            pwd.getpwnam(name)
            state = "IN GROUP lab  ← must not be" if name in lab_members else "ok (not in group lab)"
            bad += name in lab_members
        except KeyError:
            state = "no user yet (made when the module is turned on)"
        print(f"{mid:<12} {name:<18} {state}")
    for name in sorted(lab_members - {"lab"}):
        bad += 1
        print(f"group lab has member {name}  ← only the gateway (user lab) belongs there")
    for p in (os.path.join(os.path.dirname(config.DB), "backends.v2.json"),):
        if os.path.exists(p):
            bad += 1
            print(f"{p} exists  ← the old published secret view: remove it")
    if os.path.exists(config.MASTER_KEY):
        mode, age = meta(config.MASTER_KEY)
        ok = mode.split()[0] in ("640", "600") and mode.split()[1].split(":")[1] in ("lab", "root")
        bad += not ok
        print(f"\n{config.MASTER_KEY} {mode} {age}{'' if ok else '  ← must be 640 root:lab (gateway only)'}")
    for p in (getattr(config, "DELEGATION_KEY", ""),):
        if p and os.path.exists(p):
            mode, age = meta(p)
            print(f"\n{p} {mode} {age} (delegation secret, gateway only)")
    sys.exit(1 if bad else 0)


def config_cmd(args):
    from lab import manifest2  # noqa: F401 (registry imports it lazily)
    from lab.secretbox import SecretBox
    reg = _registry(args)
    mod = reg.get(args.id)
    if not mod or not mod.get("_v2"):
        sys.exit(f"{args.id}: no such v2 module")
    store = Store(config.DB)
    fields = {f["key"]: f for f in mod["config"]["fields"]}
    box = SecretBox.from_file(config.MASTER_KEY)
    for k in args.clear or []:
        if k not in fields:
            sys.exit(f"unknown field {k}")
        store.set_module_config(mod["id"], k, None)
    for kv in args.set or []:
        k, _, v = kv.partition("=")
        if k not in fields or not _:
            sys.exit(f"KEY=VALUE with KEY one of {sorted(fields)}")
        f = fields[k]
        if f["type"] == "bool":
            v = v.lower() in ("1", "true", "yes", "on")
        elif f["type"] == "int":
            v = int(v)
        elif f["type"] == "list":
            v = [x.strip() for x in v.split(",") if x.strip()]
        elif f["type"] == "url":
            v = v.rstrip("/")
        if f["type"] == "secret":
            if not box:
                sys.exit(f"no master key at {config.MASTER_KEY}")
            store.set_module_config(mod["id"], k, box.seal(mod["id"], k, v), secret=True)
        else:
            store.set_module_config(mod["id"], k, v)
        store.audit({"username": "lab-admin", "role": "owner"}, "module-config", mod["id"], k, "ok", "set from the CLI")
    stored = store.module_config(mod["id"])
    for k, f in fields.items():
        v, sec = stored.get(k, (None, False))
        shown = ("(set)" if v is not None else "(not set)") if f["type"] == "secret" else (v if v is not None else f"(default {f.get('default')})")
        print(f"{k:<20} {f['type']:<7} {'required ' if f.get('required') else ''}{shown}")
    if args.set or args.clear:
        print("restart the gateway to apply: systemctl restart lab"
              + (f"; then the connector: systemctl restart lab-connector@{mod['id']}" if mod.get("connector") else ""))


def keygen(args):
    if not ID_RE.match(args.id):
        sys.exit("bad id")
    os.makedirs(config.KEYS_DIR, mode=0o750, exist_ok=True)
    path = os.path.join(config.KEYS_DIR, f"{args.id}.key")
    if os.path.exists(path) and not args.force:
        sys.exit(f"{path} exists (use --force to rotate; the backend must get the new key)")
    key = secrets.token_hex(32)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o640)
    with os.fdopen(fd, "w") as f:
        f.write(key + "\n")
    try:
        shutil.chown(path, group="lab")
    except (LookupError, PermissionError):
        pass
    print(key)


def users(args, store):
    for u in store.users():
        flags = " ".join(f for f, on in (("local-pw", u["local"]), ("sso", u["sso"]), ("2fa", u["totp"]),
                                          ("DISABLED", u["disabled"])) if on)
        print(f"{u['username']:<16} {u['role']:<6} {_t(u['last_seen'])}  {flags:<22} {','.join(u['groups'])}")


def sessions(args, store):
    for s in store.sessions():
        print(f"{s['username']:<16} {s['via']:<6} {_t(s['created'])} → {_t(s['expires'])}  {s['ip']}  {s['ua'][:50]}")


def revoke(args, store):
    print(f"ended {store.end_sessions_for(args.user)} session(s)")
    store.audit({"username": "lab-admin"}, "revoke-sessions", target=args.user)


def read_password():
    return sys.stdin.readline().rstrip("\n") if not sys.stdin.isatty() else __import__("getpass").getpass("password: ")


def passwd(args, store):
    pw = args.password if args.password is not None else read_password()
    bad = auth.password_problem(pw)
    if bad:
        sys.exit(bad)
    if not store.user(args.user):
        if not args.role:
            sys.exit("unknown user: give --role to create a local-only user")
        from lab.login_api import USERNAME_RE
        if not USERNAME_RE.match(args.user):
            sys.exit("username: 2-64 letters, digits, . _ @ -")
        if store.user_casefold(args.user):
            sys.exit(f"{store.user_casefold(args.user)} exists already (names that differ only in case are one person)")
        store.create_local_user(args.user, args.user, args.role, [], auth.hash_password(pw))
    else:
        if args.role:
            store.set_role(args.user, args.role)
        store.set_password_hash(args.user, auth.hash_password(pw))
    store.audit({"username": "lab-admin"}, "set-local-password", target=args.user)
    u = store.user(args.user)
    print("ok" + (" (an SSO-linked account: its role is refreshed from the SSO groups at the next SSO login)" if u.get("sso") else ""))


def user_cmd(args, store):
    u = store.user(args.user)
    if not u:
        sys.exit("no such user")
    if args.disable:
        store.update_user(args.user, disabled=True)
        store.end_sessions_for(args.user)
    if args.enable:
        store.update_user(args.user, disabled=False)
    if args.reset_2fa:
        store.set_totp(args.user, None)
        store.end_sessions_for(args.user)
    store.audit({"username": "lab-admin"}, "user-changed", target=args.user,
                result=",".join(k for k in ("disable", "enable", "reset_2fa") if getattr(args, k)))
    users(args, type("One", (), {"users": lambda self: [x for x in store.users() if x["username"] == args.user]})())


def _write_private(path, text):
    """path (in root's /etc/lab) := text, mode 0600, atomically; never through a link."""
    tmp = f"{path}.new-{os.getpid()}"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, "w") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        if os.path.lexists(tmp):
            os.unlink(tmp)
        raise


def _mint_setup_link(recover=False):
    """As lab: a fresh setup token (every earlier link stops working). → {"link"} or {"refused": why}."""
    store = Store(config.DB)
    closed = store.setup_closed()
    if store.active_owners():
        return {"refused": "owner"}
    if closed and not recover:
        return {"refused": "closed"}
    link = f"{config.PUBLIC_URL}/setup#{store.new_setup_token()}"
    store.audit({"username": "lab-admin"}, "setup-link-recover" if recover and store.setup_closed() else "setup-link",
                detail="new owner-creation link (1 h)" + (" — RECOVERY: no active owner" if recover else ""))
    return {"link": link}


def setup_link(args):
    """The link goes to the terminal and to a root-only file (config.SETUP_LINK_FILE), never to a log."""
    if os.geteuid() != 0 and not os.environ.get("LAB_ALLOW_NONROOT"):
        sys.exit("run as root (the link creates the owner account)")
    out = _as_lab_child(lambda: _mint_setup_link(recover=bool(getattr(args, "recover", False))))
    if out.get("refused"):
        if os.path.lexists(config.SETUP_LINK_FILE):
            os.unlink(config.SETUP_LINK_FILE)
        if out["refused"] == "closed":
            sys.exit("no active owner, but this installation had one: setup does not reopen by itself.\n"
                     "Prefer bringing the owner back: lab-admin user NAME --enable, or lab-admin passwd NAME --role owner.\n"
                     "To create a NEW owner account through the setup page anyway: lab-admin setup-link --recover")
        sys.exit("an owner exists already: there is no setup link (owners manage accounts in People)")
    out = out["link"]
    _write_private(config.SETUP_LINK_FILE, out + "\n")
    print(f"Open this link within 1 hour to create the owner account (it works once):\n\n  {out}\n\n"
          f"(also in {config.SETUP_LINK_FILE}, root only)")


def approvals(args, store):
    if args.action == "deny":
        ok = store.decide_approval(int(args.id), "denied", "lab-admin")
        print("denied" if ok else "not pending")
        return
    for a in store.approvals(None if args.all else "pending"):
        print(f"#{a['id']:<4} {a['status']:<9} {_t(a['created'])}  {a['requester']:<10} {a['module']}: {a['label']}  {a['reason'][:60]}")


def audit(args, store):
    for a in reversed(store.audit_list(args.n)):
        print(f"{_t(a['ts'])}  {a['username'] or '-':<12} {a['role'] or '':<6} {a['action']:<22} {a['module'] or '':<8} {a['target'] or ''} {a['result'] or ''}")


def update_cmd(args, store):
    """Core updates through the root helper (the same path as Settings → ~/updates; root may use its socket too)."""
    from lab.updates import UpdateHelperError, call_helper, index_setting, record_job

    def call(req, timeout=60):
        try:
            return call_helper({**req, "by": "lab-admin"}, timeout=timeout)
        except UpdateHelperError as e:
            sys.exit(f"update: {e}")

    st = call({"op": "status"})
    if args.status:
        print(f"installed: {st.get('version') or '?'} ({(st.get('commit') or '')[:12]}), release {st.get('live')}")
        print(f"signing key: {st.get('key') or 'none (' + st.get('key_file', '') + ')'}")
        for r in st.get("releases") or []:
            print(f"  {'*' if r['live'] else ' '} {r['name']}  {r['version']} {r['commit'][:7]}")
        if st.get("staged"):
            print(f"staged: {', '.join(st['staged'])}")
        job = st.get("job")
        if job:
            print(f"last job: {job.get('op')} {job.get('target')} — {job.get('state')}: {job.get('message')}")
        return
    index, source = index_setting(store)
    if not index:
        sys.exit("no release index set: LAB_RELEASE_INDEX in /etc/lab/lab.env or Settings → ~/updates")
    chk = call({"op": "check", "index": index}, timeout=120)
    store.audit({"username": "lab-admin", "role": "owner"}, "update-check", "_core", index[:200], "ok",
                f"current {chk.get('current')} latest {chk.get('latest')} update {chk.get('update')}")
    print(f"index ({source}): {index}")
    print(f"installed: {chk.get('current') or '?'}   newest: {chk.get('latest') or '-'}")
    for r in chk.get("releases") or []:
        mark = "→" if r["version"] == chk.get("update") else (" " if r["ok"] else "x")
        print(f"  {mark} {r['version']:<16} {r.get('date', ''):<10} {'' if r['ok'] else r['why']}")
    target = args.version or chk.get("update")
    if args.check:
        if chk.get("update"):
            print(f"\nupdate available: {chk['update']}\n{(next(r for r in chk['releases'] if r['version'] == chk['update']).get('notes') or '').strip()}")
        else:
            print("\nup to date")
        return
    if not target:
        print("up to date")
        return
    rel = next((r for r in chk.get("releases") or [] if r["version"] == target), None)
    if not rel:
        sys.exit(f"{target} is not in the index")
    if not rel["ok"]:
        sys.exit(f"{target}: {rel['why']}")
    if rel.get("notes"):
        print(f"\n{target}:\n{rel['notes'].strip()}\n")
    if not args.yes:
        if not sys.stdin.isatty() or input(f"install {target}? [y/N] ").strip().lower() not in ("y", "yes"):
            sys.exit("not installed")
    out = call({"op": "stage", "index": index, "version": target}, timeout=900)
    print(f"downloaded + verified: {out.get('files')} files, sha256 {out.get('sha256', '')[:16]}…")
    out = call({"op": "apply", "version": target})
    store.audit({"username": "lab-admin", "role": "owner"}, "update-apply", "_core", target, "ok", f"job {out.get('job')}")
    print(f"installing {target} (job {out.get('job')}) …")
    import time as _time
    last = None
    while True:
        _time.sleep(2)
        try:
            job = call_helper({"op": "status"}, timeout=30).get("job") or {}
        except UpdateHelperError:
            continue
        if job.get("id") != out.get("job"):
            continue
        if job.get("state") != last:
            last = job.get("state")
            print(f"  {last}")
        if last in ("ok", "failed", "interrupted"):
            record_job(store, job)
            print(job.get("message"))
            if last != "ok":
                print("\n".join(job.get("tail") or []))
                sys.exit(1)
            return


PUBLISHERS = os.environ.get("LAB_PUBLISHERS", "/etc/lab/publishers.d")


def publisher_cmd(args):
    """Trusted module publishers: root's decision on the host, never the gateway's (a publisher's UI code runs in the
    browser with the viewer's rights, security review 2026-11-15 M5). Files are root-owned 0644 in a root 0755 dir."""
    from lab import modpkg
    if args.action == "list":
        pubs, problems = modpkg.read_publishers(PUBLISHERS)
        core = set(modpkg.file_fingerprints(config.RELEASE_PUB))
        priv = modpkg.read_privileged(PUBLISHERS)
        for name, lines in sorted(pubs.items()):
            for ln in lines:
                fp = modpkg.key_fingerprint(ln)
                print(f"{name:<20} {fp}{'  (the core release key)' if fp in core else ''}"
                      f"{'  privileged' if fp in core or name in priv else ''}  {' '.join(ln.split()[2:])[:40]}")
        for p in problems:
            print(f"PROBLEM: {p}")
        if not pubs:
            print(f"no trusted publishers in {PUBLISHERS}")
        return
    if os.geteuid() != 0:
        sys.exit("lab-admin publisher add/remove: as root (trusting a publisher lets its code run in every owner's browser)")
    os.makedirs(PUBLISHERS, mode=0o755, exist_ok=True)
    st = os.lstat(PUBLISHERS)
    if os.path.islink(PUBLISHERS) or st.st_uid != 0 or st.st_mode & 0o022:
        sys.exit(f"{PUBLISHERS} must be a directory only root can write")
    if args.action in ("allow-privileged", "revoke-privileged"):
        if not args.name or not modpkg.PUBLISHER_RE.match(args.name):
            sys.exit(f"{args.action} NAME (see lab-admin publisher list)")
        if args.action == "allow-privileged":
            if not os.path.isfile(os.path.join(PUBLISHERS, f"{args.name}.pub")):
                sys.exit(f"no publisher {args.name}")
            _allow_privileged(args.name)
        else:
            path = os.path.join(PUBLISHERS, f"{args.name}{modpkg.PRIVILEGED_SUFFIX}")
            if os.path.lexists(path):
                os.unlink(path)
            print(f"publisher {args.name}: no privileged modules any more (installed ones stay; updates are refused)")
        return
    if args.action == "remove":
        if not args.name or not modpkg.PUBLISHER_RE.match(args.name):
            sys.exit("remove NAME (see lab-admin publisher list)")
        path = os.path.join(PUBLISHERS, f"{args.name}.pub")
        if not os.path.isfile(path):
            sys.exit(f"no publisher {args.name}")
        os.unlink(path)
        priv = os.path.join(PUBLISHERS, f"{args.name}{modpkg.PRIVILEGED_SUFFIX}")
        if os.path.lexists(priv):
            os.unlink(priv)
        print(f"removed publisher {args.name}: its catalogs and packages no longer verify (installed modules stay; "
              "they just can't be updated from it)")
        return
    if not args.file:
        sys.exit("add FILE.pub [--name NAME]")
    with open(args.file, encoding="utf-8") as f:
        try:
            lines = modpkg.key_lines(f.read(16384))
        except modpkg.PackageError as e:
            sys.exit(f"{args.file}: {e}")
    if len(lines) != 1:
        sys.exit(f"{args.file}: one public key per publisher")
    name = args.name or re.sub(r"[^a-z0-9_-]+", "-", (" ".join(lines[0].split()[2:]) or
                                                      os.path.basename(args.file)[:-4]).lower()).strip("-")[:40]
    if not modpkg.PUBLISHER_RE.match(name or ""):
        sys.exit("--name NAME: a-z 0-9 _ -")
    fp = modpkg.key_fingerprint(lines[0])
    pubs, _ = modpkg.read_publishers(PUBLISHERS)
    other = modpkg.publisher_of(fp, pubs)
    if other:
        sys.exit(f"that key is trusted already as {other}")
    path = os.path.join(PUBLISHERS, f"{name}.pub")
    if os.path.exists(path):
        sys.exit(f"a publisher {name} exists: --name another, or remove it first")
    print(f"publisher {name}: {fp}")
    print("Compare this fingerprint with the one the publisher gives you (not from the same place as the key).")
    if not args.yes and (not sys.stdin.isatty() or input("trust it? [y/N] ").strip().lower() not in ("y", "yes")):
        sys.exit("not added")
    fd = os.open(path + ".new", os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o644)
    with os.fdopen(fd, "w") as f:
        f.write(lines[0] + "\n")
    os.chown(path + ".new", 0, 0)
    os.chmod(path + ".new", 0o644)
    os.replace(path + ".new", path)
    print(f"trusted: {path}")
    if args.allow_privileged:
        _allow_privileged(name)


def _allow_privileged(name):
    """Root's decision: modules from publisher NAME may ask for `delegate: true` / `connector.uses_credentials_of`
    (lab-module-helper refuses them otherwise). A root-owned 0644 marker next to the key."""
    from lab import modpkg
    path = os.path.join(PUBLISHERS, f"{name}{modpkg.PRIVILEGED_SUFFIX}")
    fd = os.open(path + ".new", os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o644)
    with os.fdopen(fd, "w") as f:
        f.write(f"# lab-admin publisher allow-privileged {name}: its modules may use delegate / "
                "connector.uses_credentials_of\n")
    os.chown(path + ".new", 0, 0)
    os.chmod(path + ".new", 0o644)
    os.replace(path + ".new", path)
    print(f"publisher {name} may ship privileged modules (delegate, uses_credentials_of): {path}")


def package_cmd(args, store):
    """Modules from catalogs through the module helper (the same path as Settings → ~/catalogs)."""
    from lab.modstore import ModuleHelperError, call_module_helper
    me = {"username": "lab-admin", "role": "owner"}

    def call(req, timeout=600):
        try:
            return call_module_helper({**req, "by": "lab-admin"}, timeout=timeout)
        except ModuleHelperError as e:
            store.audit(me, f"module-{req['op']}", req.get("id") or "_modules", str(req.get("id") or req.get("index") or ""),
                        "refused", str(e))
            sys.exit(f"package: {e}{' (signed by ' + e.extra['signer'] + ')' if e.extra.get('signer') else ''}")

    a = args.action or "status"
    if a in ("catalog-add", "catalog-remove"):
        from lab.errors import HTTPError
        from lab.modstore import CATALOGS_KEY, MAX_CATALOGS, catalogs, check_catalog_url
        try:
            url = check_catalog_url(args.id)
        except HTTPError as e:
            sys.exit(f"{a} URL: {e.msg}")
        have = catalogs(store)
        if a == "catalog-remove":
            left = [c for c in have if c["url"] != url]
            store.set_gateway_config(CATALOGS_KEY, left)
            store.audit(me, "module-catalog-remove", "_modules", url[:200], "ok" if len(left) < len(have) else "absent")
            print(f"removed {url}" if len(left) < len(have) else f"{url} was not in the list")
            return
        if any(c["url"] == url for c in have):
            sys.exit(f"{url} is in the list already")
        if len(have) >= MAX_CATALOGS:
            sys.exit(f"at most {MAX_CATALOGS} catalogs")
        out = call({"op": "catalog-check", "index": url}, timeout=120)
        c = out["catalog"]
        have.append({"url": url, "added": round(time.time()), "by": me["username"], "name": c.get("name") or "",
                     "publisher": c.get("publisher")})
        store.set_gateway_config(CATALOGS_KEY, have)
        store.audit(me, "module-catalog-add", "_modules", url[:200], "ok", f"publisher {c['publisher']['name']}")
        print(f"added {url}: {c.get('name') or ''} by {c['publisher']['name']} {c['publisher']['fingerprint']}")
        return
    if a == "status":
        st = call({"op": "status"})
        print(f"core {st.get('core')} · svelte {st.get('svelte')}{' · http:// LAN test servers allowed' if st.get('allow_http') else ''}")
        for p in st.get("publishers") or []:
            print(f"publisher {p['name']:<16} {' '.join(p['fingerprints'])}{' (core)' if p['core'] else ''}")
        from lab.modstore import catalogs
        for c in catalogs(store):
            print(f"listed    {c['url']}  (Settings → ~/catalogs)")
        for c in st.get("catalogs") or []:
            print(f"catalog   {c.get('url')}  {c.get('name') or ''}  {(c.get('publisher') or {}).get('name', '')} {c.get('error') or ''}")
        for m in st.get("installed") or []:
            print(f"installed {m['id']:<14} {m['version']:<10} previous {m.get('previous') or '-':<10} "
                  f"{(m.get('publisher') or {}).get('name', '')}{' connector' if m.get('connector') else ''}")
        return
    if a == "check":
        if not args.id:
            sys.exit("check URL")
        out = call({"op": "catalog-check", "index": args.id}, timeout=120)
        c = out["catalog"]
        store.audit(me, "module-check", "_modules", args.id[:200], "ok", f"publisher {c['publisher']['name']}")
        print(f"{c.get('name') or args.id}: publisher {c['publisher']['name']} {c['publisher']['fingerprint']}")
        for m in out["modules"]:
            print(f"  {m['id']:<14} {m['name'][:28]:<28} installed {m.get('installed') or '-':<8} "
                  f"{('→ ' + m['action'] + ' ' + m['available']) if m.get('available') else (m['versions'][0]['why'] if m['versions'] else '')}")
        return
    if not args.id:
        sys.exit(f"{a} ID")
    if a in ("install", "update"):
        if not args.version:
            sys.exit(f"{a} ID VERSION")
        req = {"op": "stage", "id": args.id, "version": args.version}
        if args.catalog:
            req["catalog"] = args.catalog
        s = call(req)["staged"]
        p = s["permissions"]
        print(f"{s['id']} {s['version']} ({s['kind']}, {s['category']}) from {s['publisher']['name']} {s['publisher']['fingerprint']}")
        print(f"  routes {len(p['routes'])} ({p['writes']} writes, {p['owner_only']} owner-only) · requires "
              f"{', '.join(r['id'] for r in p['requires']) or '-'} · connector {'yes' if p['connector'] else 'no'}"
              f"{' · uses credentials of ' + ', '.join(p['uses_credentials_of']) if p['uses_credentials_of'] else ''}")
        for t in p["network"]:
            print(f"  talks to: {t['label']}{' (e.g. ' + t['example'] + ')' if t['example'] else ''}")
        if not args.yes and (not sys.stdin.isatty() or input(f"{a} it? [y/N] ").strip().lower() not in ("y", "yes")):
            sys.exit("not installed")
        out = call({"op": a, "id": args.id, "version": args.version})
        store.audit(me, f"module-{a}", args.id, f"{args.id} {args.version}", "ok", json.dumps(out)[:500])
        print(f"{a}: {args.id} {out.get('version')}" + (f" (was {out['previous']})" if out.get("previous") else ""))
    elif a == "rollback":
        out = call({"op": "rollback", "id": args.id})
        store.audit(me, "module-rollback", args.id, args.id, "ok", f"{out.get('from')} → {out.get('version')}")
        print(f"{args.id}: back to {out['version']}")
    elif a == "remove":
        out = call({"op": "remove", "id": args.id, "keep_config": not args.drop_config})
        if args.drop_config and not out.get("bundled_remains"):
            store.drop_module(args.id)
        store.audit(me, "module-remove", args.id, args.id, "ok", json.dumps(out)[:500])
        print(f"removed {args.id} {out['version']}" + ("" if not out.get("bundled_remains") else f" (the bundled {out['bundled_remains']} is back)"))
    else:
        sys.exit(f"unknown: {a}")
    print("the gateway picks the change up with the next registry load (open tabs: within a minute)")


RUN_AS = os.environ.get("LAB_ADMIN_USER", "lab")


def _drop_to_lab():
    """Root → the gateway's user before the database is opened. Root opening /var/lib/lab/lab.sqlite3 would follow
    whatever lab put there: a symlinked -wal/-shm, a hot journal rolled back into a linked file, a chown of a planted
    link (what lab-admin did before 2026-11-15). As lab, sqlite can only reach lab's own files — and the files it makes
    belong to lab, so nothing needs to be given back afterwards."""
    if os.geteuid() != 0:
        return
    import pwd
    try:
        pw = pwd.getpwnam(RUN_AS)
    except KeyError:
        sys.exit(f"lab-admin: no user {RUN_AS}: refusing to open the database as root")
    if pw.pw_uid == 0:
        sys.exit("lab-admin: LAB_ADMIN_USER must not be root")
    os.initgroups(pw.pw_name, pw.pw_gid)   # group lab: /etc/lab, the master key, the update helper's socket
    os.setgid(pw.pw_gid)
    os.setuid(pw.pw_uid)
    os.umask(0o077)
    if os.geteuid() == 0 or os.getuid() == 0:
        sys.exit("lab-admin: could not drop root")


def _as_lab_child(fn):
    """fn() in a child that runs as lab (see _drop_to_lab); its JSON-able result comes back. Root stays root here."""
    if os.geteuid() != 0:
        return fn()
    r, w = os.pipe()
    pid = os.fork()
    if pid == 0:
        code = 1
        try:
            os.close(r)
            _drop_to_lab()
            data = json.dumps({"v": fn()}).encode()
            while data:
                data = data[os.write(w, data):]
            code = 0
        except SystemExit as e:
            print(e.code if isinstance(e.code, str) else "", file=sys.stderr)
        except BaseException as e:  # noqa: BLE001
            print(f"lab-admin: {e.__class__.__name__}: {e}", file=sys.stderr)
        finally:
            sys.stderr.flush()
            os._exit(code)
    os.close(w)
    with os.fdopen(r, "rb") as f:
        raw = f.read()
    _, status = os.waitpid(pid, 0)
    if os.waitstatus_to_exitcode(status):
        sys.exit(1)
    return json.loads(raw)["v"]


def _read_at(kv):
    """config KEY=@FILE: the file is read before dropping root (the owner may point at a root-only file)."""
    k, sep, v = kv.partition("=")
    if sep and v.startswith("@"):
        with open(v[1:], encoding="utf-8") as f:
            return f"{k}={f.read().strip()}"
    return kv


def main():
    p = argparse.ArgumentParser(prog="lab-admin", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--modules", help="modules dir (default: repo or LAB_MODULES)")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("new-module"); s.add_argument("id"); s.add_argument("--name"); s.add_argument("--backend")
    sub.add_parser("modules")
    sub.add_parser("keys")
    s = sub.add_parser("config"); s.add_argument("id"); s.add_argument("set", nargs="*"); s.add_argument("--clear", action="append")
    s = sub.add_parser("keygen"); s.add_argument("id"); s.add_argument("--force", action="store_true")
    sub.add_parser("users"); sub.add_parser("sessions")
    s = sub.add_parser("revoke"); s.add_argument("user")
    s = sub.add_parser("passwd"); s.add_argument("user"); s.add_argument("--role", choices=["owner", "admin", "guest"])
    s = sub.add_parser("user"); s.add_argument("user")
    g = s.add_mutually_exclusive_group(required=True)
    g.add_argument("--disable", action="store_true"); g.add_argument("--enable", action="store_true")
    g.add_argument("--reset-2fa", dest="reset_2fa", action="store_true")
    s = sub.add_parser("setup-link"); s.add_argument("--recover", action="store_true")
    s = sub.add_parser("approvals"); s.add_argument("action", nargs="?", choices=["list", "deny"], default="list")
    s.add_argument("id", nargs="?"); s.add_argument("--all", action="store_true")
    s = sub.add_parser("audit"); s.add_argument("-n", type=int, default=50)
    s = sub.add_parser("update"); s.add_argument("version", nargs="?")
    g = s.add_mutually_exclusive_group()
    g.add_argument("--check", action="store_true"); g.add_argument("--status", action="store_true")
    s.add_argument("--yes", "-y", action="store_true")
    s = sub.add_parser("publisher")
    s.add_argument("action", choices=["list", "add", "remove", "allow-privileged", "revoke-privileged"])
    s.add_argument("file", nargs="?"); s.add_argument("--name"); s.add_argument("--yes", "-y", action="store_true")
    s.add_argument("--allow-privileged", dest="allow_privileged", action="store_true")
    s = sub.add_parser("package")
    s.add_argument("action", nargs="?", choices=["status", "check", "install", "update", "rollback", "remove",
                                                     "catalog-add", "catalog-remove"])
    s.add_argument("id", nargs="?"); s.add_argument("version", nargs="?"); s.add_argument("--catalog")
    s.add_argument("--yes", "-y", action="store_true"); s.add_argument("--drop-config", action="store_true")
    args = p.parse_args()
    if args.cmd == "publisher":
        if args.action in ("remove", "allow-privileged", "revoke-privileged"):
            args.name = args.name or args.file
        return publisher_cmd(args)
    if args.cmd == "new-module":
        return new_module(args)
    if args.cmd == "keys":
        return keys(args)
    if args.cmd == "keygen":
        return keygen(args)
    if args.cmd == "setup-link":
        return setup_link(args)
    # everything below opens the database: as lab, never as root (see _drop_to_lab). What needs root (a password
    # typed at root's terminal, a root-only @FILE) is read first.
    if args.cmd == "config":
        args.set = [_read_at(kv) for kv in args.set or []]
    args.password = read_password() if args.cmd == "passwd" else None
    _drop_to_lab()
    if args.cmd == "modules":
        return modules(args)
    if args.cmd == "config":
        return config_cmd(args)
    store = Store(config.DB)
    {"users": users, "sessions": sessions, "revoke": revoke, "passwd": passwd, "approvals": approvals,
     "audit": audit, "user": user_cmd, "update": update_cmd, "package": package_cmd}[args.cmd](args, store)


if __name__ == "__main__":
    main()
