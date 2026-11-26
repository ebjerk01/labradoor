"""Modules from catalogs (step 16): deploy/lab-module-helper, gateway/lab/modpkg.py, the registry merge, the gateway's
/api/modules/* routes and installed-module bundles, deploy/make-module.sh.

  * packages: a good one installs, updates, rolls back and is removed (with and without its config, its connector's
    drop-in, key, state and user); tampered (sha256, signature, MANIFEST), signed with the wrong / an unknown key, a
    catalog listing another publisher's package, path escapes, links, files outside the allowed layout, an ABI
    (svelte major.minor, imported names, specifiers) or min_core this core can't meet, a connector port in use, a
    bundled id (only the core's key + newer), an update from another publisher, a staged package changed before install;
  * the helper's command validation (fixed commands, exact keys, ids, versions, URL policy);
  * publisher keys: fingerprints as ssh-keygen prints them, the signer read from a signature, root-only files;
  * the registry: which of a bundled and an installed module is used, ABI-incompatible packages, the bundle URL;
  * the gateway: owner only, audited, the bundle route (who may load it, which version), the CSP hash of the import map,
    remove without keep_config drops the config;
  * make-module.sh: a real package that verifies, and a tampered one that does not.

Needs ssh-keygen (OpenSSH ≥ 8)."""
import base64
import copy
import hashlib
import http.client
import importlib.machinery
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "gateway"))
HAVE_KEYGEN = shutil.which("ssh-keygen") is not None
HAVE_NODE = shutil.which("node") is not None and os.path.isdir(os.path.join(ROOT, "node_modules", "vite"))


def load_helper():
    loader = importlib.machinery.SourceFileLoader("lab_module_helper", os.path.join(ROOT, "deploy", "lab-module-helper"))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    os.environ.setdefault("LAB_GATEWAY_CODE", os.path.join(ROOT, "gateway"))
    loader.exec_module(mod)
    return mod


M = load_helper()
from lab import modpkg  # noqa: E402
from lab.registry import Registry  # noqa: E402

TMP = None
FILES = {}
SVELTE = "5.57.3"
ABI = {"format": 1, "svelte": SVELTE, "specifiers": {
    "svelte": {"file": "/assets/abi/svelte.js", "exports": ["mount", "untrack"]},
    "svelte/internal/client": {"file": "/assets/abi/sic.js", "exports": ["append", "child", "from_html", "template"]},
    "$lab/sdk.js": {"file": "/assets/abi/sdk.js", "exports": ["act", "lazy"]},
    "$lab/Table.svelte": {"file": "/assets/abi/table.js", "exports": ["default"]}}}


class Files(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        data = FILES.get(self.path)
        if data is None:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def keygen(name):
    path = os.path.join(TMP, name)
    subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", name, "-f", path], check=True)
    return path


def sign(key, data, namespace="labradoor-module"):
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "f")
        with open(p, "wb") as f:
            f.write(data)
        subprocess.run(["ssh-keygen", "-q", "-Y", "sign", "-f", key, "-n", namespace, p], check=True)
        with open(p + ".sig", "rb") as f:
            return f.read()


def manifest(mid, version, connector_port=None, **extra):
    m = {"manifest": 2, "id": mid, "name": f"Test {mid}", "version": version, "kind": "community", "category": "tools",
         "description": "a test module",
         "config": {"fields": [{"key": "url", "type": "url", "label": "Server URL", "required": True,
                                "placeholder": "http://srv:1"}]},
         "routes": [{"method": "GET", "path": "/api/x"},
                    {"method": "POST", "path": "/api/y", "min": "admin", "label": "do y"},
                    {"method": "DELETE", "path": "/api/z/*", "owner_only": True, "label": "delete z"}]}
    if connector_port:
        m["backend"] = {"url": f"http://127.0.0.1:{connector_port}", "health": "/healthz"}
        m["connector"] = {}
    else:
        m["config"]["fields"].append({"key": "token", "type": "secret", "label": "Token", "required": True})
        m["backend"] = {"url": "{url}", "auth": {"type": "bearer", "secret": "token"}}
    m.update(extra)
    return m


def package(mid, version, man=None, pkg=None, files=None, mutate=None, members=None, connector=False):
    """A package tarball as bytes. mutate(tree) runs after the MANIFEST was written (tampering)."""
    man = man or manifest(mid, version, connector_port=8199 if connector else None)
    p = {"format": 1, "id": mid, "name": man["name"], "version": version, "kind": man["kind"], "connector": connector,
         "abi": {"svelte": SVELTE, "imports": {"svelte/internal/client": ["append", "child"], "$lab/sdk.js": ["act"]}},
         "built": "2026-11-15", "commit": "abc"}
    if man.get("min_core"):
        p["min_core"] = man["min_core"]
    p.update(pkg or {})
    with tempfile.TemporaryDirectory(dir=TMP) as d:
        top = os.path.join(d, f"{mid}-{version}")
        os.makedirs(os.path.join(top, "ui"))
        with open(os.path.join(top, "manifest.json"), "w") as f:
            json.dump(man, f)
        with open(os.path.join(top, "package.json"), "w") as f:
            json.dump(p, f)
        with open(os.path.join(top, "ui", "ui.js"), "w") as f:
            f.write(f"export default {{ id: {json.dumps(mid)} }};\n")
        if connector:
            os.makedirs(os.path.join(top, "connector"))
            with open(os.path.join(top, "connector", "connector.py"), "w") as f:
                f.write("print('hi')\n")
        for rel, data in (files or {}).items():
            os.makedirs(os.path.dirname(os.path.join(top, rel)) or top, exist_ok=True)
            with open(os.path.join(top, rel), "w") as f:
                f.write(data)
        M.U.write_manifest(top)
        if mutate:
            mutate(top)
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as t:
            t.add(top, arcname=f"{mid}-{version}")
            for info, data in members or []:
                t.addfile(info, io.BytesIO(data) if data is not None else None)
        return buf.getvalue()


@unittest.skipUnless(HAVE_KEYGEN, "ssh-keygen missing")
class HelperBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        global TMP
        TMP = tempfile.mkdtemp(prefix="labmod-")
        cls.pubkey = keygen("publisher-a")    # trusted publisher "alpha"
        cls.core = keygen("core")             # the core's release key, trusted as "labradoor"
        cls.stranger = keygen("stranger")     # nobody trusts it
        cls.srv = HTTPServer(("127.0.0.1", 0), Files)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.srv.server_address[1]}"
        cls.saved = {k: getattr(M, k) for k in ("STATE", "INSTALLED", "PUBLISHERS", "RELEASE_PUB", "UNIT_DIR", "KEYS_DIR",
                                                  "CONN_STATE", "SYSTEMCTL", "USERDEL", "LIVE", "ABI_FILE", "BUNDLED")}
        cls.env = {k: os.environ.get(k) for k in ("LAB_UPDATE_ALLOW_HTTP", "LAB_PUBLISHERS_ANY_OWNER")}
        os.environ["LAB_UPDATE_ALLOW_HTTP"] = "1"
        os.environ["LAB_PUBLISHERS_ANY_OWNER"] = "1"

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        for k, v in cls.saved.items():
            setattr(M, k, v)
        for k, v in cls.env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(TMP, ignore_errors=True)

    def setUp(self):
        FILES.clear()
        self.dir = tempfile.mkdtemp(dir=TMP)
        j = lambda *p: os.path.join(self.dir, *p)  # noqa: E731
        for d in ("pubs", "live", "bundled", "units", "keys", "cstate"):
            os.makedirs(j(d))
        os.chmod(j("pubs"), 0o755)
        shutil.copy(self.pubkey + ".pub", j("pubs", "alpha.pub"))
        shutil.copy(self.core + ".pub", j("pubs", "labradoor.pub"))
        shutil.copy(self.core + ".pub", j("release.pub"))
        with open(j("live", "VERSION"), "w") as f:
            f.write("0.2.0\n")
        with open(j("abi.json"), "w") as f:
            json.dump(ABI, f)
        M.STATE, M.INSTALLED, M.PUBLISHERS, M.RELEASE_PUB = j("state"), j("installed"), j("pubs"), j("release.pub")
        M.UNIT_DIR, M.KEYS_DIR, M.CONN_STATE, M.LIVE = j("units"), j("keys"), j("cstate"), j("live")
        M.ABI_FILE, M.BUNDLED = j("abi.json"), j("bundled")
        self.sysctl = j("systemctl.log")
        script = j("fake-systemctl")
        with open(script, "w") as f:
            f.write(f"#!/bin/sh\necho \"$@\" >> {self.sysctl}\n")
        os.chmod(script, 0o755)
        M.SYSTEMCTL, M.USERDEL = script, "/bin/true"

    # --- helpers ---------------------------------------------------------------------------------------------------
    def publish(self, entries, key=None, path="/c/catalog.json", name="Test catalog", sig_key=None):
        """entries: [(mid, version, tarball bytes, package signing key or None = the catalog's key, extra entry keys)]"""
        key = key or self.pubkey
        mods = {}
        folder = path.rsplit("/", 1)[0]
        for mid, version, tar, pkey, extra in entries:
            fn = f"{mid}-{version}.tar.gz"
            FILES[f"{folder}/{fn}"] = tar
            FILES[f"{folder}/{fn}.sig"] = sign(pkey or key, tar)
            e = mods.setdefault(mid, {"id": mid, "name": f"Test {mid}", "kind": "community", "category": "tools",
                                      "versions": []})
            e["versions"].append({"version": version, "sha256": hashlib.sha256(tar).hexdigest(), "url": fn,
                                  "sig": fn + ".sig", "min_core": None, "svelte": SVELTE, **(extra or {})})
        doc = json.dumps({"format": 1, "product": "labradoor-modules", "name": name,
                          "modules": list(mods.values())}).encode()
        FILES[path] = doc
        FILES[path + ".sig"] = sign(sig_key or key, doc)
        return self.base + path

    def ok(self, req):
        return M.handle(req)

    def refused(self, req, text):
        with self.assertRaises(M.Fail) as cm:
            M.handle(req)
        self.assertIn(text, str(cm.exception))
        return cm.exception

    def stage_install(self, url, mid, version, op="install"):
        self.ok({"op": "catalog-check", "index": url})
        st = self.ok({"op": "stage", "id": mid, "version": version, "catalog": url})
        self.ok({"op": op, "id": mid, "version": version})
        return st


class Requests(HelperBase):
    def test_fixed_commands_only(self):
        for req, text in [({"op": "exec"}, "op is one of"), ("x", "JSON object"),
                          ({"op": "status", "id": "x"}, "status takes nothing"),
                          ({"op": "install", "id": "dns"}, "install takes"),
                          ({"op": "install", "id": "../x", "version": "1.0.0"}, "id: a module id"),
                          ({"op": "install", "id": "dns", "version": "1.0"}, "version"),
                          ({"op": "remove", "id": "dns", "keep_config": "yes"}, "keep_config"),
                          ({"op": "stage", "id": "dns", "version": "1.0.0", "catalog": "file:///etc/x"}, "not allowed"),
                          ({"op": "status", "by": "x\ny"}, "by:")]:
            with self.assertRaises(M.Fail, msg=req) as cm:
                M.check(req)
            self.assertIn(text, str(cm.exception))

    def test_url_policy(self):
        os.environ.pop("LAB_UPDATE_ALLOW_HTTP")
        try:
            self.refused({"op": "catalog-check", "index": self.base + "/c/catalog.json"}, "only https://")
            self.refused({"op": "catalog-check", "index": "http://8.8.8.8/c.json"}, "only https://")
        finally:
            os.environ["LAB_UPDATE_ALLOW_HTTP"] = "1"
        self.refused({"op": "catalog-check", "index": "http://user:pw@127.0.0.1/c.json"}, "not allowed")

    def test_status(self):
        st = self.ok({"op": "status"})
        self.assertEqual({p["name"] for p in st["publishers"]}, {"alpha", "labradoor"})
        self.assertTrue(next(p for p in st["publishers"] if p["name"] == "labradoor")["core"])
        self.assertEqual((st["core"], st["svelte"], st["installed"]), ("0.2.0", SVELTE, []))


class Signatures(HelperBase):
    def test_fingerprints_match_ssh_keygen(self):
        out = subprocess.run(["ssh-keygen", "-l", "-f", self.pubkey + ".pub"], capture_output=True, text=True).stdout
        with open(self.pubkey + ".pub") as f:
            fp = modpkg.key_fingerprint(f.read())
        self.assertEqual(fp, out.split()[1])
        self.assertEqual(modpkg.sshsig_info(sign(self.pubkey, b"x")), (fp, "labradoor-module"))
        self.assertEqual(modpkg.sshsig_info(sign(self.pubkey, b"x", "labradoor-release"))[1], "labradoor-release")
        with self.assertRaises(modpkg.PackageError):
            modpkg.sshsig_info(b"-----BEGIN SSH SIGNATURE-----\nAAAA\n-----END SSH SIGNATURE-----")

    def test_unknown_publisher(self):
        url = self.publish([("solo", "1.0.0", package("solo", "1.0.0"), None, None)], key=self.stranger)
        e = self.refused({"op": "catalog-check", "index": url}, "unknown publisher")
        with open(self.stranger + ".pub") as f:
            self.assertEqual(e.extra["signer"], modpkg.key_fingerprint(f.read()))

    def test_wrong_namespace(self):
        url = self.publish([("solo", "1.0.0", package("solo", "1.0.0"), None, None)])
        FILES["/c/catalog.json.sig"] = sign(self.pubkey, FILES["/c/catalog.json"], "labradoor-release")
        self.refused({"op": "catalog-check", "index": url}, "not for Labradoor modules")

    def test_tampered_catalog(self):
        url = self.publish([("solo", "1.0.0", package("solo", "1.0.0"), None, None)])
        FILES["/c/catalog.json"] = FILES["/c/catalog.json"].replace(b"Test catalog", b"Evil catalog")
        self.refused({"op": "catalog-check", "index": url}, "does NOT verify")

    def test_publisher_files_must_be_roots(self):
        if os.geteuid() == 0:
            self.skipTest("as root every file is root's")
        os.environ.pop("LAB_PUBLISHERS_ANY_OWNER")
        try:
            pubs, problems = modpkg.read_publishers(M.PUBLISHERS)
        finally:
            os.environ["LAB_PUBLISHERS_ANY_OWNER"] = "1"
        self.assertEqual(pubs, {})
        self.assertTrue(problems and "root" in problems[0])

    def test_removed_publisher_invalidates_checked_catalog(self):
        url = self.publish([("solo", "1.0.0", package("solo", "1.0.0"), None, None)])
        self.ok({"op": "catalog-check", "index": url})
        os.unlink(os.path.join(M.PUBLISHERS, "alpha.pub"))
        self.refused({"op": "stage", "id": "solo", "version": "1.0.0"}, "no checked catalog")


class Packages(HelperBase):
    def test_install_update_rollback_remove(self):
        url = self.publish([("tool", "1.0.0", package("tool", "1.0.0", connector=True), None, None),
                            ("tool", "1.1.0", package("tool", "1.1.0", connector=True), None, None)])
        chk = self.ok({"op": "catalog-check", "index": url})
        mod = chk["modules"][0]
        self.assertEqual((mod["available"], mod["action"]), ("1.1.0", "install"))
        self.assertEqual(chk["catalog"]["publisher"]["name"], "alpha")
        st = self.ok({"op": "stage", "id": "tool", "version": "1.0.0"})["staged"]
        p = st["permissions"]
        self.assertEqual(p["connector"], {"port": 8199})
        self.assertEqual((p["writes"], p["owner_only"]), (2, 1))
        self.assertEqual(p["network"][0]["label"], "Server URL")
        out = self.ok({"op": "install", "id": "tool", "version": "1.0.0", "by": "boss"})
        self.assertEqual((out["installed"], out["version"], out["connector"]), ("tool", "1.0.0", True))
        tree = os.path.join(M.INSTALLED, "tool", "1.0.0")
        self.assertTrue(os.path.isfile(os.path.join(tree, "ui", "ui.js")))
        self.assertEqual(oct(os.stat(tree).st_mode & 0o777), "0o755")
        with open(M.dropin_path("tool")) as f:
            self.assertIn(f"WorkingDirectory={M.INSTALLED}/tool/1.0.0/connector", f.read())
        self.refused({"op": "install", "id": "tool", "version": "1.0.0"}, "not staged")
        self.ok({"op": "stage", "id": "tool", "version": "1.1.0"})
        self.refused({"op": "install", "id": "tool", "version": "1.1.0"}, "installed already")
        out = self.ok({"op": "update", "id": "tool", "version": "1.1.0"})
        self.assertEqual((out["version"], out["previous"]), ("1.1.0", "1.0.0"))
        with open(M.dropin_path("tool")) as f:
            self.assertIn("/tool/1.1.0/connector", f.read())
        with open(self.sysctl) as f:
            self.assertIn("try-restart lab-connector@tool.service", f.read())
        self.refused({"op": "stage", "id": "tool", "version": "1.0.0"}, "not newer")
        out = self.ok({"op": "rollback", "id": "tool"})
        self.assertEqual((out["version"], out["from"]), ("1.0.0", "1.1.0"))
        self.assertEqual(modpkg.installed_state("tool", M.INSTALLED)["previous"], "1.1.0")
        # remove without its config: key, connector state (a planted link inside is removed, never followed), user
        victim = os.path.join(self.dir, "victim")
        with open(victim, "w") as f:
            f.write("keep me")
        os.makedirs(os.path.join(M.CONN_STATE, "tool"))
        os.symlink(victim, os.path.join(M.CONN_STATE, "tool", "link"))
        with open(os.path.join(M.KEYS_DIR, "tool.key"), "w") as f:
            f.write("k")
        out = self.ok({"op": "remove", "id": "tool", "keep_config": False})
        self.assertEqual(out["also_removed"][:2], ["key", "connector state"])
        self.assertFalse(os.path.exists(os.path.join(M.INSTALLED, "tool")))
        self.assertFalse(os.path.exists(M.dropin_path("tool")))
        with open(victim) as f:
            self.assertEqual(f.read(), "keep me")
        self.refused({"op": "rollback", "id": "tool"}, "not installed")

    def test_remove_keeps_config(self):
        url = self.publish([("tool", "1.0.0", package("tool", "1.0.0"), None, None)])
        self.stage_install(url, "tool", "1.0.0")
        with open(os.path.join(M.KEYS_DIR, "tool.key"), "w") as f:
            f.write("k")
        out = self.ok({"op": "remove", "id": "tool", "keep_config": True})
        self.assertEqual(out["also_removed"], [])
        self.assertTrue(os.path.exists(os.path.join(M.KEYS_DIR, "tool.key")))

    def test_sha256_mismatch(self):
        url = self.publish([("tool", "1.0.0", package("tool", "1.0.0"), None, None)])
        self.ok({"op": "catalog-check", "index": url})
        FILES["/c/tool-1.0.0.tar.gz"] = package("tool", "1.0.0", files={"README.md": "changed"})
        self.refused({"op": "stage", "id": "tool", "version": "1.0.0"}, "sha256 mismatch")
        self.assertFalse(os.path.exists(M.stage_dir("tool", "1.0.0")))

    def test_package_signature(self):
        tar = package("tool", "1.0.0")
        url = self.publish([("tool", "1.0.0", tar, self.stranger, None)])
        self.ok({"op": "catalog-check", "index": url})
        self.refused({"op": "stage", "id": "tool", "version": "1.0.0"}, "unknown publisher")
        url = self.publish([("tool", "1.0.0", tar, self.core, None)])     # trusted, but not the catalog's publisher
        self.ok({"op": "catalog-check", "index": url})
        self.refused({"op": "stage", "id": "tool", "version": "1.0.0"}, "only list its own publisher's packages")
        url = self.publish([("tool", "1.0.0", tar, None, None)])
        FILES["/c/tool-1.0.0.tar.gz.sig"] = sign(self.pubkey, tar + b"x")   # a good signature of other bytes
        self.ok({"op": "catalog-check", "index": url})
        self.refused({"op": "stage", "id": "tool", "version": "1.0.0"}, "does NOT verify")

    def test_manifest_and_layout(self):
        def change(top):
            with open(os.path.join(top, "ui", "ui.js"), "a") as f:
                f.write("fetch('/api/users', {method: 'POST'});\n")

        def extra(top):
            with open(os.path.join(top, "connector.sh"), "w") as f:
                f.write("x")
        for kw, text in [({"mutate": change}, "MANIFEST mismatch: ui/ui.js"),
                         ({"mutate": extra}, "files not in the MANIFEST: connector.sh"),
                         ({"files": {"run.sh": "x"}}, "not allowed in a module package: run.sh"),
                         ({"files": {"ui/other.js": "x"}}, "not allowed in a module package: ui/other.js"),
                         ({"pkg": {"id": "other"}}, "package.json: id"),
                         ({"pkg": {"evil": 1}}, "unknown key")]:
            with self.subTest(text):
                url = self.publish([("tool", "1.0.0", package("tool", "1.0.0", **kw), None, None)])
                self.ok({"op": "catalog-check", "index": url})
                self.refused({"op": "stage", "id": "tool", "version": "1.0.0"}, text)

    def test_path_escape_and_links(self):
        def member(name, kind=tarfile.REGTYPE, data=b"x", link=""):
            i = tarfile.TarInfo(name)
            i.type, i.size, i.linkname = kind, len(data) if kind == tarfile.REGTYPE else 0, link
            return i, data if kind == tarfile.REGTYPE else None
        for members, text in [([member("tool-1.0.0/../escape")], "outside"),
                              ([member("/etc/cron.d/x")], "outside"),
                              ([member("other/x")], "outside"),
                              ([member("tool-1.0.0/ui/a b")], "strange name"),
                              ([member("tool-1.0.0/link", tarfile.SYMTYPE, link="/etc/shadow")], "link or special"),
                              ([member("tool-1.0.0/hard", tarfile.LNKTYPE, link="tool-1.0.0/manifest.json")], "link or special"),
                              ([member("tool-1.0.0/fifo", tarfile.FIFOTYPE)], "link or special")]:
            with self.subTest(text=text, name=members[0][0].name):
                url = self.publish([("tool", "1.0.0", package("tool", "1.0.0", members=members), None, None)])
                self.ok({"op": "catalog-check", "index": url})
                self.refused({"op": "stage", "id": "tool", "version": "1.0.0"}, text)

    def test_abi_and_min_core(self):
        for kw, text in [({"pkg": {"abi": {"svelte": "5.12.0", "imports": {}}}}, "needs the same major.minor"),
                         ({"pkg": {"abi": {"svelte": "4.2.0", "imports": {}}}}, "built for svelte 4.2.0"),
                         ({"pkg": {"abi": {"svelte": SVELTE, "imports": {"svelte/internal/client": ["nope"]}}}},
                          "imports nope from svelte/internal/client"),
                         ({"pkg": {"abi": {"svelte": SVELTE, "imports": {"$lab/lab.svelte.js": ["lab"]}}}},
                          "imports $lab/lab.svelte.js, which this core does not provide"),
                         ({"man": manifest("tool", "1.0.0", min_core="9.0.0")}, "needs core 9.0.0")]:
            with self.subTest(text):
                url = self.publish([("tool", "1.0.0", package("tool", "1.0.0", **kw), None, None)])
                self.ok({"op": "catalog-check", "index": url})
                self.refused({"op": "stage", "id": "tool", "version": "1.0.0"}, text)
        # the catalog already says so (before any download)
        url = self.publish([("tool", "1.0.0", package("tool", "1.0.0"), None, {"min_core": "9.0.0"})])
        v = self.ok({"op": "catalog-check", "index": url})["modules"][0]["versions"][0]
        self.assertEqual((v["ok"], v["why"]), (False, "needs core 9.0.0 (this is 0.2.0)"))

    def test_privileged_needs_roots_allowance(self):
        """Owner decision 2026-11-16 (#10): delegate / uses_credentials_of only from the core's release key or from a
        publisher root allowed for it (publishers.d/<name>.privileged), decided by this helper — not the gateway."""
        man = manifest("tool", "1.0.0", connector_port=8199, delegate=True)
        tar = package("tool", "1.0.0", man=man, connector=True)
        perms = modpkg.permissions(man)
        self.assertTrue(perms["privileged"])
        url = self.publish([("tool", "1.0.0", tar, None, {"permissions": perms})])
        v = self.ok({"op": "catalog-check", "index": url})["modules"][0]["versions"][0]
        self.assertFalse(v["ok"])
        self.assertIn("lab-admin publisher allow-privileged alpha", v["why"])
        self.refused({"op": "stage", "id": "tool", "version": "1.0.0"}, "not allowed privileged modules")
        # a marker root does not own (a test run is not root: LAB_PUBLISHERS_ANY_OWNER relaxes ownership) — a link never
        os.symlink("/etc/hostname", os.path.join(M.PUBLISHERS, "alpha.privileged"))
        self.refused({"op": "stage", "id": "tool", "version": "1.0.0"}, "not allowed privileged modules")
        os.unlink(os.path.join(M.PUBLISHERS, "alpha.privileged"))
        with open(os.path.join(M.PUBLISHERS, "alpha.privileged"), "w") as f:
            f.write("allowed by root\n")
        self.assertTrue(self.ok({"op": "catalog-check", "index": url})["modules"][0]["versions"][0]["ok"])
        st = self.ok({"op": "stage", "id": "tool", "version": "1.0.0"})["staged"]
        self.assertEqual(st["privileged"], {"asks": ["delegate"], "allowed_because": "root allowed publisher alpha"})
        self.ok({"op": "install", "id": "tool", "version": "1.0.0"})
        self.assertTrue(next(p for p in self.ok({"op": "status"})["publishers"] if p["name"] == "alpha")["privileged"])
        # revoked: the installed version stays, but nothing of it is (re)installed — a rollback/update re-checks
        os.unlink(os.path.join(M.PUBLISHERS, "alpha.privileged"))
        url2 = self.publish([("tool", "1.1.0", package("tool", "1.1.0", man=manifest("tool", "1.1.0", connector_port=8199,
                                                                                    delegate=True), connector=True),
                              None, None)], path="/c2/catalog.json")
        self.ok({"op": "catalog-check", "index": url2})
        self.refused({"op": "stage", "id": "tool", "version": "1.1.0", "catalog": url2}, "not allowed privileged")
        # the core's release key needs no allowance
        url3 = self.publish([("tool2", "1.0.0", package("tool2", "1.0.0", man=manifest("tool2", "1.0.0", connector_port=8198,
                                                                                      delegate=True), connector=True),
                              None, None)], key=self.core, path="/k/catalog.json")
        self.ok({"op": "catalog-check", "index": url3})
        st = self.ok({"op": "stage", "id": "tool2", "version": "1.0.0"})["staged"]
        self.assertEqual(st["privileged"]["allowed_because"], "core release key")

    def test_pre_release_core_counts_as_its_release(self):
        self.assertTrue(modpkg.core_satisfies("0.2.0-dev", "0.2.0"))
        self.assertFalse(modpkg.core_satisfies("0.1.9", "0.2.0"))
        self.assertFalse(modpkg.core_satisfies(None, "0.1.0"))
        self.assertTrue(modpkg.core_satisfies(None, None))

    def test_bundled_id(self):
        os.makedirs(os.path.join(M.BUNDLED, "bund"))
        with open(os.path.join(M.BUNDLED, "bund", "manifest.json"), "w") as f:
            json.dump(manifest("bund", "1.0.0"), f)
        url = self.publish([("bund", "1.1.0", package("bund", "1.1.0"), None, None)])
        self.ok({"op": "catalog-check", "index": url})
        self.refused({"op": "stage", "id": "bund", "version": "1.1.0"}, "ships with the core")
        url = self.publish([("bund", "0.9.0", package("bund", "0.9.0"), None, None),
                            ("bund", "1.1.0", package("bund", "1.1.0"), None, None)], key=self.core, path="/k/catalog.json")
        mods = self.ok({"op": "catalog-check", "index": url})["modules"]
        self.assertEqual([(v["version"], v["ok"]) for v in mods[0]["versions"]], [("1.1.0", True), ("0.9.0", False)])
        self.refused({"op": "stage", "id": "bund", "version": "0.9.0", "catalog": url}, "ships with the core")
        self.refused({"op": "stage", "id": "bund", "version": "1.1.0"}, "several catalogs")
        self.stage_install(url, "bund", "1.1.0")
        out = self.ok({"op": "remove", "id": "bund", "keep_config": False})
        self.assertEqual((out["bundled_remains"], out["also_removed"]), ("1.0.0", []))   # the bundled one keeps its key

    def test_update_from_another_publisher(self):
        url = self.publish([("tool", "1.0.0", package("tool", "1.0.0"), None, None)])
        self.stage_install(url, "tool", "1.0.0")
        url2 = self.publish([("tool", "2.0.0", package("tool", "2.0.0"), None, None)], key=self.core, path="/k/catalog.json")
        self.ok({"op": "catalog-check", "index": url2})
        self.refused({"op": "stage", "id": "tool", "version": "2.0.0"}, "same publisher")

    def test_connector_port_in_use(self):
        os.makedirs(os.path.join(M.BUNDLED, "other"))
        with open(os.path.join(M.BUNDLED, "other", "manifest.json"), "w") as f:
            json.dump(manifest("other", "1.0.0", connector_port=8199), f)
        url = self.publish([("tool", "1.0.0", package("tool", "1.0.0", connector=True), None, None)])
        self.ok({"op": "catalog-check", "index": url})
        self.refused({"op": "stage", "id": "tool", "version": "1.0.0"}, "port 8199 is used by other")

    def test_connector_must_match_manifest(self):
        url = self.publish([("tool", "1.0.0", package("tool", "1.0.0", files={"connector/connector.py": "x"}), None, None)])
        self.ok({"op": "catalog-check", "index": url})
        self.refused({"op": "stage", "id": "tool", "version": "1.0.0"}, "must agree")

    def test_staged_package_changed_before_install(self):
        url = self.publish([("tool", "1.0.0", package("tool", "1.0.0"), None, None)])
        self.ok({"op": "catalog-check", "index": url})
        self.ok({"op": "stage", "id": "tool", "version": "1.0.0"})
        ui = os.path.join(M.stage_dir("tool", "1.0.0"), "tree", "tool-1.0.0", "ui", "ui.js")
        with open(ui, "a") as f:
            f.write("// changed\n")
        self.refused({"op": "install", "id": "tool", "version": "1.0.0"}, "MANIFEST mismatch")
        with open(os.path.join(M.stage_dir("tool", "1.0.0"), "package.tar.gz"), "ab") as f:
            f.write(b"x")
        self.refused({"op": "install", "id": "tool", "version": "1.0.0"}, "sha256 changed")
        self.assertFalse(os.path.exists(os.path.join(M.INSTALLED, "tool")))

    def test_installed_tree_is_checked_on_rollback(self):
        url = self.publish([("tool", "1.0.0", package("tool", "1.0.0"), None, None),
                            ("tool", "1.0.1", package("tool", "1.0.1"), None, None)])
        self.stage_install(url, "tool", "1.0.0")
        self.ok({"op": "stage", "id": "tool", "version": "1.0.1"})
        self.ok({"op": "update", "id": "tool", "version": "1.0.1"})
        with open(os.path.join(M.INSTALLED, "tool", "1.0.0", "ui", "ui.js"), "a") as f:
            f.write("// changed on disk\n")
        self.refused({"op": "rollback", "id": "tool"}, "MANIFEST mismatch")
        self.assertEqual(modpkg.installed_state("tool", M.INSTALLED)["version"], "1.0.1")


class RegistryMerge(HelperBase):
    """The gateway's side of the rules: which module is used, and why not."""

    def reg(self):
        return Registry(M.BUNDLED, installed_dir=M.INSTALLED, abi_file=M.ABI_FILE, release_pub=M.RELEASE_PUB)

    def bundled(self, mid, version):
        os.makedirs(os.path.join(M.BUNDLED, mid), exist_ok=True)
        with open(os.path.join(M.BUNDLED, mid, "manifest.json"), "w") as f:
            json.dump(manifest(mid, version), f)

    def test_installed_module_is_loaded(self):
        url = self.publish([("tool", "1.0.0", package("tool", "1.0.0"), None, None)])
        self.stage_install(url, "tool", "1.0.0")
        r = self.reg()
        self.assertFalse(r.installed_changed())
        m = r.get("tool")
        self.assertEqual((m["_source"], m["_installed"]["bundle"]), ("installed", "/modules/tool/1.0.0/ui.js"))
        self.ok({"op": "remove", "id": "tool", "keep_config": True})   # e.g. lab-admin package remove: the gateway notices
        self.assertTrue(r.installed_changed())
        r.load()
        self.assertIsNone(r.get("tool"))
        self.stage_install(url, "tool", "1.0.0")
        r = self.reg()
        self.assertEqual(r.bundle_file("tool", "1.0.0"), os.path.realpath(os.path.join(M.INSTALLED, "tool/1.0.0/ui/ui.js")))
        self.assertIsNone(r.bundle_file("tool", "0.9.0"))
        r.apply(config={"tool": {"url": "http://x", "token": "<set>"}})
        vis = r.visible({"username": "o", "role": "owner"})
        self.assertEqual([(v["id"], v["source"], v["bundle"]) for v in vis], [("tool", "installed", "/modules/tool/1.0.0/ui.js")])

    def test_bundled_vs_installed(self):
        self.bundled("bund", "1.0.0")
        url = self.publish([("bund", "1.1.0", package("bund", "1.1.0"), None, None)], key=self.core)
        self.stage_install(url, "bund", "1.1.0")
        self.assertEqual(self.reg().get("bund")["version"], "1.1.0")      # newer + the core's key
        self.bundled("bund", "1.2.0")                                       # a core update ships a newer one
        r = self.reg()
        self.assertEqual((r.get("bund")["version"], r.get("bund")["_source"]), ("1.2.0", "bundled"))
        self.assertIn("bundled 1.2.0 is used", r.shadowed["bund"])
        # an installed copy signed by someone else never replaces a bundled module (written by hand: the helper refuses)
        st = modpkg.installed_state("bund", M.INSTALLED)
        st["publisher"] = {"name": "alpha", "fingerprint": "SHA256:other"}
        self.bundled("bund", "1.0.0")
        with open(os.path.join(M.INSTALLED, "bund", "state.json"), "w") as f:
            json.dump(st, f)
        r = self.reg()
        self.assertEqual(r.get("bund")["_source"], "bundled")
        self.assertIn("signed with the core's release key", r.shadowed["bund"])

    def test_abi_incompatible_after_a_core_update(self):
        url = self.publish([("tool", "1.0.0", package("tool", "1.0.0"), None, None)])
        self.stage_install(url, "tool", "1.0.0")
        with open(M.ABI_FILE, "w") as f:
            json.dump({**ABI, "svelte": "5.80.0"}, f)
        r = self.reg()
        self.assertIsNone(r.get("tool"))
        self.assertIn("built for svelte", r.errors["tool@1.0.0"])
        os.unlink(M.ABI_FILE)
        self.assertIn("no module ABI", self.reg().errors["tool@1.0.0"])


@unittest.skipUnless(HAVE_KEYGEN, "ssh-keygen missing")
class GatewayRoutes(unittest.TestCase):
    """Owner only; audited; the helper's refusals passed on with the signer; the bundle route; the page's CSP."""

    @classmethod
    def setUpClass(cls):
        from lab import config, server
        cls.config, cls.server = config, server
        cls.tmp = tempfile.mkdtemp(prefix="labmodgw-")
        j = lambda *p: os.path.join(cls.tmp, *p)  # noqa: E731
        for d in ("modules", "keys", "dist", "installed/tool/1.0.0/ui"):
            os.makedirs(j(d))
        with open(j("dist", "index.html"), "w") as f:
            f.write('<!doctype html><head><script type="importmap">{"imports":{"svelte":"/assets/abi/s.js"}}</script>'
                    '<script type="module" src="/assets/index.js"></script></head>')
        with open(j("dist", "abi.json"), "w") as f:
            json.dump(ABI, f)
        man = manifest("tool", "1.0.0")
        with open(j("installed/tool/1.0.0/manifest.json"), "w") as f:
            json.dump(man, f)
        with open(j("installed/tool/1.0.0/package.json"), "w") as f:
            json.dump({"format": 1, "id": "tool", "version": "1.0.0", "kind": "community", "connector": False,
                       "abi": {"svelte": SVELTE, "imports": {}}}, f)
        with open(j("installed/tool/1.0.0/ui/ui.js"), "w") as f:
            f.write("export default { id: 'tool' };\n")
        with open(j("installed/tool/state.json"), "w") as f:
            json.dump({"version": "1.0.0", "previous": None, "publisher": {"name": "alpha", "fingerprint": "SHA256:a"}}, f)
        keys = ("DB", "MODULES_DIR", "KEYS_DIR", "STATIC_DIR", "BACKENDS_FILE", "MASTER_KEY", "DELEGATION_KEY",
                "COOKIE_SECURE", "TRUST_PROXY", "HEALTH_INTERVAL", "INSTALLED_DIR", "RELEASE_PUB")
        cls.saved = {k: getattr(config, k) for k in keys}
        config.DB, config.MODULES_DIR, config.KEYS_DIR = j("lab.sqlite3"), j("modules"), j("keys")
        config.STATIC_DIR, config.BACKENDS_FILE, config.MASTER_KEY = j("dist"), j("backends.json"), j("master.key")
        config.DELEGATION_KEY, config.INSTALLED_DIR, config.RELEASE_PUB = j("delegation.key"), j("installed"), j("none.pub")
        config.COOKIE_SECURE, config.TRUST_PROXY, config.HEALTH_INTERVAL = False, False, 3600
        with open(config.MASTER_KEY, "w") as f:
            f.write(os.urandom(32).hex())
        app = server.App()
        cls.calls = []

        def fake(req, timeout=60):
            from lab.modstore import ModuleHelperError
            cls.calls.append(req)
            if req["op"] == "catalog-check" and "evil" in req["index"]:
                raise ModuleHelperError("the catalog: signed by an unknown publisher (SHA256:zz)", {"signer": "SHA256:zz"})
            if req["op"] == "catalog-check":
                return {"catalog": {"url": req["index"], "name": "C", "publisher": {"name": "alpha", "fingerprint": "SHA256:a"}},
                        "modules": []}
            if req["op"] == "status":
                return {"installed": [], "publishers": [], "catalogs": []}
            if req["op"] == "remove":
                return {"removed": req["id"], "version": "1.0.0", "kept_config": req["keep_config"], "bundled_remains": None}
            return {"rolled_back": req["id"], "version": "0.9.0", "from": "1.0.0"}
        app.module_helper = fake
        st = app.store
        st.upsert_user("boss", "", "", [], "owner")
        st.upsert_user("adm", "", "", [], "admin")
        st.upsert_user("gst", "", "", [], "guest")
        cls.owner = st.new_session("boss", 1, via="local")
        cls.admin = st.new_session("adm", 1, via="local")
        cls.guest = st.new_session("gst", 1, via="local")
        st.set_module_config("tool", "url", "http://x")
        st.set_module_config("tool", "token", app.box.seal("tool", "token", "t"), secret=True)
        app.reload_config()
        cls.gw = server.PooledHTTPServer(("127.0.0.1", 0), server.Handler, app, workers=4)
        cls.port = cls.gw.server_address[1]
        threading.Thread(target=cls.gw.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.gw.shutdown()
        for k, v in cls.saved.items():
            setattr(cls.config, k, v)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def call(self, method, path, body=None, token=None, raw=False):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        h = {"Cookie": f"lab_session={token}"} if token else {}
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            h["Content-Type"] = "application/json"
        c.request(method, path, data, h)
        r = c.getresponse()
        payload = r.read()
        c.close()
        return (r.status, payload, dict(r.getheaders())) if raw else (r.status, json.loads(payload or b"null"))

    def audit(self):
        return [(a["action"], a["result"]) for a in self.gw.app.store.audit_list(50)]

    def test_owner_only(self):
        for tok in (self.admin, self.guest, None):
            self.assertIn(self.call("GET", "/api/modules/store", token=tok)[0], (401, 403))
            self.assertIn(self.call("POST", "/api/modules/rollback", {"id": "tool"}, token=tok)[0], (401, 403))

    def test_catalogs_audited_and_signer_passed_on(self):
        s, out = self.call("POST", "/api/modules/catalogs", {"url": "https://evil.example/catalog.json"}, self.owner)
        self.assertEqual((s, out.get("signer")), (409, "SHA256:zz"))
        s, out = self.call("POST", "/api/modules/catalogs", {"url": "https://good.example/catalog.json"}, self.owner)
        self.assertEqual((s, [c["url"] for c in out["catalogs"]]), (200, ["https://good.example/catalog.json"]))
        self.assertEqual(self.call("POST", "/api/modules/catalogs", {"url": "https://good.example/catalog.json"}, self.owner)[0], 409)
        self.assertEqual(self.call("POST", "/api/modules/catalogs", {"url": "ftp://x/c.json"}, self.owner)[0], 400)
        self.assertIn(("module-catalog-add", "refused"), self.audit())
        self.assertIn(("module-catalog-add", "ok"), self.audit())
        s, out = self.call("POST", "/api/modules/catalogs", {"url": "https://good.example/catalog.json", "remove": True}, self.owner)
        self.assertEqual(out["catalogs"], [])

    def test_bad_requests(self):
        self.assertEqual(self.call("POST", "/api/modules/stage", {"id": "../x", "version": "1.0.0"}, self.owner)[0], 400)
        self.assertEqual(self.call("POST", "/api/modules/install", {"id": "tool", "version": "1"}, self.owner)[0], 400)
        self.assertEqual(self.call("POST", "/api/modules/remove", {"id": "tool", "keep_config": "no"}, self.owner)[0], 400)

    def test_bundle_route(self):
        s, body, h = self.call("GET", "/modules/tool/1.0.0/ui.js", token=self.owner, raw=True)
        self.assertEqual((s, body), (200, b"export default { id: 'tool' };\n"))
        self.assertTrue(h["Content-Type"].startswith("text/javascript"))
        self.assertEqual(self.call("GET", "/modules/tool/0.9.0/ui.js", token=self.owner, raw=True)[0], 404)
        self.assertEqual(self.call("GET", "/modules/tool/1.0.0/ui.js", token=self.guest, raw=True)[0], 404)
        self.assertEqual(self.call("GET", "/modules/tool/1.0.0/ui.js", raw=True)[0], 401)
        self.assertEqual(self.call("GET", "/modules/tool/1.0.0/../../x/ui.js", token=self.owner, raw=True)[0], 404)
        s, reg = self.call("GET", "/api/registry", token=self.owner)
        tool = next(m for m in reg["modules"] if m["id"] == "tool")
        self.assertEqual((tool["source"], tool["bundle"]), ("installed", "/modules/tool/1.0.0/ui.js"))

    def test_page_csp_allows_only_its_import_map(self):
        s, body, h = self.call("GET", "/", raw=True)
        im = b'{"imports":{"svelte":"/assets/abi/s.js"}}'
        want = "'sha256-" + base64.b64encode(hashlib.sha256(im).digest()).decode() + "'"
        self.assertIn(f"script-src 'self' {want};", h["Content-Security-Policy"])
        s, body, h = self.call("GET", "/modules/tool/1.0.0/ui.js", token=self.owner, raw=True)
        self.assertIn("script-src 'self';", h["Content-Security-Policy"])

    def test_remove_without_config_drops_it(self):
        st = self.gw.app.store
        st.set_module_setting("tool", "_ticker", False)
        s, out = self.call("POST", "/api/modules/remove", {"id": "tool", "keep_config": False}, self.owner)
        self.assertEqual((s, out["config_dropped"]), (200, 3))
        self.assertEqual(st.module_config("tool"), {})
        self.assertIn(("module-remove", "ok"), self.audit())
        st.set_module_config("tool", "url", "http://x")
        st.set_module_config("tool", "token", self.gw.app.box.seal("tool", "token", "t"), secret=True)
        self.gw.app.reload_config()


@unittest.skipUnless(HAVE_KEYGEN and HAVE_NODE, "ssh-keygen / node_modules missing")
class MakeModule(unittest.TestCase):
    def test_build_verify_tamper(self):
        with tempfile.TemporaryDirectory(prefix="labmk-") as d:
            key = os.path.join(d, "k")
            subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", "pub", "-f", key], check=True)
            out = os.path.join(d, "out")
            p = subprocess.run([os.path.join(ROOT, "deploy", "make-module.sh"), "dns", "--key", key, "--out", out,
                                "--version", "9.9.9", "--allow-dirty", "--catalog-name", "T"], capture_output=True, text=True)
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
            tar = os.path.join(out, "dns-9.9.9.tar.gz")
            env = {**os.environ, "LAB_GATEWAY_CODE": os.path.join(ROOT, "gateway")}
            helper = [sys.executable, "-I", os.path.join(ROOT, "deploy", "lab-module-helper"), "verify-package"]
            p = subprocess.run(helper + [tar, key + ".pub"], capture_output=True, text=True, env=env)
            self.assertEqual(p.returncode, 0, p.stderr)
            self.assertEqual(json.loads(p.stdout)["version"], "9.9.9")
            with tarfile.open(tar) as t:
                names = sorted(t.getnames())
                pkg = json.load(t.extractfile("dns-9.9.9/package.json"))
            self.assertEqual(names, ["dns-9.9.9", "dns-9.9.9/MANIFEST", "dns-9.9.9/manifest.json", "dns-9.9.9/package.json",
                                     "dns-9.9.9/ui", "dns-9.9.9/ui/ui.js"])
            self.assertIn("svelte/internal/client", pkg["abi"]["imports"])
            cat = json.load(open(os.path.join(out, "catalog.json")))
            self.assertEqual((cat["name"], cat["modules"][0]["versions"][0]["version"]), ("T", "9.9.9"))
            self.assertTrue(os.path.exists(os.path.join(out, "catalog.json.sig")))
            other = os.path.join(d, "o")
            subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", other], check=True)
            p = subprocess.run(helper + [tar, other + ".pub"], capture_output=True, text=True, env=env)
            self.assertIn("unknown publisher", p.stderr)
            with open(tar, "ab") as f:
                f.write(b"\0")
            p = subprocess.run(helper + [tar, key + ".pub"], capture_output=True, text=True, env=env)
            self.assertIn("does NOT verify", p.stderr)


class LabAdminCatalogList(unittest.TestCase):
    """`lab-admin package catalog-add|catalog-remove`: the same list Settings → Modules keeps (gateway_config), and
    adding verifies the catalog through the helper first (an unverifiable one is never listed)."""

    def test_add_remove(self):
        import argparse
        import contextlib
        from lab import modstore
        from lab.store import Store
        loader = importlib.machinery.SourceFileLoader("lab_admin_t", os.path.join(ROOT, "gateway", "lab_admin.py"))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        la = importlib.util.module_from_spec(spec)
        loader.exec_module(la)
        t = tempfile.mkdtemp()
        calls, real = [], modstore.call_module_helper
        ok = {"catalog": {"name": "Mine", "publisher": {"name": "me", "fingerprint": "SHA256:x"}}}

        def fake(req, timeout=120, path=None):
            calls.append(req)
            if req["index"].endswith("bad.json"):
                raise modstore.ModuleHelperError("not signed by a trusted publisher")
            return ok
        modstore.call_module_helper = fake
        try:
            st = Store(os.path.join(t, "lab.sqlite3"))
            a = lambda action, url: argparse.Namespace(action=action, id=url, version=None, catalog=None, yes=True,  # noqa: E731
                                                      drop_config=False)
            with contextlib.redirect_stdout(io.StringIO()):
                la.package_cmd(a("catalog-add", "https://dist.example/modules/catalog.json"), st)
                self.assertEqual([c["url"] for c in modstore.catalogs(st)], ["https://dist.example/modules/catalog.json"])
                self.assertEqual(calls[-1]["op"], "catalog-check")
                with self.assertRaises(SystemExit):   # twice
                    la.package_cmd(a("catalog-add", "https://dist.example/modules/catalog.json"), st)
                with self.assertRaises(SystemExit):   # the helper refuses it → not listed
                    la.package_cmd(a("catalog-add", "https://dist.example/bad.json"), st)
                with self.assertRaises(SystemExit):   # not a URL
                    la.package_cmd(a("catalog-add", "file:///etc/passwd"), st)
                self.assertEqual(len(modstore.catalogs(st)), 1)
                la.package_cmd(a("catalog-remove", "https://dist.example/modules/catalog.json"), st)
            self.assertEqual(modstore.catalogs(st), [])
            acts = [r["action"] for r in st.q("SELECT action FROM audit ORDER BY rowid")]
            self.assertIn("module-catalog-add", acts)
            self.assertIn("module-catalog-remove", acts)
        finally:
            modstore.call_module_helper = real
            shutil.rmtree(t, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
