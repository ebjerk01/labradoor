"""Security review 2026-11-15, H2: the gateway's user (lab) must not reach root through the update helper.

Root scripts reached from the helper — deploy/lab-rollback --with-db, deploy/install.sh on apply (and the lab-admin
calls it makes), the helper itself — must never follow a symlink or act on a path that lab (or a connector's user) can
create or replace. Shown here, without root (the tests run as one ordinary user; "root" is that user):

  * deploy/lab-dbcopy: a symlinked backup directory, a planted link at the destination, a symlinked database and
    planted -wal/-shm links are refused or never followed; old /var/lib/lab/backups is adopted only when it is root's
    own real directory; pruning only touches root's tree;
  * deploy/lab-rollback --with-db: restores through lab-dbcopy, refuses a backup directory that is a symlink or
    writable by others, never writes through a planted link, keeps a snapshot of what it replaced;
  * the update helper refuses with_db unless its peer is root (SO_PEERCRED), over a real socket too;
  * install.sh / lab-admin: no root chmod/chown/rm/copy by name inside lab's directories, lab-admin drops to lab before
    it opens the database, the setup link goes to a 0600 file and not to a log."""
import hashlib
import importlib.machinery
import importlib.util
import json
import os
import pwd
import re
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DBCOPY = os.path.join(ROOT, "deploy", "lab-dbcopy")
ROLLBACK = os.path.join(ROOT, "deploy", "lab-rollback")
HELPER = os.path.join(ROOT, "deploy", "lab-update-helper")
ME = pwd.getpwuid(os.geteuid()).pw_name


def load(path, name):
    loader = importlib.machinery.SourceFileLoader(name, path)
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


D = load(DBCOPY, "lab_dbcopy")


def make_db(path, value, wal=True):
    c = sqlite3.connect(path)
    if wal:
        c.execute("PRAGMA journal_mode=WAL")
    c.execute("CREATE TABLE IF NOT EXISTS t (v TEXT)")
    c.execute("DELETE FROM t")
    c.execute("INSERT INTO t VALUES (?)", (value,))
    c.commit()
    c.close()


def db_value(path):
    c = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        return c.execute("SELECT v FROM t").fetchone()[0]
    finally:
        c.close()


def read(path):
    with open(path, "rb") as f:
        return f.read()


class Base(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.mkdtemp(prefix="labh2-")
        os.chmod(self.t, 0o700)
        self.data = os.path.join(self.t, "data")             # stands for /var/lib/lab (the gateway's)
        self.bk_root = os.path.join(self.t, "lab-backups")   # stands for /var/lib/lab-backups (root's, 0700)
        os.makedirs(self.data, mode=0o700)
        os.makedirs(self.bk_root, mode=0o700)
        self.victim = os.path.join(self.t, "root-file")      # stands for /etc/lab/lab.env, /root/.bashrc, ...
        with open(self.victim, "w") as f:
            f.write("ROOT ONLY\n")

    def tearDown(self):
        shutil.rmtree(self.t, ignore_errors=True)

    def victim_untouched(self):
        self.assertEqual(read(self.victim), b"ROOT ONLY\n")


class DbCopy(Base):
    def test_backup_and_restore_roundtrip(self):
        src = os.path.join(self.data, "lab.sqlite3")
        make_db(src, "live")
        rel = os.path.join(self.bk_root, "20261115-010000-abc1234")
        os.mkdir(rel, 0o700)
        D.backup(ME, src, os.path.join(rel, "lab.sqlite3"))
        self.assertEqual(os.stat(os.path.join(rel, "lab.sqlite3")).st_mode & 0o777, 0o600)
        self.assertEqual(db_value(os.path.join(rel, "lab.sqlite3")), "live")
        make_db(src, "changed")
        D.restore(ME, os.path.join(rel, "lab.sqlite3"), src)
        self.assertEqual(db_value(src), "live")
        self.assertEqual(os.stat(src).st_mode & 0o777, 0o600)

    def test_backup_refuses_symlinked_backup_dir(self):
        src = os.path.join(self.data, "lab.sqlite3")
        make_db(src, "live")
        elsewhere = os.path.join(self.t, "elsewhere")
        os.mkdir(elsewhere, 0o700)
        link = os.path.join(self.bk_root, "20261115-010000-abc1234")
        os.symlink(elsewhere, link)   # e.g. lab replaced the backups directory with a link to /
        with self.assertRaisesRegex(D.Fail, "not a real directory"):
            D.backup(ME, src, os.path.join(link, "lab.sqlite3"))
        self.assertEqual(os.listdir(elsewhere), [])
        os.chmod(self.bk_root, 0o770)   # writable by a group: not root's alone
        rel = os.path.join(self.bk_root, "r")
        os.mkdir(rel, 0o700)
        with self.assertRaisesRegex(D.Fail, "writable by group"):
            D.backup(ME, src, os.path.join(rel, "lab.sqlite3"))

    def test_backup_never_writes_through_a_planted_link(self):
        src = os.path.join(self.data, "lab.sqlite3")
        make_db(src, "payload\n/bin/sh -c 'id > /tmp/pwned'\n")
        rel = os.path.join(self.bk_root, "20261115-010000-abc1234")
        os.mkdir(rel, 0o700)
        os.symlink(self.victim, os.path.join(rel, "lab.sqlite3"))
        with self.assertRaises(OSError):
            D.backup(ME, src, os.path.join(rel, "lab.sqlite3"))
        self.victim_untouched()

    def test_backup_refuses_a_symlinked_database(self):
        real = os.path.join(self.t, "someone-elses.sqlite3")
        make_db(real, "not lab's")
        os.symlink(real, os.path.join(self.data, "lab.sqlite3"))
        rel = os.path.join(self.bk_root, "r")
        os.mkdir(rel, 0o700)
        code = D.main(["backup", "--as", ME, os.path.join(self.data, "lab.sqlite3"), os.path.join(rel, "lab.sqlite3")])
        self.assertEqual(code, 1)
        self.assertEqual(os.listdir(rel), [])   # nothing half-written is left behind
        self.assertEqual(D.main(["backup", "--as", ME, os.path.join(self.data, "none.sqlite3"),
                                 os.path.join(rel, "none.sqlite3")]), D.MISSING)

    def test_restore_never_writes_through_planted_links(self):
        rel = os.path.join(self.bk_root, "r")
        os.mkdir(rel, 0o700)
        good = os.path.join(rel, "lab.sqlite3")
        make_db(good, "backup", wal=False)
        dst = os.path.join(self.data, "lab.sqlite3")
        for sfx in ("", "-wal", "-shm", "-journal"):   # every name sqlite (or the old cp) would touch
            os.symlink(self.victim, dst + sfx)
        D.restore(ME, good, dst)
        self.victim_untouched()
        self.assertFalse(os.path.islink(dst))
        self.assertEqual(db_value(dst), "backup")
        for sfx in ("-wal", "-shm", "-journal"):
            self.assertFalse(os.path.lexists(dst + sfx), sfx)

    def test_restore_refuses_a_backup_that_is_a_link_or_in_a_shared_dir(self):
        rel = os.path.join(self.bk_root, "r")
        os.mkdir(rel, 0o700)
        os.symlink(self.victim, os.path.join(rel, "lab.sqlite3"))
        with self.assertRaises(OSError):   # O_NOFOLLOW
            D.restore(ME, os.path.join(rel, "lab.sqlite3"), os.path.join(self.data, "lab.sqlite3"))
        shared = os.path.join(self.t, "shared")
        os.mkdir(shared)
        os.chmod(shared, 0o777)
        make_db(os.path.join(shared, "lab.sqlite3"), "planted", wal=False)
        with self.assertRaisesRegex(D.Fail, "writable by group"):
            D.restore(ME, os.path.join(shared, "lab.sqlite3"), os.path.join(self.data, "lab.sqlite3"))
        self.assertFalse(os.path.lexists(os.path.join(self.data, "lab.sqlite3")))

    def test_acting_as_another_user_needs_root(self):
        with self.assertRaisesRegex(D.Fail, "only root"):
            D.user("root") if os.geteuid() else None
        if os.geteuid() == 0:   # pragma: no cover (CI runs unprivileged)
            with self.assertRaisesRegex(D.Fail, "refused"):
                D.user("root")

    def test_adopt_old_backups(self):
        old = os.path.join(self.data, "backups")
        os.mkdir(old, 0o700)
        good = os.path.join(old, "20261115-010000-aaaaaaa")
        os.mkdir(good, 0o700)
        make_db(os.path.join(good, "lab.sqlite3"), "old backup", wal=False)
        os.symlink(self.victim, os.path.join(good, "ai.sqlite3"))            # a link inside: dropped
        os.symlink(self.t, os.path.join(old, "20261115-020000-bbbbbbb"))     # a "release" that is a link: dropped
        with open(os.path.join(old, "junk"), "w") as f:
            f.write("x")
        self.assertEqual(D.adopt(old, self.bk_root), ["20261115-010000-aaaaaaa"])
        self.assertFalse(os.path.lexists(old))
        self.assertEqual(sorted(os.listdir(self.bk_root)), ["20261115-010000-aaaaaaa"])
        self.assertEqual(os.listdir(os.path.join(self.bk_root, "20261115-010000-aaaaaaa")), ["lab.sqlite3"])
        self.assertEqual(db_value(os.path.join(self.bk_root, "20261115-010000-aaaaaaa", "lab.sqlite3")), "old backup")
        self.victim_untouched()
        self.assertTrue(os.path.isdir(self.t))
        self.assertEqual(D.adopt(old, self.bk_root), [])   # nothing there any more: a no-op

    def test_adopt_drops_a_symlinked_or_shared_old_dir(self):
        target = os.path.join(self.t, "target")
        os.mkdir(target, 0o700)
        os.mkdir(os.path.join(target, "20261115-010000-aaaaaaa"), 0o700)
        old = os.path.join(self.data, "backups")
        os.symlink(target, old)   # lab: "backups" → a directory of its choosing (or /)
        self.assertEqual(D.adopt(old, self.bk_root), [])
        self.assertFalse(os.path.lexists(old))
        self.assertEqual(os.listdir(target), ["20261115-010000-aaaaaaa"])   # never followed, never deleted
        self.assertEqual(os.listdir(self.bk_root), [])
        os.mkdir(old)
        os.chmod(old, 0o777)
        os.mkdir(os.path.join(old, "20261115-010000-aaaaaaa"), 0o700)
        self.assertEqual(D.adopt(old, self.bk_root), [])
        self.assertEqual(os.listdir(self.bk_root), [])

    def test_prune_keeps_ten_releases_and_five_snapshots(self):
        for i in range(12):
            os.mkdir(os.path.join(self.bk_root, f"20261115-0100{i:02d}-abc1234"))
        for i in range(7):
            os.mkdir(os.path.join(self.bk_root, f"rollback-20261115-0200{i:02d}-from-20261115-010000-abc1234"))
        os.symlink(self.t, os.path.join(self.bk_root, ".adopt-1"))
        gone = D.prune(self.bk_root)
        self.assertEqual(len(gone), 4)
        left = os.listdir(self.bk_root)
        self.assertEqual(len([x for x in left if x.startswith("2026")]), 10)
        self.assertEqual(len([x for x in left if x.startswith("rollback-")]), 5)
        self.assertNotIn("20261115-010000-abc1234", left)   # the oldest went
        self.assertTrue(os.path.isdir(self.t))               # the leftover link was unlinked, not followed


class Rollback(Base):
    """deploy/lab-rollback --with-db with the LAB_* test overrides (fake systemctl, this user as lab and lab-c-ai)."""

    def setUp(self):
        super().setUp()
        self.rel = os.path.join(self.t, "releases")
        for r in ("20261115-010000-aaaaaaa", "20261115-020000-bbbbbbb"):
            os.makedirs(os.path.join(self.rel, r))
            with open(os.path.join(self.rel, r, "VERSION"), "w") as f:
                f.write("0.1.0\n")
        self.live = os.path.join(self.t, "lab")
        os.symlink(os.path.join(self.rel, "20261115-020000-bbbbbbb"), self.live)
        self.cdata = os.path.join(self.t, "connectors")
        os.makedirs(os.path.join(self.cdata, "ai"), mode=0o700)
        self.bk = os.path.join(self.bk_root, "20261115-020000-bbbbbbb")
        os.mkdir(self.bk, 0o700)
        make_db(os.path.join(self.bk, "lab.sqlite3"), "before the release", wal=False)
        make_db(os.path.join(self.bk, "ai.sqlite3"), "ai before", wal=False)
        make_db(os.path.join(self.data, "lab.sqlite3"), "after the release")
        make_db(os.path.join(self.cdata, "ai", "ai.sqlite3"), "ai after")
        self.sysctl = os.path.join(self.t, "systemctl")
        with open(self.sysctl, "w") as f:
            f.write(f'#!/bin/sh\necho "$*" >> {self.t}/systemctl.log\n[ "$1" = is-active ] && exit 3\nexit 0\n')
        os.chmod(self.sysctl, 0o755)

    def run_rb(self, *args):
        env = {**os.environ, "LAB_RELEASES": self.rel, "LAB_LIVE": self.live, "LAB_BACKUPS": self.bk_root,
               "LAB_DATA": self.data, "LAB_CONNECTOR_DATA": self.cdata, "LAB_USER": ME, "LAB_AI_USER": ME,
               "LAB_DBCOPY": DBCOPY, "LAB_SYSTEMCTL": self.sysctl, "LAB_DEPLOY_LOCK": os.path.join(self.t, "lock")}
        return subprocess.run(["sh", ROLLBACK, *args], env=env, capture_output=True, text=True, timeout=60)

    def live_release(self):
        return os.path.basename(os.path.realpath(self.live))

    def test_with_db_restores_without_following_planted_links(self):
        """The victim stands for root's file: 0400, so 'lab' (this user) can't write it — just like the real thing."""
        dst = os.path.join(self.data, "lab.sqlite3")
        os.chmod(self.victim, 0o400)
        for name in (f"lab.sqlite3.before-rollback-{n}" for n in range(1700000000, 1700000000 + 3)):
            os.symlink(self.victim, os.path.join(self.data, name))   # the old `cp dst dst.before-rollback-<ts>`
        for sfx in ("-shm", "-journal"):
            os.symlink(self.victim, dst + sfx)
        p = self.run_rb("--with-db")
        self.assertEqual(p.returncode, 0, (p.stdout + p.stderr)[-2000:])
        self.victim_untouched()
        self.assertEqual(db_value(dst), "before the release")
        for sfx in ("-shm", "-journal"):
            self.assertFalse(os.path.lexists(dst + sfx))

    def test_with_db_restores_and_keeps_a_snapshot(self):
        dst = os.path.join(self.data, "lab.sqlite3")
        p = self.run_rb("--with-db")
        self.assertEqual(p.returncode, 0, (p.stdout + p.stderr)[-2000:])
        self.assertEqual(self.live_release(), "20261115-010000-aaaaaaa")
        self.assertEqual(db_value(dst), "before the release")
        self.assertEqual(db_value(os.path.join(self.cdata, "ai", "ai.sqlite3")), "ai before")
        snaps = [x for x in os.listdir(self.bk_root) if x.startswith("rollback-")]
        self.assertEqual(len(snaps), 1)   # what was replaced, in root's tree
        self.assertEqual(db_value(os.path.join(self.bk_root, snaps[0], "lab.sqlite3")), "after the release")
        self.assertEqual(os.stat(os.path.join(self.bk_root, snaps[0])).st_mode & 0o777, 0o700)
        self.assertEqual(sorted(os.listdir(self.data)), ["lab.sqlite3"])   # nothing else is made in lab's directory

    def test_with_db_refuses_a_symlinked_backup_dir(self):
        shutil.rmtree(self.bk)
        evil = os.path.join(self.t, "evil")
        os.mkdir(evil, 0o700)
        make_db(os.path.join(evil, "lab.sqlite3"), "attacker's", wal=False)
        os.symlink(evil, self.bk)
        p = self.run_rb("--with-db")
        self.assertEqual(p.returncode, 1)
        self.assertIn("no usable database backup", p.stdout)
        self.assertEqual(self.live_release(), "20261115-020000-bbbbbbb")   # nothing changed
        self.assertEqual(db_value(os.path.join(self.data, "lab.sqlite3")), "after the release")
        self.assertFalse(os.path.exists(os.path.join(self.t, "systemctl.log")) and
                         "stop" in read(os.path.join(self.t, "systemctl.log")).decode())

    def test_with_db_refuses_a_backup_tree_others_can_write(self):
        os.chmod(self.bk_root, 0o777)
        p = self.run_rb("--with-db")
        self.assertEqual(p.returncode, 1)
        self.assertEqual(self.live_release(), "20261115-020000-bbbbbbb")

    def test_a_link_inside_the_backup_is_not_restored(self):
        os.remove(os.path.join(self.bk, "lab.sqlite3"))
        other = os.path.join(self.t, "other.sqlite3")
        make_db(other, "linked", wal=False)
        os.symlink(other, os.path.join(self.bk, "lab.sqlite3"))
        p = self.run_rb("--with-db")
        self.assertEqual(p.returncode, 0, (p.stdout + p.stderr)[-2000:])
        self.assertEqual(db_value(os.path.join(self.data, "lab.sqlite3")), "after the release")

    def test_list_shows_versions(self):
        with open(os.path.join(self.rel, "20261115-020000-bbbbbbb", "COMMIT"), "w") as f:
            f.write("bbbbbbbcafe\n")
        p = self.run_rb("--list")
        self.assertIn("  20261115-010000-aaaaaaa  0.1.0\n", p.stdout)        # no COMMIT (before step 17)
        self.assertIn("* 20261115-020000-bbbbbbb  0.1.0 bbbbbbb\n", p.stdout)

    def test_without_db_leaves_databases_alone(self):
        p = self.run_rb()
        self.assertEqual(p.returncode, 0, (p.stdout + p.stderr)[-2000:])
        self.assertEqual(self.live_release(), "20261115-010000-aaaaaaa")
        self.assertEqual(db_value(os.path.join(self.data, "lab.sqlite3")), "after the release")


class HelperWithDb(unittest.TestCase):
    """The update helper takes with_db only from a root peer; the gateway (group lab) can't forge that."""

    def ask(self, req, stdin):
        p = subprocess.Popen([sys.executable, HELPER], stdin=stdin, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return p

    def test_socket_peer_not_root_is_refused(self):
        H = load(HELPER, "lab_update_helper_h2")
        a, b = socket.socketpair()
        try:
            self.assertEqual(H.peer_uid(a.fileno()), os.geteuid())
            r, w = os.pipe()
            self.assertIsNone(H.peer_uid(r))
            os.close(r)
            os.close(w)
            p = subprocess.Popen([sys.executable, HELPER], stdin=b.fileno(), stdout=b.fileno(),
                                 stderr=subprocess.DEVNULL)
            a.sendall(json.dumps({"op": "rollback", "with_db": True, "by": "boss"}).encode() + b"\n")
            out = b""
            a.settimeout(30)
            while not out.endswith(b"\n"):
                chunk = a.recv(4096)
                if not chunk:
                    break
                out += chunk
            p.wait(timeout=30)
        finally:
            a.close()
            b.close()
        ans = json.loads(out)
        if os.geteuid() != 0:
            self.assertEqual(ans, {"ok": False, "error": H.WITH_DB_ROOT_ONLY})

    def test_pipe_is_refused_too(self):
        out = subprocess.run([sys.executable, HELPER], input=b'{"op": "rollback", "with_db": true}\n',
                             capture_output=True, timeout=30)
        self.assertIn("only possible as root", json.loads(out.stdout)["error"])


class Scripts(unittest.TestCase):
    """What runs as root on install/apply: no by-name chmod/chown/rm/copy inside lab's (or a connector's) directory."""

    def src(self, *p):
        with open(os.path.join(ROOT, *p), encoding="utf-8") as f:
            return f.read()

    def test_install_sh(self):
        sh = self.src("deploy", "install.sh")
        code = [ln for ln in sh.splitlines() if not ln.lstrip().startswith("#")]
        for ln in code:
            if re.search(r"\b(chmod|chown|rm -rf|cp|install -d|xargs)\b", ln) and "/var/lib/lab/" in ln:
                self.assertIn("runuser -u lab", ln, ln[:200])   # only ever done AS lab
            if "lab-connectors" in ln or "$D" in ln:
                self.assertNotIn("chown -R", ln, ln[:200])     # never a whole tree its user controls
        self.assertNotIn("/var/lib/lab/backups/$", sh)
        self.assertIn("lab-dbcopy adopt /var/lib/lab/backups", sh)
        self.assertIn("lab-dbcopy backup --as", sh)
        self.assertIn('install -d -o root -g root -m 700 "$BK_ROOT"', sh)
        self.assertIn('install -m 755 "$SRC/deploy/lab-dbcopy" /usr/local/sbin/lab-dbcopy', sh)
        self.assertNotRegex(sh, r"echo .*\$SETUP")   # the setup link itself is not printed into a job log

    def test_rollback_script(self):
        sh = self.src("deploy", "lab-rollback")
        self.assertNotRegex(sh, r"\bcp\b")
        self.assertNotRegex(sh, r"install -o")
        self.assertIn('"$DBCOPY" restore --as', sh)

    def test_lab_admin_drops_root_before_the_database(self):
        src = self.src("gateway", "lab_admin.py")
        self.assertNotIn("_db_owner_back", src)
        main = src[src.index("def main():"):]
        self.assertLess(main.index("_drop_to_lab()"), main.index("Store(config.DB)"))
        self.assertLess(main.index("_drop_to_lab()"), main.index("return config_cmd(args)"))
        self.assertLess(main.index("_drop_to_lab()"), main.index("return modules(args)"))
        # setup-link: the database part runs in a child that dropped to lab
        self.assertIn("_as_lab_child(lambda: _mint_setup_link(", src)

    def test_gateway_does_not_log_the_setup_link(self):
        src = self.src("gateway", "lab", "server.py")
        serve = src[src.index("    app = App()"):]
        self.assertNotIn("first_run_notice(", serve)
        self.assertNotIn("/setup#", serve)


class SetupLink(unittest.TestCase):
    """Review L2: lab-admin setup-link prints the link and keeps it in a 0600 file; with an owner, the file goes."""

    def test_setup_link_file(self):
        t = tempfile.mkdtemp(prefix="labsetup-")
        try:
            env = {**os.environ, "LAB_DB": os.path.join(t, "lab.sqlite3"), "LAB_SETUP_LINK_FILE": os.path.join(t, "setup-link"),
                   "LAB_PUBLIC_URL": "https://door.example", "LAB_ALLOW_NONROOT": "1", "LAB_MODULES": os.path.join(t, "m")}
            run = lambda *more: subprocess.run([sys.executable, os.path.join(ROOT, "gateway", "lab_admin.py"),  # noqa: E731
                                                "setup-link", *more], env=env, capture_output=True, text=True, timeout=60)
            p = run()
            self.assertEqual(p.returncode, 0, p.stderr)
            link = re.search(r"https://door\.example/setup#\S+", p.stdout).group(0)
            self.assertEqual(read(os.path.join(t, "setup-link")).decode().strip(), link)
            self.assertEqual(os.stat(os.path.join(t, "setup-link")).st_mode & 0o777, 0o600)
            sys.path.insert(0, os.path.join(ROOT, "gateway"))
            from lab.store import Store, _hash
            st = Store(os.path.join(t, "lab.sqlite3"))
            self.assertTrue(st.setup_token_valid(link.split("#", 1)[1]))
            self.assertEqual(st.q("SELECT COUNT(*) AS n FROM setup_tokens WHERE token_hash=?",
                                  (_hash(link.split("#", 1)[1]),))[0]["n"], 1)
            st.upsert_user("boss", "", "", [], "owner")
            p = run()
            self.assertNotEqual(p.returncode, 0)
            self.assertIn("an owner exists already", p.stderr)
            self.assertFalse(os.path.lexists(os.path.join(t, "setup-link")))
            # the only owner is demoted (rolesync, an IdP group change): setup stays closed, even for root's plain
            # setup-link (install.sh runs that on every install) — only --recover makes a link
            st.set_role("boss", "admin")
            p = run()
            self.assertNotEqual(p.returncode, 0)
            self.assertIn("setup-link --recover", p.stderr)
            self.assertFalse(os.path.lexists(os.path.join(t, "setup-link")))
            p = run("--recover")
            self.assertEqual(p.returncode, 0, p.stderr)
            self.assertTrue(st.setup_token_valid(re.search(r"/setup#(\S+)", p.stdout).group(1)))
            self.assertIn("setup-link-recover", [r["action"] for r in st.audit_list(5)])
        finally:
            shutil.rmtree(t, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
