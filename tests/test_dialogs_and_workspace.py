"""Dialogs, dataset deletion, and workspace management.

The dialog tests run against a stub that speaks the same contract as the
Electron endpoint, so they exercise the client without popping a modal on
someone's screen. If a real desktop app is running, its live endpoint is
additionally checked for auth and binding.

Run: python3 tests/test_dialogs_and_workspace.py
"""
import json
import os
import shutil
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print(f"  {'ok  ' if cond else 'FAIL'}  {name}  {detail}")


# --------------------------------------------------------------- dialog stub

TOKEN = "test-token-123"
NEXT_REPLY = {"paths": []}
SEEN = {}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        url = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        SEEN.clear()
        SEEN.update(q)
        if q.get("token") != TOKEN:
            body, code = {"error": "forbidden"}, 403
        elif url.path != "/pick":
            body, code = {"error": "not found"}, 404
        else:
            body, code = NEXT_REPLY, 200
        raw = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


def start_stub():
    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def test_dialog_client(tmp):
    from src.common import common

    server = start_stub()
    port = server.server_address[1]
    os.environ["FLASHAPP_DIALOG_PORT"] = str(port)
    os.environ["FLASHAPP_DIALOG_TOKEN"] = TOKEN
    try:
        sample = tmp / "picked.mzML"
        sample.write_bytes(b"x")

        global NEXT_REPLY
        NEXT_REPLY = {"paths": [str(sample)]}
        got = common.electron_dialog(file_types=["mzML", "tsv"], title="Pick data")
        check("dialog returns the chosen paths as Path objects",
              got == [sample] and all(isinstance(p, Path) for p in got), str(got))
        check("dialog passes the auth token", SEEN.get("token") == TOKEN)
        check("dialog passes the file-type filter", SEEN.get("types") == "mzML,tsv",
              SEEN.get("types", ""))
        check("dialog passes the title", SEEN.get("title") == "Pick data")

        NEXT_REPLY = {"paths": []}
        check("cancel yields no paths", common.electron_dialog() == [])

        NEXT_REPLY = {"paths": [str(tmp)]}
        got = common.electron_dialog(directory=True)
        check("directory mode is requested", SEEN.get("directory") == "1")
        check("directory selection returns a path", got == [tmp], str(got))

        # A wrong token must not yield paths.
        os.environ["FLASHAPP_DIALOG_TOKEN"] = "wrong"
        check("a bad token yields no paths", common.electron_dialog() == [])
        os.environ["FLASHAPP_DIALOG_TOKEN"] = TOKEN

        # Outside the desktop shell there is no endpoint at all.
        del os.environ["FLASHAPP_DIALOG_PORT"]
        check("no dialog endpoint yields no paths, no exception",
              common.electron_dialog() == [])
        os.environ["FLASHAPP_DIALOG_PORT"] = str(port)

        # An unreachable endpoint must not raise out of the page.
        os.environ["FLASHAPP_DIALOG_PORT"] = "1"
        check("unreachable endpoint is handled", common.electron_dialog() == [])
    finally:
        server.shutdown()
        os.environ.pop("FLASHAPP_DIALOG_PORT", None)
        os.environ.pop("FLASHAPP_DIALOG_TOKEN", None)


def test_live_endpoint():
    """If the packaged app is running, check its endpoint is not open."""
    import subprocess
    try:
        out = subprocess.run(
            ["pgrep", "-f", "FLASHApp.app/Contents/Resources/runtime/bin/python3"],
            capture_output=True, text=True, timeout=10)
        pid = out.stdout.split()[0] if out.stdout.strip() else None
        if not pid:
            return
        env = subprocess.run(["ps", "-E", "-p", pid, "-o", "command="],
                             capture_output=True, text=True, timeout=10).stdout
        port = next((t.split("=", 1)[1] for t in env.split()
                     if t.startswith("FLASHAPP_DIALOG_PORT=")), None)
        if not port:
            return
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/pick", timeout=5)
            check("live dialog endpoint rejects a missing token", False, "returned 200")
        except urllib.error.HTTPError as e:
            check("live dialog endpoint rejects a missing token", e.code == 403,
                  f"HTTP {e.code}")
    except Exception:
        pass


# ------------------------------------------------------ deletion & workspaces

def test_deletion(tmp):
    from src.workflow.FileManager import FileManager

    ws = tmp / "ws"
    cache = ws / "cache"
    cache.mkdir(parents=True)
    user_file = tmp / "mine" / "keep_me.mzML"
    user_file.parent.mkdir(parents=True)
    user_file.write_bytes(b"precious")

    fm = FileManager(ws, cache)
    fm.store_file("ds1", "out_deconv_mzML", user_file, remove=False)
    fm.store_data("ds1", "deconv_dfs", pd.DataFrame({"a": [1]}))
    fm.store_data("ds2", "deconv_dfs", pd.DataFrame({"a": [2]}))

    check("both datasets are listed",
          set(fm.get_results_list(["deconv_dfs"])) == {"ds1", "ds2"})

    fm.remove_results("ds1")
    check("deleting one dataset removes only that one",
          fm.get_results_list(["deconv_dfs"]) == ["ds2"],
          str(fm.get_results_list(["deconv_dfs"])))
    check("deleting a dataset does not delete the user's source file",
          user_file.exists())
    check("deleted dataset is gone from the index",
          not fm.result_exists("ds1", "deconv_dfs"))

    # Deleting twice must not explode: a linked dataset has no directory.
    try:
        fm.remove_results("ds1")
        check("deleting an already-deleted dataset is harmless", True)
    except Exception as exc:  # noqa: BLE001
        check("deleting an already-deleted dataset is harmless", False, repr(exc))

    fm.clear_cache()
    check("clear_cache empties the index", fm.get_results_list(["deconv_dfs"]) == [])
    check("clear_cache does not delete the user's source file", user_file.exists())


def test_workspace_names():
    from src.common.common import valid_workspace_name

    destructive = ["/Users/me/Documents", "..", "../..", "/", "a/b", "a\\b",
                   "", "   ", ".", ".hidden"]
    for bad in destructive:
        check(f"workspace name refused: {bad!r}", valid_workspace_name(bad) == "")
    for good in ("default", "my-run", "run_2026"):
        check(f"workspace name accepted: {good!r}", valid_workspace_name(good) == good)

    root = Path("..", "workspaces-FLASHViewer")
    escapes = [c for c in destructive
               if (root / (valid_workspace_name(c) or "default")).resolve()
               not in list((root / "x").resolve().parents) + [(root / "default").resolve()]
               and root.resolve() not in (root / (valid_workspace_name(c) or "default")).resolve().parents]
    check("no rejected name can escape the workspaces directory", not escapes, str(escapes))


def main():
    tmp = Path(tempfile.mkdtemp(prefix="flashapp-dialogs-"))
    try:
        print("dialogs")
        test_dialog_client(tmp)
        test_live_endpoint()
        print("\ndataset deletion")
        test_deletion(tmp)
        print("\nworkspace management")
        test_workspace_names()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    failed = [n for n, ok, _ in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed")
    if failed:
        print("failed: " + ", ".join(failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
