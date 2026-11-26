"""Releases + core updates (step 17): deploy/lab-update-helper and gateway/lab/updates.py.

  * version compare (semver precedence) and the upgrade policy (no downgrade, no same version, min_upgrade_from);
  * OpenSSH signatures: good, tampered, wrong key, wrong namespace;
  * the signed index: good, tampered, signed by another key, malformed;
  * staging: sha256, the tarball's signature, the MANIFEST (changed / extra / missing file), unsafe tar members;
  * URL policy: https only, http:// only to LAN addresses with the test flag, redirects checked too;
  * the helper's command validation (fixed commands only);
  * the job: a good install, an install that fails before switching, a release that doesn't come up (auto rollback);
  * the gateway routes: owner only, audited, index setting locked by the environment.

Needs ssh-keygen (OpenSSH ≥ 8). Imports the gateway lazily and restores lab.config (see test_login.py)."""
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


def load_helper():
    loader = importlib.machinery.SourceFileLoader("lab_update_helper", os.path.join(ROOT, "deploy", "lab-update-helper"))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


H = load_helper()
TMP = None
FILES = {}          # path served by the test web server → bytes
REDIRECTS = {}      # path → Location


class Files(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path in REDIRECTS:
            self.send_response(302)
            self.send_header("Location", REDIRECTS[self.path])
            self.end_headers()
            return
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


def sign(key, data, namespace="labradoor-release"):
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "f")
        with open(p, "wb") as f:
            f.write(data)
        subprocess.run(["ssh-keygen", "-q", "-Y", "sign", "-f", key, "-n", namespace, p], check=True)
        with open(p + ".sig", "rb") as f:
            return f.read()


def make_tree(root, version, extra=None):
    files = {"VERSION": f"{version}\n", "deploy/install.sh": "#!/bin/sh\necho installing\n",
             "gateway/lab/server.py": "# gateway\n", "ui/dist/index.html": "<!doctype html>\n", **(extra or {})}
    for rel, text in files.items():
        p = os.path.join(root, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as f:
            f.write(text)
    H.write_manifest(root)


def tarball(version, mutate=None, members=None):
    """A release tarball as bytes; mutate(tree) runs after the MANIFEST was written; members: extra raw TarInfos."""
    with tempfile.TemporaryDirectory() as d:
        top = os.path.join(d, f"labradoor-{version}")
        os.makedirs(top)
        make_tree(top, version)
        if mutate:
            mutate(top)
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as t:
            t.add(top, arcname=f"labradoor-{version}")
            for info, data in members or []:
                t.addfile(info, io.BytesIO(data) if data is not None else None)
        return buf.getvalue()


@unittest.skipUnless(HAVE_KEYGEN, "ssh-keygen missing")
class ReleaseBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        global TMP
        TMP = tempfile.mkdtemp(prefix="labrel-")
        cls.key = keygen("release")
        cls.other = keygen("other")
        cls.pub = cls.key + ".pub"
        cls.srv = HTTPServer(("127.0.0.1", 0), Files)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.srv.server_address[1]}"
        cls.saved = {k: getattr(H, k) for k in ("STATE", "PUBKEY", "LIVE", "REL_ROOT", "SYSTEMCTL", "SYSTEMD_RUN",
                                                  "SELF", "LAB_ENV", "ROLLBACK", "LOCK")}
        os.environ["LAB_UPDATE_ALLOW_HTTP"] = "1"

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        for k, v in cls.saved.items():
            setattr(H, k, v)
        os.environ.pop("LAB_UPDATE_ALLOW_HTTP", None)
        shutil.rmtree(TMP, ignore_errors=True)

    def setUp(self):
        FILES.clear()
        REDIRECTS.clear()
        self.dir = tempfile.mkdtemp(dir=TMP)
        H.STATE = os.path.join(self.dir, "state")
        H.PUBKEY = self.pub
        H.REL_ROOT = os.path.join(self.dir, "releases")
        os.makedirs(os.path.join(H.REL_ROOT, "20261115-010000-aaaaaaa"))
        with open(os.path.join(H.REL_ROOT, "20261115-010000-aaaaaaa", "VERSION"), "w") as f:
            f.write("0.1.0\n")
        H.LIVE = os.path.join(self.dir, "lab")
        os.symlink(os.path.join(H.REL_ROOT, "20261115-010000-aaaaaaa"), H.LIVE)
        H.SYSTEMCTL = "/bin/false"

    def publish(self, entries, key=None, raw=None):
        doc = {"format": 1, "product": "labradoor", "releases": entries}
        data = raw if raw is not None else json.dumps(doc).encode()
        FILES["/rel/index.json"] = data
        FILES["/rel/index.json.sig"] = sign(key or self.key, data)
        return self.base + "/rel/index.json"

    def release(self, version, data=None, key=None, low=None, notes=""):
        data = data if data is not None else tarball(version)
        name = f"labradoor-{version}.tar.gz"
        FILES[f"/rel/{name}"] = data
        FILES[f"/rel/{name}.sig"] = sign(key or self.key, data)
        return {"version": version, "date": "2026-11-15", "sha256": hashlib.sha256(data).hexdigest(), "url": name,
                "sig": name + ".sig", "min_upgrade_from": low, "notes": notes}


class Versions(unittest.TestCase):
    def test_semver_order(self):
        order = ["0.9.9", "1.0.0-alpha", "1.0.0-alpha.1", "1.0.0-alpha.beta", "1.0.0-beta", "1.0.0-beta.2",
                 "1.0.0-beta.11", "1.0.0-rc.1", "1.0.0", "1.0.1-dev", "1.0.1", "1.2.0", "1.10.0", "2.0.0"]
        for i, a in enumerate(order):
            for j, b in enumerate(order):
                self.assertEqual(H.compare(a, b), (i > j) - (i < j), f"{a} vs {b}")

    def test_build_metadata_ignored(self):
        self.assertEqual(H.compare("0.1.0-dev+gabc", "0.1.0-dev"), 0)

    def test_not_versions(self):
        for bad in ("", "1", "1.0", "01.0.0", "1.0.0-", "v1.0.0", "1.0.0/../x", "1.0.0 ", None, 5, "1." * 40 + "0"):
            self.assertFalse(H.is_version(bad), bad)
            with self.assertRaises(ValueError):
                H.compare(bad, "1.0.0")

    def test_upgrade_policy(self):
        e = lambda v, low=None: {"version": v, "min_upgrade_from": low}  # noqa: E731
        self.assertEqual(H.may_upgrade("0.1.0", e("0.1.1")), (True, ""))
        self.assertIn("already installed", H.may_upgrade("0.1.0", e("0.1.0"))[1])
        self.assertIn("rollback", H.may_upgrade("0.2.0", e("0.1.9"))[1])                     # downgrade
        self.assertFalse(H.may_upgrade("0.1.0-dev", e("0.1.0-alpha"))[0])                    # pre-release order
        self.assertIn("0.2.0 or newer", H.may_upgrade("0.1.5", e("0.3.0", "0.2.0"))[1])      # min_upgrade_from
        self.assertTrue(H.may_upgrade("0.2.0", e("0.3.0", "0.2.0"))[0])
        self.assertFalse(H.may_upgrade(None, e("9.9.9"))[0])                                 # unknown (git deploy)


class Urls(unittest.TestCase):
    def test_policy(self):
        self.assertEqual(H.check_url("https://releases.example/index.json", False), "https://releases.example/index.json")
        for bad in ("http://10.0.0.5/i.json", "ftp://x/i", "file:///etc/passwd", "https://u:p@x/i", "https://x/i#f",
                    "https:///nohost", "https://x/a b", "", None, "https://x/" + "a" * 3000):
            with self.assertRaises(H.Fail, msg=bad):
                H.check_url(bad, False)
        self.assertTrue(H.check_url("http://10.0.0.5/i.json", True))        # LAN with the test flag
        self.assertTrue(H.check_url("http://127.0.0.1:8000/i.json", True))
        with self.assertRaises(H.Fail):
            H.check_url("http://93.184.216.34/i.json", True)                 # never plain http to the internet


class Signatures(ReleaseBase):
    def test_good_tampered_wrong_key_wrong_namespace(self):
        data = b"labradoor release\n"
        self.assertTrue(H.verify_bytes(data, sign(self.key, data)))
        self.assertFalse(H.verify_bytes(data + b"x", sign(self.key, data)))
        self.assertFalse(H.verify_bytes(data, sign(self.other, data)))
        self.assertFalse(H.verify_bytes(data, sign(self.key, data, namespace="file")))
        self.assertFalse(H.verify_bytes(data, b"not a signature"))

    def test_no_or_bad_key_file(self):
        H.PUBKEY = os.path.join(self.dir, "missing.pub")
        with self.assertRaises(H.Fail):
            H.verify_bytes(b"x", b"y")
        with open(H.PUBKEY, "w") as f:
            f.write("not a key\n")
        with self.assertRaises(H.Fail):
            H.verify_bytes(b"x", b"y")


class Index(ReleaseBase):
    def test_check_lists_and_picks(self):
        url = self.publish([self.release("0.1.1", notes="fixes"), self.release("0.2.0", low="0.1.1"),
                            self.release("0.0.9")])
        out = H.op_check(url)
        self.assertEqual(out["current"], "0.1.0")
        self.assertEqual(out["latest"], "0.2.0")
        self.assertEqual(out["update"], "0.1.1")                  # 0.2.0 needs 0.1.1 first
        self.assertEqual([r["version"] for r in out["releases"]], ["0.2.0", "0.1.1", "0.0.9"])
        self.assertEqual(out["releases"][1]["notes"], "fixes")

    def test_tampered_index(self):
        url = self.publish([self.release("0.1.1")])
        FILES["/rel/index.json"] = FILES["/rel/index.json"].replace(b"0.1.1", b"0.1.2")
        with self.assertRaisesRegex(H.Fail, "signature"):
            H.op_check(url)

    def test_index_signed_by_other_key(self):
        url = self.publish([self.release("0.1.1")], key=self.other)
        with self.assertRaisesRegex(H.Fail, "signature"):
            H.op_check(url)

    def test_missing_signature(self):
        url = self.publish([self.release("0.1.1")])
        del FILES["/rel/index.json.sig"]
        with self.assertRaisesRegex(H.Fail, "404"):
            H.op_check(url)

    def test_malformed(self):
        for raw in (b"[]", b"{}", b'{"format": 2, "releases": []}', b"not json",
                    json.dumps({"format": 1, "releases": [{"version": "1.0", "sha256": "0" * 64, "url": "x"}]}).encode(),
                    json.dumps({"format": 1, "releases": [{"version": "1.0.0", "sha256": "zz", "url": "x"}]}).encode(),
                    json.dumps({"format": 1, "product": "other", "releases": []}).encode()):
            url = self.publish([], raw=raw)
            with self.assertRaises(H.Fail, msg=raw):
                H.op_check(url)

    def test_redirect_to_internet_http_refused(self):
        url = self.publish([self.release("0.1.1")])
        REDIRECTS["/moved/index.json"] = "http://93.184.216.34/index.json"
        with self.assertRaisesRegex(H.Fail, "LAN"):
            H.op_check(self.base + "/moved/index.json")
        self.assertTrue(H.op_check(url))

    def test_http_needs_flag(self):
        url = self.publish([self.release("0.1.1")])
        os.environ.pop("LAB_UPDATE_ALLOW_HTTP")
        try:
            with self.assertRaisesRegex(H.Fail, "https"):
                H.op_check(url)
        finally:
            os.environ["LAB_UPDATE_ALLOW_HTTP"] = "1"


class Stage(ReleaseBase):
    def test_good(self):
        url = self.publish([self.release("0.1.1")])
        out = H.op_stage(url, "0.1.1")
        self.assertEqual(out["staged"], "0.1.1")
        self.assertEqual(H.staged(), ["0.1.1"])
        e, tree = H.verify_staged("0.1.1")
        self.assertTrue(os.path.isfile(os.path.join(tree, "deploy", "install.sh")))

    def test_sha256_mismatch(self):
        e = self.release("0.1.1")
        e["sha256"] = "0" * 64
        with self.assertRaisesRegex(H.Fail, "sha256"):
            H.op_stage(self.publish([e]), "0.1.1")
        self.assertEqual(H.staged(), [])

    def test_tarball_signed_by_other_key(self):
        e = self.release("0.1.1", key=self.other)    # the index (good key) has the right sha256, the .sig is foreign
        with self.assertRaisesRegex(H.Fail, "signature"):
            H.op_stage(self.publish([e]), "0.1.1")

    def test_manifest_mismatch_extra_missing(self):
        def changed(top):
            with open(os.path.join(top, "gateway", "lab", "server.py"), "a") as f:
                f.write("evil()\n")

        def extra(top):
            with open(os.path.join(top, "deploy", "sneaky.sh"), "w") as f:
                f.write("x")

        def missing(top):
            os.remove(os.path.join(top, "gateway", "lab", "server.py"))

        for mutate, msg in ((changed, "MANIFEST mismatch"), (extra, "not in the MANIFEST"), (missing, "missing")):
            url = self.publish([self.release("0.1.1", data=tarball("0.1.1", mutate))])
            with self.assertRaisesRegex(H.Fail, msg):
                H.op_stage(url, "0.1.1")

    def test_wrong_version_inside(self):
        def other_version(top):
            with open(os.path.join(top, "VERSION"), "w") as f:
                f.write("0.9.0\n")
            H.write_manifest(top)
        url = self.publish([self.release("0.1.1", data=tarball("0.1.1", other_version))])
        with self.assertRaisesRegex(H.Fail, "not 0.1.1"):
            H.op_stage(url, "0.1.1")

    def test_unsafe_members(self):
        link = tarfile.TarInfo("labradoor-0.1.1/deploy/link")
        link.type, link.linkname = tarfile.SYMTYPE, "/etc/shadow"
        trav = tarfile.TarInfo("labradoor-0.1.1/../../evil")
        trav.size = 1
        other = tarfile.TarInfo("elsewhere/x")
        other.size = 1
        for m, msg in ((link, "link"), (trav, "outside"), (other, "outside")):
            url = self.publish([self.release("0.1.1", data=tarball("0.1.1", members=[(m, b"x" if m.size else None)]))])
            with self.assertRaisesRegex(H.Fail, msg):
                H.op_stage(url, "0.1.1")

    def test_downgrade_and_min_upgrade_from(self):
        url = self.publish([self.release("0.0.9"), self.release("0.1.0"), self.release("0.3.0", low="0.2.0")])
        for v, msg in (("0.0.9", "older"), ("0.1.0", "already"), ("0.3.0", "0.2.0 or newer"), ("0.4.0", "not in")):
            with self.assertRaisesRegex(H.Fail, msg):
                H.op_stage(url, v)

    def test_apply_reverifies(self):
        url = self.publish([self.release("0.1.1")])
        H.op_stage(url, "0.1.1")
        tree = os.path.join(H.stage_dir("0.1.1"), "tree", "labradoor-0.1.1")
        with open(os.path.join(tree, "deploy", "install.sh"), "a") as f:
            f.write("rm -rf /\n")
        with self.assertRaisesRegex(H.Fail, "MANIFEST"):
            H.op_apply("0.1.1", "owner")
        with self.assertRaisesRegex(H.Fail, "not staged"):
            H.op_apply("0.1.2", "owner")


class Commands(unittest.TestCase):
    def test_fixed_commands_only(self):
        ok = [({"op": "status"}, "status"), ({"op": "check", "index": "https://r.example/i.json"}, "check"),
              ({"op": "stage", "index": "https://r.example/i.json", "version": "1.0.0", "by": "owner"}, "stage"),
              ({"op": "apply", "version": "1.0.0-rc.1"}, "apply"), ({"op": "rollback"}, "rollback"),
              ({"op": "rollback", "release": "20261115-010000-abc1234", "with_db": False}, "rollback")]
        for req, op in ok:
            self.assertEqual(H.check(req)[0], op, req)
        # restoring the database: root only (review H2) — the gateway's group may not ask for it
        wdb = {"op": "rollback", "release": "20261115-010000-abc1234", "with_db": True}
        with self.assertRaisesRegex(H.Fail, "only possible as root"):
            H.check(wdb)
        self.assertEqual(H.check(wdb, root=True)[1]["with_db"], True)
        bad = [None, [], {}, {"op": "shell", "cmd": "id"}, {"op": "status", "id": 1}, {"op": "check"},
               {"op": "check", "index": "http://evil.example/i.json"}, {"op": "apply"},
               {"op": "apply", "version": "../../etc"}, {"op": "apply", "version": "1.0.0", "index": "https://x/i"},
               {"op": "rollback", "release": "../x"}, {"op": "rollback", "release": "x; rm -rf /"},
               {"op": "rollback", "with_db": "yes"}, {"op": "status", "by": "a\nb"},
               {"op": "stage", "index": "https://r.example/i.json", "version": "1.0.0", "url": "https://x"}]
        for req in bad:
            with self.assertRaises(H.Fail, msg=req):
                H.check(req)

    def test_socket_protocol(self):
        out = subprocess.run([sys.executable, os.path.join(ROOT, "deploy", "lab-update-helper")],
                             input=b'{"op": "nope"}\n', capture_output=True, timeout=30)
        ans = json.loads(out.stdout)
        self.assertFalse(ans["ok"])
        self.assertIn("op is one of", ans["error"])
        out = subprocess.run([sys.executable, os.path.join(ROOT, "deploy", "lab-update-helper")],
                             input=b"garbage\n", capture_output=True, timeout=30)
        self.assertEqual(json.loads(out.stdout), {"ok": False, "error": "one JSON line expected"})


class Health(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        self.send_response(200 if self.server.up else 503)
        self.end_headers()


class Job(ReleaseBase):
    """run_job with a fake install.sh (switches the LIVE symlink like the real one) and a fake lab-rollback."""

    def setUp(self):
        super().setUp()
        self.health = HTTPServer(("127.0.0.1", 0), Health)
        self.health.up = True
        threading.Thread(target=self.health.serve_forever, daemon=True).start()
        H.LAB_ENV = os.path.join(self.dir, "lab.env")
        with open(H.LAB_ENV, "w") as f:
            f.write(f"LAB_PORT={self.health.server_address[1]}\n")
        H.LOCK = os.path.join(self.dir, "deploy.lock")
        H.ROLLBACK = os.path.join(self.dir, "lab-rollback")
        with open(H.ROLLBACK, "w") as f:   # args: RELEASE [--with-db]
            f.write(f'#!/bin/sh\necho "rollback $*" >> {self.dir}/rollbacks\nln -sfn "{H.REL_ROOT}/$1" "{H.LIVE}"\n')
        os.chmod(H.ROLLBACK, 0o755)
        self._orig_healthy = H.healthy
        H.healthy = lambda wait=3: self._orig_healthy(wait)

    def tearDown(self):
        H.healthy = self._orig_healthy
        self.health.shutdown()

    def stage_with(self, script):
        def put(top):
            with open(os.path.join(top, "deploy", "install.sh"), "w") as f:
                f.write(script)
            H.write_manifest(top)
        url = self.publish([self.release("0.1.1", data=tarball("0.1.1", put))])
        H.op_stage(url, "0.1.1")
        H.write_job({"id": "j1", "op": "apply", "target": "0.1.1", "state": "queued", "by": "owner"})

    def switch_script(self, extra=""):
        new = os.path.join(H.REL_ROOT, "20261115-020000-bbbbbbb")
        return f'#!/bin/sh\nmkdir -p "{new}" && echo 0.1.1 > "{new}/VERSION" && ln -sfn "{new}" "{H.LIVE}"\n{extra}'

    def test_good_install(self):
        self.stage_with(self.switch_script())
        self.assertEqual(H.run_job(["apply", "0.1.1", "j1"]), 0)
        job = H.read_job()
        self.assertEqual(job["state"], "ok", job)
        self.assertEqual(H.installed()[0], "0.1.1")
        self.assertEqual(H.staged(), [])                     # the staged copy is gone once live

    def test_install_fails_before_switch(self):
        self.stage_with("#!/bin/sh\necho broken; exit 3\n")
        self.assertEqual(H.run_job(["apply", "0.1.1", "j1"]), 1)
        job = H.read_job()
        self.assertEqual(job["state"], "failed")
        self.assertIn("nothing changed", job["message"])
        self.assertIn("broken", "\n".join(job["tail"]))
        self.assertEqual(H.installed()[0], "0.1.0")

    def test_unhealthy_release_is_rolled_back_with_db(self):
        self.stage_with(self.switch_script())
        self.health.up = False
        self.assertEqual(H.run_job(["apply", "0.1.1", "j1"]), 1)
        job = H.read_job()
        self.assertIn("rolled back to 20261115-010000-aaaaaaa", job["message"])
        with open(os.path.join(self.dir, "rollbacks")) as f:
            self.assertEqual(f.read().strip(), "rollback 20261115-010000-aaaaaaa --with-db")
        self.assertEqual(H.installed()[0], "0.1.0")

    def test_rollback_job_goes_forward_again_when_down(self):
        os.makedirs(os.path.join(H.REL_ROOT, "20261115-020000-bbbbbbb"))
        with open(os.path.join(H.REL_ROOT, "20261115-020000-bbbbbbb", "VERSION"), "w") as f:
            f.write("0.1.1\n")
        os.remove(H.LIVE)
        os.symlink(os.path.join(H.REL_ROOT, "20261115-020000-bbbbbbb"), H.LIVE)
        H.write_job({"id": "j2", "op": "rollback", "target": "20261115-010000-aaaaaaa", "state": "queued"})
        self.health.up = False
        self.assertEqual(H.run_job(["rollback", "20261115-010000-aaaaaaa", "0", "j2"]), 1)
        self.assertIn("roll back with the database", H.read_job()["message"])
        self.assertEqual(H.installed()[0], "0.1.1")
        self.health.up = True
        H.write_job({"id": "j3", "op": "rollback", "target": "20261115-010000-aaaaaaa", "state": "queued"})
        self.assertEqual(H.run_job(["rollback", "20261115-010000-aaaaaaa", "1", "j3"]), 0)
        self.assertEqual(H.installed()[0], "0.1.0")

    def test_rollback_request_defaults_to_previous(self):
        os.makedirs(os.path.join(H.REL_ROOT, "20261115-020000-bbbbbbb"))
        os.remove(H.LIVE)
        os.symlink(os.path.join(H.REL_ROOT, "20261115-020000-bbbbbbb"), H.LIVE)
        started = []
        H.SYSTEMD_RUN = os.path.join(self.dir, "systemd-run")
        with open(H.SYSTEMD_RUN, "w") as f:
            f.write(f'#!/bin/sh\necho "$@" > {self.dir}/started\n')
        os.chmod(H.SYSTEMD_RUN, 0o755)
        out = H.op_rollback(None, False, "owner")
        self.assertEqual(out["state"], "started")
        with open(os.path.join(self.dir, "started")) as f:
            started = f.read()
        self.assertIn("--job rollback 20261115-010000-aaaaaaa 0", started)
        self.assertIn("--unit=lab-update-job", started)
        with self.assertRaisesRegex(H.Fail, "already live"):
            H.op_rollback("20261115-020000-bbbbbbb", False, "owner")
        with self.assertRaisesRegex(H.Fail, "no such release"):
            H.op_rollback("20991231-000000-zzzzzzz", False, "owner")


class GatewayRoutes(unittest.TestCase):
    """Owner only; every step audited; the helper's answer passed through; LAB_RELEASE_INDEX locks the setting."""

    @classmethod
    def setUpClass(cls):
        from lab import config, server
        cls.config, cls.server = config, server
        cls.tmp = tempfile.mkdtemp(prefix="labupd-")
        for d in ("modules", "keys", "dist"):
            os.makedirs(os.path.join(cls.tmp, d))
        with open(os.path.join(cls.tmp, "dist", "index.html"), "w") as f:
            f.write("<!doctype html>")
        cls.saved = {k: getattr(config, k) for k in ("DB", "MODULES_DIR", "KEYS_DIR", "STATIC_DIR", "BACKENDS_FILE",
                                                     "MASTER_KEY", "DELEGATION_KEY", "COOKIE_SECURE", "TRUST_PROXY",
                                                     "HEALTH_INTERVAL")}
        config.DB = os.path.join(cls.tmp, "lab.sqlite3")
        config.MODULES_DIR = os.path.join(cls.tmp, "modules")
        config.KEYS_DIR = os.path.join(cls.tmp, "keys")
        config.STATIC_DIR = os.path.join(cls.tmp, "dist")
        config.BACKENDS_FILE = os.path.join(cls.tmp, "backends.json")
        config.MASTER_KEY = os.path.join(cls.tmp, "master.key")
        config.DELEGATION_KEY = os.path.join(cls.tmp, "delegation.key")
        config.COOKIE_SECURE, config.TRUST_PROXY, config.HEALTH_INTERVAL = False, False, 3600
        os.environ.pop("LAB_RELEASE_INDEX", None)
        app = server.App()
        cls.calls = []

        def fake(req, timeout=60):
            cls.calls.append(req)
            if req["op"] == "check":
                return {"ok": True, "current": "0.1.0", "latest": "0.1.1", "update": "0.1.1", "releases": []}
            if req["op"] == "stage" and req["version"] == "6.6.6":
                from lab.updates import UpdateHelperError
                raise UpdateHelperError("the release signature does not verify")
            if req["op"] == "status":
                return {"ok": True, "version": "0.1.0", "job": {"id": "j9", "op": "apply", "target": "0.1.1",
                                                                "state": "ok", "by": "boss", "message": "0.1.1 is live"}}
            return {"ok": True, "job": "j9", "state": "started", "staged": req.get("version"), "files": 3, "sha256": "ab"}
        app.update_helper = fake
        st = app.store
        st.upsert_user("boss", "", "", [], "owner")
        st.upsert_user("adm", "", "", [], "admin")
        cls.owner = st.new_session("boss", 1, via="local")
        cls.admin = st.new_session("adm", 1, via="local")
        cls.gw = server.PooledHTTPServer(("127.0.0.1", 0), server.Handler, app, workers=4)
        cls.port = cls.gw.server_address[1]
        threading.Thread(target=cls.gw.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.gw.shutdown()
        for k, v in cls.saved.items():
            setattr(cls.config, k, v)
        os.environ.pop("LAB_RELEASE_INDEX", None)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def call(self, method, path, body=None, token=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        h = {"Cookie": f"lab_session={token}"} if token else {}
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            h["Content-Type"] = "application/json"
        c.request(method, path, data, h)
        r = c.getresponse()
        out = json.loads(r.read() or b"null")
        c.close()
        return r.status, out

    def audit(self):
        return [(a["action"], a["result"]) for a in self.gw.app.store.audit_list(50)]

    def test_owner_only(self):
        for method, path in (("GET", "/api/update"), ("GET", "/api/update/status"), ("POST", "/api/update/check"),
                             ("POST", "/api/update/apply"), ("POST", "/api/update/rollback")):
            self.assertEqual(self.call(method, path, {} if method == "POST" else None, self.admin)[0], 403, path)
            self.assertEqual(self.call(method, path, {} if method == "POST" else None)[0], 401, path)

    def test_flow_audited(self):
        self.call("POST", "/api/update/settings", {"index": ""}, self.owner)
        self.assertEqual(self.call("POST", "/api/update/check", {}, self.owner)[0], 409)   # no index yet
        s, out = self.call("POST", "/api/update/settings", {"index": "ftp://x/i.json"}, self.owner)
        self.assertEqual(s, 400)
        s, out = self.call("POST", "/api/update/settings", {"index": "https://releases.example/index.json"}, self.owner)
        self.assertEqual((s, out["index"]["source"]), (200, "settings"))
        s, out = self.call("POST", "/api/update/check", {}, self.owner)
        self.assertEqual((s, out["update"]), (200, "0.1.1"))
        self.assertEqual(self.calls[-1], {"op": "check", "index": "https://releases.example/index.json", "by": "boss"})
        s, out = self.call("POST", "/api/update/stage", {"version": "6.6.6"}, self.owner)
        self.assertEqual((s, out["error"]), (409, "the release signature does not verify"))
        self.assertEqual(self.call("POST", "/api/update/stage", {"version": "0.1.1"}, self.owner)[0], 200)
        self.assertEqual(self.call("POST", "/api/update/apply", {"version": "0.1.1"}, self.owner)[1]["job"], "j9")
        self.assertEqual(self.call("POST", "/api/update/rollback", {"with_db": "x"}, self.owner)[0], 400)
        n = len(self.calls)
        s, out = self.call("POST", "/api/update/rollback", {"release": "20261115-010000-abc", "with_db": True}, self.owner)
        self.assertEqual((s, len(self.calls)), (403, n))   # root only (review H2): never even sent to the helper
        self.assertIn("lab-admin rollback --with-db", out["error"])
        self.assertEqual(self.call("POST", "/api/update/rollback", {"release": "20261115-010000-abc"}, self.owner)[0], 200)
        self.assertEqual(self.calls[-1], {"op": "rollback", "release": "20261115-010000-abc", "with_db": False, "by": "boss"})
        s, out = self.call("GET", "/api/update", None, self.owner)
        self.assertEqual(out["index"]["url"], "https://releases.example/index.json")
        self.call("GET", "/api/update/status", None, self.owner)               # the finished job: audited once
        acts = self.audit()
        for want in (("update-settings", "ok"), ("update-check", "ok"), ("update-stage", "refused"),
                     ("update-stage", "ok"), ("update-apply", "ok"), ("update-rollback", "refused"),
                     ("update-rollback", "ok"), ("apply-result", "ok")):
            self.assertIn(want, acts)
        self.assertEqual(acts.count(("apply-result", "ok")), 1)

    def test_env_index_is_the_default(self):
        os.environ["LAB_RELEASE_INDEX"] = "https://default.example/index.json"
        try:
            self.call("POST", "/api/update/settings", {"index": ""}, self.owner)
            s, out = self.call("GET", "/api/update", None, self.owner)
            self.assertEqual(out["index"], {"url": "https://default.example/index.json", "source": "env",
                                            "env": "LAB_RELEASE_INDEX"})
            s, out = self.call("POST", "/api/update/settings", {"index": "https://mine.example/i.json"}, self.owner)
            self.assertEqual(out["index"]["source"], "settings")
            s, out = self.call("POST", "/api/update/settings", {"index": ""}, self.owner)   # back to the default
            self.assertEqual(out["index"]["url"], "https://default.example/index.json")
        finally:
            os.environ.pop("LAB_RELEASE_INDEX")


class Files_(unittest.TestCase):
    def read(self, *p):
        with open(os.path.join(ROOT, *p)) as f:
            return f.read()

    def test_units_and_install(self):
        sock = self.read("deploy", "lab-update-helper.socket")
        self.assertIn("SocketGroup=lab", sock)
        self.assertIn("SocketMode=0660", sock)
        svc = self.read("deploy", "lab-update-helper@.service")
        self.assertIn("EnvironmentFile=-/etc/lab/update.env", svc)
        inst = self.read("deploy", "install.sh")
        for want in ("/usr/local/sbin/lab-update-helper", "/etc/lab/release.pub", "/var/lib/lab-update"):
            self.assertIn(want, inst)
        self.assertTrue(H.KEY_RE.match(self.read("deploy", "release.pub").strip()))
        self.assertTrue(H.is_version(self.read("VERSION").strip()))

    def test_installer_mints_one_setup_link(self):
        """A fresh install makes ONE first-run link (one audit entry): deploy/install.sh skips its own when the Proxmox
        installer runs it (that one sets the public address first and mints the link afterwards)."""
        import re
        top, inner = self.read("install.sh"), self.read("deploy", "install.sh")
        runs = lambda sh: [ln for ln in sh.splitlines()
                           if "lab-admin setup-link" in ln and not ln.lstrip().startswith(("#", "echo"))]
        self.assertEqual(len(runs(top)), 1, runs(top))
        self.assertEqual(len(runs(inner)), 1, runs(inner))
        self.assertIn('"${LAB_SKIP_SETUP_LINK:-0}" != 1', runs(inner)[0])
        calls = [ln for ln in top.splitlines() if re.search(r'sh "\$TREE/deploy/install.sh"', ln)]
        self.assertTrue(calls and all("LAB_SKIP_SETUP_LINK=1" in ln for ln in calls), calls)

    def test_installer_pins_the_shipped_key(self):
        pub = self.read("deploy", "release.pub").strip().split()[1]
        self.assertIn(pub, self.read("install.sh"))
