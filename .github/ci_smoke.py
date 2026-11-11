"""Real install on a real macOS / Windows machine: hooks, login service, proxy, uninstall.

There is no Databricks workspace in CI, so the proxy cannot sign in. Everything else is real:
the installer writes the user-level hooks and starts the login service; we check that every
hook blocks a SQL query in every shell, that the service is listening, and that it refuses
a SQL statement request. Then we uninstall.
"""
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
home = Path.home()
cfg = home / ".databrickscfg"
if not cfg.exists():
    cfg.write_text("[DEFAULT]\nhost = https://dbc-ci-example.cloud.databricks.com\ntoken = not-a-real-token\n")

repo = Path(tempfile.mkdtemp()) / "project"
repo.mkdir()
py = sys.executable


def run(*args):
    print("\n$ " + " ".join(map(str, args)), flush=True)
    r = subprocess.run([str(a) for a in args], capture_output=True, text=True)
    print(r.stdout + r.stderr, flush=True)
    return r


failures = []
r = run(py, ROOT / "install.py", repo, "--skip-doctor", "--skip-databricks-check")
if r.returncode != 0:
    failures.append("installer failed")

svc = home / ".databricks-guard" / "bin" / "proxy_service.py"
for _ in range(30):
    if run(py, svc, "status").returncode == 0:
        break
    time.sleep(2)
else:
    failures.append("login service is not listening")

d = run(py, svc, "doctor")
lines = d.stdout.splitlines()
hook_lines = [x for x in lines if " via " in x]
if not hook_lines:
    failures.append("doctor found no hooks")
for x in hook_lines:
    if not x.strip().startswith("ok"):
        failures.append("hook check failed: " + x.strip())
if not any("SQL statement request refused (403)" in x and x.strip().startswith("ok") for x in lines):
    failures.append("proxy did not refuse a SQL statement request")

u = run(py, ROOT / "install.py", "--uninstall")
if u.returncode != 0:
    failures.append("uninstall failed")

print("\n" + ("SMOKE TEST PASSED" if not failures else "SMOKE TEST FAILED:\n  " + "\n  ".join(failures)))
sys.exit(1 if failures else 0)
