"""Installable module packages (step 16, docs/catalog.md): the rules the gateway, the root helper
(deploy/lab-module-helper, which imports this file from the live release) and the package build share.

A package `<id>-<version>.tar.gz` (deploy/make-module.sh) unpacks to `<id>-<version>/` holding
    package.json   {"format": 1, "id", "version", "kind", "min_core", "connector": bool,
                    "abi": {"svelte": "5.57.3", "imports": {specifier: [names]}}, "built", "commit"}
    manifest.json  the module's manifest (v2), same id and version
    ui/ui.js       its UI: ONE ES module importing only `svelte…` and `$lab/…` (resolved by the shell's import map)
    connector/     optional: the connector it runs (connectors/README.md), stdlib Python
    README.md, LICENSE   optional
    MANIFEST       sha256 of every other file
and is signed with `ssh-keygen -Y sign -n labradoor-module` by a publisher key. Installed copies live in
/var/lib/lab-modules/<id>/<version>/ (root-owned, read-only for the gateway); <id>/state.json names the live version.

The ABI: compiled Svelte code only runs on the runtime it was compiled against, and a bundle can only import what the
shell exports. The shell's build writes ui/dist/abi.json (ui/vite-abi.js); a package is compatible when it was built
with the same svelte major.minor and every name it imports exists there."""
import base64
import hashlib
import json
import os
import re

PKG_FORMAT = 1
NAMESPACE = "labradoor-module"            # ssh-keygen -Y sign -n labradoor-module
ID_RE = re.compile(r"^[a-z][a-z0-9-]{1,30}$")
PUBLISHER_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")
SEMVER_RE = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-((?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*)(?:\.(?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*))*))?$")
SPEC_RE = re.compile(r"^(svelte(/[a-z0-9/-]{1,60})?|\$lab/([a-z][a-z0-9-]{0,30}/)?[A-Za-z0-9_-][A-Za-z0-9._-]{0,59})$")  # $lab/x.js, $lab/arr/x.js
NAME_RE = re.compile(r"^(\*|[A-Za-z_$][\w$]{0,80})$")
KEY_LINE_RE = re.compile(r"^(ssh-ed25519|ecdsa-sha2-nistp(?:256|384|521)|ssh-rsa|sk-ssh-ed25519@openssh\.com) "
                         r"([A-Za-z0-9+/]+=*)(?: .*)?$")
TOP_ALLOWED = {"package.json", "manifest.json", "MANIFEST", "ui", "connector", "README.md", "LICENSE"}
INSTALLED_DIR = os.environ.get("LAB_INSTALLED_MODULES", "/var/lib/lab-modules")


class PackageError(ValueError):
    pass


# --- versions ------------------------------------------------------------------------------------------------------
def parse_version(v):
    m = SEMVER_RE.match(v) if isinstance(v, str) and len(v) <= 64 else None
    if not m:
        raise PackageError(f"not a version (semver): {str(v)[:64]!r}")
    pre = tuple(int(p) if p.isdigit() else p for p in m.group(4).split(".")) if m.group(4) else None
    return int(m.group(1)), int(m.group(2)), int(m.group(3)), pre


def is_version(v):
    try:
        parse_version(v)
        return True
    except PackageError:
        return False


def compare(a, b):
    """Semver precedence: -1, 0, 1 (1.0.0-rc.1 < 1.0.0)."""
    pa, pb = parse_version(a), parse_version(b)
    if pa[:3] != pb[:3]:
        return -1 if pa[:3] < pb[:3] else 1
    xa, xb = pa[3], pb[3]
    if xa == xb:
        return 0
    if xa is None or xb is None:
        return 1 if xa is None else -1
    for ia, ib in zip(xa, xb):
        if ia == ib:
            continue
        if isinstance(ia, int) != isinstance(ib, int):
            return -1 if isinstance(ia, int) else 1
        return -1 if ia < ib else 1
    return (len(xa) > len(xb)) - (len(xa) < len(xb))


def core_satisfies(core, min_core):
    """min_core check. A pre-release core (0.2.0-dev, a build from the repository) counts as its release."""
    if not min_core:
        return True
    if not core or not is_version(core):
        return False
    return compare(".".join(map(str, parse_version(core)[:3])), min_core) >= 0


# --- keys + signatures ---------------------------------------------------------------------------------------------
def _fp(blob):
    return "SHA256:" + base64.b64encode(hashlib.sha256(blob).digest()).decode().rstrip("=")


def key_fingerprint(line):
    """'ssh-ed25519 AAAA… comment' → 'SHA256:…' (as `ssh-keygen -l` prints it), or None."""
    m = KEY_LINE_RE.match((line or "").strip())
    if not m:
        return None
    try:
        return _fp(base64.b64decode(m.group(2), validate=True))
    except ValueError:
        return None


def key_lines(text):
    """The public key lines of a .pub file (comments and blank lines skipped). PackageError for anything else."""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip() and not ln.lstrip().startswith("#")]
    if not lines or not all(key_fingerprint(ln) for ln in lines):
        raise PackageError("expected OpenSSH public key line(s)")
    return lines


def _ssh_string(buf, i):
    if i + 4 > len(buf):
        raise PackageError("signature: truncated")
    n = int.from_bytes(buf[i:i + 4], "big")
    if i + 4 + n > len(buf):
        raise PackageError("signature: truncated")
    return buf[i + 4:i + 4 + n], i + 4 + n


def sshsig_info(sig):
    """An armored `ssh-keygen -Y sign` signature → (key fingerprint, namespace). Says WHO signed, not whether the
    signature is good: that is ssh-keygen -Y verify's job (the helper). PackageError when it isn't one."""
    try:
        text = sig.decode("ascii") if isinstance(sig, (bytes, bytearray)) else str(sig)
    except UnicodeDecodeError:
        raise PackageError("signature: not an SSH signature") from None
    m = re.search(r"-----BEGIN SSH SIGNATURE-----(.*?)-----END SSH SIGNATURE-----", text, re.S)
    if not m:
        raise PackageError("signature: not an SSH signature")
    try:
        blob = base64.b64decode("".join(m.group(1).split()), validate=True)
    except ValueError:
        raise PackageError("signature: bad base64") from None
    if blob[:6] != b"SSHSIG":
        raise PackageError("signature: not an SSH signature")
    i = 10                                    # magic + uint32 version
    pub, i = _ssh_string(blob, i)
    ns, i = _ssh_string(blob, i)
    return _fp(pub), ns.decode("utf-8", "replace")


def _relaxed():
    """Tests only: a non-root process may read publisher files it owns. Never for root."""
    return os.geteuid() != 0 and os.environ.get("LAB_PUBLISHERS_ANY_OWNER") == "1"


def read_publishers(directory):
    """Trusted publisher keys: {name: [key lines]} from DIR/<name>.pub. Only files root owns and only root can change
    count (with a directory only root can change): anything else is skipped and reported in `problems`."""
    pubs, problems = {}, []
    try:
        st = os.stat(directory)
        if (st.st_uid != 0 or st.st_mode & 0o022) and not _relaxed():
            return {}, [f"{directory}: must be owned by root and writable only by root"]
        names = sorted(os.listdir(directory))
    except FileNotFoundError:
        return {}, []
    except OSError as e:
        return {}, [f"{directory}: {e.__class__.__name__}"]
    for f in names:
        if not f.endswith(".pub"):
            continue
        name, path = f[:-4], os.path.join(directory, f)
        if not PUBLISHER_RE.match(name):
            problems.append(f"{f}: publisher names are a-z 0-9 _ - (skipped)")
            continue
        try:
            st = os.lstat(path)
            if not os.path.isfile(path) or os.path.islink(path):
                raise PackageError("not a regular file")
            if (st.st_uid != 0 or st.st_mode & 0o022) and not _relaxed():
                raise PackageError("must be owned by root and writable only by root")
            with open(path, encoding="utf-8") as fh:
                pubs[name] = key_lines(fh.read(16384))
        except (OSError, UnicodeDecodeError, PackageError) as e:
            problems.append(f"{f}: {e} (skipped)")
    return pubs, problems


PRIVILEGED_SUFFIX = ".privileged"


def read_privileged(directory):
    """Publishers root allowed to ship PRIVILEGED modules (`delegate: true`, `connector.uses_credentials_of`):
    DIR/<name>.privileged next to DIR/<name>.pub, written by `lab-admin publisher add … --allow-privileged` /
    `allow-privileged NAME`. Same rules as the keys: a regular file root owns and only root can change, in a directory
    only root can change; anything else does not count. → set of names."""
    out = set()
    try:
        st = os.stat(directory)
        if (st.st_uid != 0 or st.st_mode & 0o022) and not _relaxed():
            return out
        names = os.listdir(directory)
    except OSError:
        return out
    for f in names:
        if not f.endswith(PRIVILEGED_SUFFIX):
            continue
        name, path = f[:-len(PRIVILEGED_SUFFIX)], os.path.join(directory, f)
        try:
            st = os.lstat(path)
        except OSError:
            continue
        if PUBLISHER_RE.match(name) and not os.path.islink(path) and os.path.isfile(path) \
                and ((st.st_uid == 0 and not st.st_mode & 0o022) or _relaxed()):
            out.add(name)
    return out


def privileges(perms):
    """What a module asks for beyond its own routes (permissions() or a catalog's copy of it) → ["delegate", …]:
      delegate             its connector reads every module AS the person using it (the AI assistant);
      uses_credentials_of  its connector gets other modules' API credentials and calls their backends as that person.
    A package asking for either installs only from the core's release key or a publisher root allowed for it."""
    out = []
    if (perms or {}).get("delegate"):
        out.append("delegate")
    if (perms or {}).get("uses_credentials_of"):
        out.append("uses_credentials_of (" + ", ".join(perms["uses_credentials_of"]) + ")")
    return out


def publisher_of(fingerprint, pubs):
    """The publisher name whose key has this fingerprint, or None."""
    for name, lines in sorted(pubs.items()):
        if any(key_fingerprint(ln) == fingerprint for ln in lines):
            return name
    return None


def file_fingerprints(path):
    """Fingerprints of the keys in a .pub file (e.g. /etc/lab/release.pub: the core's own publisher); [] if unreadable."""
    try:
        with open(path, encoding="utf-8") as f:
            return [key_fingerprint(ln) for ln in key_lines(f.read(16384))]
    except (OSError, UnicodeDecodeError, PackageError):
        return []


# --- package.json + ABI --------------------------------------------------------------------------------------------
def check_package_json(p, mid=None, version=None):
    """Validate a package's package.json (as parsed). Returns it. PackageError for anything unexpected."""
    if not isinstance(p, dict):
        raise PackageError("package.json: an object")
    extra = set(p) - {"format", "id", "version", "kind", "min_core", "connector", "abi", "built", "commit", "name"}
    if extra:
        raise PackageError(f"package.json: unknown key(s) {sorted(extra)}")
    if p.get("format") != PKG_FORMAT:
        raise PackageError(f"package.json: format {p.get('format')!r} (this core reads format {PKG_FORMAT})")
    if not (isinstance(p.get("id"), str) and ID_RE.match(p["id"])) or (mid and p["id"] != mid):
        raise PackageError(f"package.json: id {p.get('id')!r} is not {mid}")
    if not is_version(p.get("version")) or (version and p["version"] != version):
        raise PackageError(f"package.json: version {p.get('version')!r} is not {version}")
    if p.get("min_core") is not None and not is_version(p["min_core"]):
        raise PackageError("package.json: min_core must be a version")
    if not isinstance(p.get("connector", False), bool) or p.get("kind") not in ("community", "private"):
        raise PackageError("package.json: connector true/false, kind community|private")
    for k in ("built", "commit", "name"):
        if k in p and not (isinstance(p[k], str) and len(p[k]) <= 200):
            raise PackageError(f"package.json: {k} is short text")
    abi = p.get("abi")
    if not (isinstance(abi, dict) and set(abi) <= {"svelte", "imports"} and is_version(abi.get("svelte"))
            and isinstance(abi.get("imports"), dict) and len(abi["imports"]) <= 200):
        raise PackageError("package.json: abi = {svelte: version, imports: {specifier: [names]}}")
    for spec, names in abi["imports"].items():
        if not (isinstance(spec, str) and SPEC_RE.match(spec) and ".." not in spec and isinstance(names, list)
                and len(names) <= 2000 and all(isinstance(n, str) and NAME_RE.match(n) for n in names)):
            raise PackageError(f"package.json: abi import {str(spec)[:60]!r}")
    return p


def load_abi(path):
    """The shell's ui/dist/abi.json → {"svelte": v, "specifiers": {spec: set(names)}}, or None."""
    try:
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
        return {"svelte": doc["svelte"],
                "specifiers": {s: set(v.get("exports") or []) for s, v in doc["specifiers"].items()}}
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None


def abi_problem(pkg_abi, shell_abi):
    """Why a package's UI can't run on this shell, or None."""
    if not shell_abi:
        return "this core has no module ABI (ui/dist/abi.json missing): installed modules can't be loaded"
    have, want = shell_abi["svelte"], (pkg_abi or {}).get("svelte")
    if not is_version(want) or parse_version(want)[:2] != parse_version(have)[:2]:
        return (f"built for svelte {want}, this core runs svelte {have}: a module needs the same major.minor "
                f"({'.'.join(str(x) for x in parse_version(have)[:2])}.x). The publisher rebuilds it against this core "
                "(docs/catalog.md, \"The svelte rule\")")
    for spec, names in sorted((pkg_abi.get("imports") or {}).items()):
        exports = shell_abi["specifiers"].get(spec)
        if exports is None:
            return f"imports {spec}, which this core does not provide"
        missing = sorted(set(names) - exports - {"*"})
        if missing:
            return f"imports {', '.join(missing[:5])} from {spec}, which this core does not export"
    return None


# --- what a module asks for (the install dialog, the catalog index) ------------------------------------------------
def permissions(m):
    """A validated manifest (registry.validate) → what installing it grants, for the owner to read before installing."""
    routes = []
    for r in m.get("_routes_base", m.get("routes", [])):
        routes.append({"method": r["method"], "path": r["path"], "label": r.get("label") or "",
                       "who": "owner" if r.get("min") == "owner" else
                              "owner (admins ask)" if r.get("owner_only") else r.get("min", "guest"),
                       "owner_only": bool(r.get("owner_only") or r.get("min") == "owner"),
                       "secret": bool(r.get("secret")), "write": r["method"] != "GET"})
    fields = m.get("config", {}).get("fields", [])
    be = m.get("_backend_tpl") or m.get("backend") or None
    conn = m.get("connector")
    targets = []
    if be:
        used = set(re.findall(r"\{([a-z][a-z0-9_]{0,40})\}", be.get("url", "")))
        for f in fields:
            if f["type"] == "url" or f["key"] in used:
                targets.append({"field": f["key"], "label": f.get("label") or f["key"],
                                "example": f.get("placeholder") or "", "type": f["type"]})
    return {
        "access": {"roles": list(m.get("access", {}).get("roles", [])), "groups": list(m.get("access", {}).get("groups", []))},
        "guest_safe": bool(m.get("guest_safe")),
        "delegate": bool(m.get("delegate")),
        "privileged": bool(m.get("delegate") or (conn or {}).get("uses_credentials_of")),
        "requires": [{"id": r["id"], "optional": bool(r.get("optional"))} for r in m.get("requires", [])],
        "uses_credentials_of": list((conn or {}).get("uses_credentials_of") or []),
        "connector": {"port": (conn or {}).get("port")} if conn else None,
        "backend": ({"url": be.get("url", ""), "auth": (be.get("auth") or {}).get("type"),
                     "own": not be.get("auth") and not conn} if be else None),
        "network": targets,
        "secrets": [f["key"] for f in fields if f["type"] == "secret"],
        "routes": routes,
        "writes": sum(1 for r in routes if r["write"]),
        "owner_only": sum(1 for r in routes if r["owner_only"]),
        "settings": len(m.get("settings") or []),
    }


# --- the installed tree (read side; the helper writes it) ----------------------------------------------------------
def installed_state(mid, base=None):
    """/var/lib/lab-modules/<id>/state.json → {"version", "previous", "publisher": {name, fingerprint}, …} or None."""
    base = base or INSTALLED_DIR
    if not ID_RE.match(mid or ""):
        return None
    try:
        with open(os.path.join(base, mid, "state.json"), encoding="utf-8") as f:
            st = json.load(f)
    except (OSError, ValueError):
        return None
    if not (isinstance(st, dict) and is_version(st.get("version"))):
        return None
    return st


def installed_ids(base=None):
    base = base or INSTALLED_DIR
    try:
        return sorted(d for d in os.listdir(base) if ID_RE.match(d) and installed_state(d, base))
    except OSError:
        return []
