"""The media modules' route allow-lists (sonarr, radarr, prowlarr, bazarr): which verb/path/body/query each role may
send. Nothing here talks to a backend; it only asks the gateway's registry (the same checks the proxy runs).

Run:  python3 -m unittest discover -s tests -p 'test_arr_routes.py'"""
import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "gateway"))

from lab.registry import Registry  # noqa: E402

CFG = {m: {"url": f"http://{m}.example:1", "api_key": "<set>", "verify_tls": True} for m in ("sonarr", "radarr", "prowlarr", "bazarr")}
OWNER, ADMIN, GUEST = ({"username": "u", "role": r} for r in ("owner", "admin", "guest"))
# what the UI sends for each command ($lab/arr/: actions, ItemDetail, ManualImport → importPayload)
Q = {"quality": {"id": 7, "name": "Bluray-1080p", "source": "bluray", "resolution": 1080, "modifier": "none"},
     "revision": {"version": 1, "real": 0, "isRepack": False}}
SFILE = {"path": "/data/downloads/Show.S01/Show.S01E01.mkv", "seriesId": 7, "episodeIds": [71], "releaseType": "singleEpisode",
         "quality": Q, "languages": [{"id": 1, "name": "English"}], "releaseGroup": "G", "indexerFlags": 0, "downloadId": "ABC"}
MFILE = {"path": "/data/downloads/M.2026/M.2026.mkv", "movieId": 3, "quality": Q, "languages": [], "releaseGroup": None,
         "indexerFlags": 0, "downloadId": "D9"}
CMD = {"EpisodesSearch": {"episodeIds": [4]}, "SeasonSearch": {"seriesId": 1, "seasonNumber": 2}, "SeriesSearch": {"seriesId": 1},
       "MissingEpisodeSearch": {}, "RefreshSeries": {}, "MoviesSearch": {"movieIds": [9]}, "MissingMoviesSearch": {},
       "RefreshMovie": {}, "ManualImport": None}


class ArrRoutes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.reg = Registry(os.path.join(ROOT, "modules"))
        cls.reg.apply(overrides={m: {"import_paths": ["/data/downloads/"]} for m in ("sonarr", "radarr")}, config=CFG)
        assert cls.reg.errors == {}, cls.reg.errors

    def route(self, mid, method, path):
        return Registry.find_route(self.reg.get(mid), method, path)

    def verdict(self, mid, method, path, user=None):
        return Registry.permission(self.route(mid, method, path), user or ADMIN)

    def body(self, mid, method, path, raw):
        r = self.route(mid, method, path)
        return Registry.body_ok(r, raw.encode())

    def query(self, mid, method, path, q):
        return Registry.query_ok(self.route(mid, method, path), q)

    def test_connection_comes_from_config(self):
        for mid in ("sonarr", "radarr", "prowlarr", "bazarr"):
            self.assertEqual(self.reg.get(mid)["backend"]["url"], f"http://{mid}.example:1")
            self.assertNotIn("10.0.", str(self.reg.get(mid)["backend"]))
        self.assertEqual(self.reg.get("sonarr")["backend"]["auth"]["secret"], "api_key")
        self.assertEqual(self.reg.get("bazarr")["backend"]["auth"]["name"], "X-API-KEY")

    def test_command_names_are_the_ones_we_need(self):
        for mid, ok, bad in (
            ("sonarr", ["EpisodesSearch", "SeasonSearch", "SeriesSearch", "ManualImport", "MissingEpisodeSearch", "RefreshSeries"],
             ["MoviesSearch", "Backup", "DeleteLogFiles", "ResetApiKey", "RenameSeries", "ApplicationUpdate"]),
            ("radarr", ["MoviesSearch", "ManualImport", "MissingMoviesSearch", "RefreshMovie"],
             ["EpisodesSearch", "Backup", "ApplicationUpdate", "RenameMovie"]),
        ):
            CMD["ManualImport"] = {"files": [SFILE if mid == "sonarr" else MFILE], "importMode": "auto"}
            for name in ok:
                self.assertEqual(self.verdict(mid, "POST", "/api/v3/command"), "yes")
                self.assertTrue(self.body(mid, "POST", "/api/v3/command", json.dumps({"name": name, **CMD[name]})), name)
                self.assertFalse(self.body(mid, "POST", "/api/v3/command", json.dumps({"name": name, **CMD[name], "x": 1})), name)
            for name in bad:
                self.assertFalse(self.body(mid, "POST", "/api/v3/command", f'{{"name": "{name}"}}'), name)
            self.assertFalse(self.body(mid, "POST", "/api/v3/command", '{"name": "ManualImport", "Name": "Backup"}'))
            self.assertFalse(self.body(mid, "POST", "/api/v3/command", '{"name": "manualimport", "files": []}'))  # exact name
            self.assertEqual(self.verdict(mid, "POST", "/api/v3/command", GUEST), "no")

    def test_manual_import_body(self):
        """ManualImport (body_schema): only files inside the allowed folders, only the fields the UI sends, right types."""
        def ok(mid, cmd):
            return self.body(mid, "POST", "/api/v3/command", json.dumps(cmd) if not isinstance(cmd, str) else cmd)

        def mi(f, **top):
            return {"name": "ManualImport", "files": [f], "importMode": "auto", **top}
        for mid, f in (("sonarr", SFILE), ("radarr", MFILE)):
            self.assertTrue(ok(mid, mi(f)))
            self.assertTrue(ok(mid, {"name": "ManualImport", "files": [f, {**f, "quality": None, "languages": None}]}))
            bad = [
                # paths: outside the folders, traversal, look-alike folder, relative, backslash, NUL, not text
                {**f, "path": "/etc/shadow"}, {**f, "path": "/data/downloads/../../etc/passwd"},
                {**f, "path": "/data/downloads/./x.mkv"}, {**f, "path": "/data/downloads//x.mkv"},
                {**f, "path": "/data/downloads-evil/x.mkv"}, {**f, "path": "data/downloads/x.mkv"},
                {**f, "path": "/data/downloads/x\\..\\y.mkv"}, {**f, "path": "/data/downloads/x\u0000.mkv"},
                {**f, "path": "/data/downloads"}, {**f, "path": ["/data/downloads/x.mkv"]}, {**f, "path": None},
                # extra keys, at every level
                {**f, "folder": "/"}, {**f, "quality": {**Q, "x": 1}}, {**f, "quality": {"quality": {"id": 1, "evil": True}}},
                {**f, "languages": [{"id": 1, "name": "x", "more": {}}]},
                # wrong types
                {**f, "indexerFlags": "0"}, {**f, "indexerFlags": True}, {**f, "indexerFlags": 1.5},
                {**f, "quality": "Bluray-1080p"}, {**f, "languages": {"id": 1}}, {**f, "releaseGroup": 5},
                # deeper nesting than the schema knows
                {**f, "quality": {"quality": {"id": {"id": 1}}}}, {**f, "languages": [[{"id": 1}]]},
                # required fields
                {k: v for k, v in f.items() if k != "path"},
            ]
            if mid == "sonarr":
                bad += [{**f, "episodeIds": []}, {**f, "episodeIds": "71"}, {**f, "episodeIds": [71.0]},
                        {**f, "episodeIds": [True]}, {**f, "seriesId": -1}, {**f, "movieId": 3}]
            else:
                bad += [{**f, "movieId": "3"}, {**f, "seriesId": 7}, {k: v for k, v in f.items() if k != "movieId"}]
            for i, b in enumerate(bad):
                self.assertFalse(ok(mid, mi(b)), f"{mid} bad[{i}]: {str(b)[:120]}")
            # top level: files not a list, empty, too many, extra fields, other import modes, case-variant duplicates
            for top in ({"name": "ManualImport", "files": f}, {"name": "ManualImport", "files": "x"},
                        {"name": "ManualImport", "files": []}, {"name": "ManualImport", "files": [f] * 201},
                        {"name": "ManualImport"}, mi(f, sendUpdatesToClient=True), mi(f, importMode="move"),
                        mi(f, importMode="copy"), {"name": "ManualImport", "files": [f], "importMode": None},
                        [mi(f)], "null", '"ManualImport"'):
                self.assertFalse(ok(mid, top), str(top)[:120])
            raw = json.dumps(mi(f))
            self.assertFalse(ok(mid, raw[:-1] + ', "Files": []}'))                      # case-variant duplicate key
            self.assertFalse(ok(mid, raw.replace('"indexerFlags": 0', '"indexerFlags": NaN')))
            self.assertFalse(ok(mid, "[" * 5000 + "]" * 5000))                        # deep nesting: refused, no crash
            self.assertFalse(ok(mid, raw.encode("utf-16").decode("latin-1")))
            # the route takes no query string beside the body (Proxmox-style merging)
            self.assertFalse(self.query(mid, "POST", "/api/v3/command", "name=Backup"))

    def test_manual_import_needs_folders(self):
        """No import_paths setting = no ManualImport at all (the other commands still work)."""
        reg = Registry(os.path.join(ROOT, "modules"))
        reg.apply(overrides={}, config=CFG)
        for mid, f in (("sonarr", SFILE), ("radarr", MFILE)):
            r = Registry.find_route(reg.get(mid), "POST", "/api/v3/command")
            self.assertFalse(Registry.body_ok(r, json.dumps({"name": "ManualImport", "files": [f]}).encode()))
            self.assertTrue(Registry.body_ok(r, b'{"name": "CheckHealth"}'))
            self.assertIn("outside the allowed folders",
                          Registry.body_problem(r, json.dumps({"name": "ManualImport", "files": [f]}).encode()))

    def test_interactive_search_and_grab(self):
        for mid, q in (("sonarr", "episodeId=4&seriesId=1&seasonNumber=2"), ("radarr", "movieId=9")):
            self.assertEqual(self.verdict(mid, "GET", "/api/v3/release"), "yes")
            self.assertTrue(self.query(mid, "GET", "/api/v3/release", q))
            self.assertFalse(self.query(mid, "GET", "/api/v3/release", "episodeId=1&movieId=1&download=true" if mid == "sonarr" else "movieId=1&episodeId=1"))
            self.assertEqual(self.verdict(mid, "POST", "/api/v3/release"), "yes")
            self.assertTrue(self.body(mid, "POST", "/api/v3/release", '{"guid": "g", "indexerId": 3}'))
            self.assertFalse(self.body(mid, "POST", "/api/v3/release", '{"guid": "g", "indexerId": 3, "downloadClientId": 7}'))
            self.assertFalse(self.body(mid, "POST", "/api/v3/release", '{"guid": "g", "indexerId": 3, "indexerId": 4}'))  # duplicate key
            self.assertEqual(self.verdict(mid, "POST", "/api/v3/release", GUEST), "no")
            self.assertIsNone(self.route(mid, "PUT", "/api/v3/release"))
            self.assertIsNone(self.route(mid, "POST", "/api/v3/release/push"))

    def test_manual_import_candidates_never_take_a_folder(self):
        for mid, extra in (("sonarr", "seriesId=1"), ("radarr", "movieId=1")):
            self.assertTrue(self.query(mid, "GET", "/api/v3/manualimport", f"downloadId=ABC&filterExistingFiles=true&{extra}"))
            self.assertFalse(self.query(mid, "GET", "/api/v3/manualimport", "folder=/etc"))  # would list any directory
            self.assertFalse(self.query(mid, "GET", "/api/v3/manualimport", "downloadId=A&folder=/"))
            self.assertIsNone(self.route(mid, "POST", "/api/v3/manualimport"))
            self.assertIsNone(self.route(mid, "PUT", "/api/v3/manualimport"))

    def test_edit_is_the_editor_endpoint_only(self):
        s, r = "sonarr", "radarr"
        self.assertEqual(self.verdict(s, "PUT", "/api/v3/series/editor"), "yes")
        self.assertTrue(self.body(s, "PUT", "/api/v3/series/editor", '{"seriesIds": [1], "monitored": false, "qualityProfileId": 4}'))
        self.assertFalse(self.body(s, "PUT", "/api/v3/series/editor", '{"seriesIds": [1], "rootFolderPath": "/", "moveFiles": true}'))
        self.assertFalse(self.body(s, "PUT", "/api/v3/series/editor", '{"seriesIds": [1], "deleteFiles": true}'))
        self.assertIsNone(self.route(s, "PUT", "/api/v3/series/1"))  # the full-object PUT can move the series folder
        self.assertTrue(self.body(r, "PUT", "/api/v3/movie/editor", '{"movieIds": [1], "monitored": true, "minimumAvailability": "released"}'))
        self.assertFalse(self.body(r, "PUT", "/api/v3/movie/editor", '{"movieIds": [1], "rootFolderPath": "/"}'))
        self.assertIsNone(self.route(r, "PUT", "/api/v3/movie/1"))
        self.assertTrue(self.body(s, "PUT", "/api/v3/episode/monitor", '{"episodeIds": [1, 2], "monitored": true}'))
        self.assertFalse(self.body(s, "PUT", "/api/v3/episode/monitor", '{"episodeIds": [1], "monitored": true, "x": 1}'))
        self.assertFalse(self.query(s, "PUT", "/api/v3/episode/monitor", "includeImages=true"))
        self.assertEqual(self.verdict(s, "PUT", "/api/v3/series/editor", GUEST), "no")

    def test_delete_is_owner_only_and_admin_must_ask(self):
        for mid, item in (("sonarr", "series"), ("radarr", "movie")):
            p = f"/api/v3/{item}/12"
            self.assertEqual(self.verdict(mid, "DELETE", p, OWNER), "yes")
            self.assertEqual(self.verdict(mid, "DELETE", p, ADMIN), "ask")
            self.assertEqual(self.verdict(mid, "DELETE", p, GUEST), "no")
            self.assertTrue(self.query(mid, "DELETE", p, "deleteFiles=true&addImportListExclusion=false"))
            self.assertTrue(self.query(mid, "DELETE", p, "deleteFiles=false"))
            self.assertFalse(self.query(mid, "DELETE", p, "deleteFiles=true&other=1"))
            self.assertIsNone(self.route(mid, "DELETE", f"/api/v3/{item}"))  # no bulk delete
            self.assertIsNone(self.route(mid, "DELETE", f"/api/v3/{item}/editor/x"))
            self.assertEqual(self.verdict(mid, "DELETE", "/api/v3/queue/5", ADMIN), "yes")  # removing a download stays admin
            self.assertTrue(self.query(mid, "DELETE", "/api/v3/queue/5", "removeFromClient=true&blocklist=true&skipRedownload=false"))
            self.assertFalse(self.query(mid, "DELETE", "/api/v3/queue/5", "removeFromClient=true&changeCategory=true&x=1"))

    def test_library_reads_and_nothing_else(self):
        self.assertEqual(self.verdict("sonarr", "GET", "/api/v3/series"), "yes")
        self.assertEqual(self.verdict("sonarr", "GET", "/api/v3/episode"), "yes")
        self.assertTrue(self.query("sonarr", "GET", "/api/v3/episode", "seriesId=3"))
        self.assertFalse(self.query("sonarr", "GET", "/api/v3/episode", "seriesId=3&includeEpisodeFile=true"))
        self.assertEqual(self.verdict("radarr", "GET", "/api/v3/movie"), "yes")
        self.assertIsNone(self.route("radarr", "POST", "/api/v3/movie"))   # adding a movie is not offered
        self.assertIsNone(self.route("sonarr", "POST", "/api/v3/series"))
        self.assertIsNone(self.route("sonarr", "GET", "/api/v3/config/host"))  # holds the API key
        self.assertIsNone(self.route("sonarr", "GET", "/api/v3/downloadclient"))

    def test_prowlarr_indexer_config_stays_owner_only_secret(self):
        r = self.route("prowlarr", "GET", "/api/v1/indexer")
        self.assertTrue(r["owner_only"] and r["secret"])
        self.assertEqual(Registry.permission(r, OWNER), "yes")
        self.assertEqual(Registry.permission(r, ADMIN), "ask")  # a secret read: the admin needs the owner's approval
        self.assertEqual(self.verdict("prowlarr", "POST", "/api/v1/indexer/testall"), "yes")
        self.assertTrue(self.body("prowlarr", "POST", "/api/v1/command", '{"name": "CheckHealth"}'))
        self.assertFalse(self.body("prowlarr", "POST", "/api/v1/command", '{"name": "ResetApiKey"}'))

    def test_bazarr_queries(self):
        self.assertTrue(self.query("bazarr", "POST", "/api/system/tasks", "taskid=update_series"))
        self.assertFalse(self.query("bazarr", "POST", "/api/system/tasks", "taskid=x&other=1"))
        self.assertTrue(self.query("bazarr", "POST", "/api/providers", "action=reset"))
        self.assertFalse(self.query("bazarr", "POST", "/api/providers", "action=reset&x=1"))
        self.assertEqual(self.verdict("bazarr", "POST", "/api/system/tasks", GUEST), "no")

    def test_the_hub_has_no_backend_and_only_optional_requires(self):
        hub = self.reg.get("arr")
        self.assertEqual(hub["routes"], [])
        self.assertTrue(hub["requires"] and all(r["optional"] for r in hub["requires"]))


if __name__ == "__main__":
    unittest.main()
