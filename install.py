#!/usr/bin/env python3
"""
Install the Databricks metadata-only guard. Works on macOS and Windows (and Linux, without autostart).

    python3 install.py /path/to/your/repo          macOS
    py install.py C:\\path\\to\\your\\repo            Windows

Two parts:

REPO (shared, commit these)
  <repo>/CLAUDE.md                                 rule for Claude (appended if the file exists)
  <repo>/.cursor/rules/databricks-metadata-only.mdc rule for Cursor
  <repo>/.guards/                                  guard, proxy, service helper, tests, docs
  <repo>/.claude/settings.json                     env + deny list (portable, no machine paths)
  <repo>/.gitignore                                adds .databricks-guard/

THIS COMPUTER (per developer, never committed)
  ~/.databricks-guard/bin/                         guard + proxy copies used by hooks and the service
  ~/.claude/settings.json                          Claude Code hook, using THIS machine's Python
  ~/.cursor/hooks.json                             Cursor hooks, using THIS machine's Python
  ~/.databrickscfg                                 adds the [agent] profile (backup kept)
  login service                                    macOS LaunchAgent / Windows scheduled task

Options: --repo-only  --user-only  --no-autostart  --upstream-profile NAME  --port N  --no-pip
Safe to run again (updates in place, *.bak backups of anything it changes).
"""
from __future__ import annotations

import argparse
import configparser
import json
import os
import platform
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
# Works from the downloaded package (guards/ next to this file) and from a repo copy
# (<repo>/.guards/setup/install.py, guard files one level up).
GUARDS_SRC = HERE / "guards" if (HERE / "guards").is_dir() else HERE.parent
sys.path.insert(0, str(GUARDS_SRC))
import proxy_service as svc  # noqa: E402

MARK = "# RULE: Databricks — Metadata Only, Generate Code, Never Execute"
HOME = Path(os.environ.get("DBX_GUARD_HOME") or Path.home())
OSNAME = svc.system()
CLAUDE_MATCHER = "Bash|Read|Write|Edit|MultiEdit|NotebookEdit|Grep|Glob|mcp__.*"
CURSOR_EVENTS = ("beforeShellExecution", "beforeMCPExecution", "beforeReadFile")
USER_DENY = [
    "Read(~/.databrickscfg)", "Read(~/.databricks/**)",
    "Edit(~/.databricks-guard/**)", "Write(~/.databricks-guard/**)",
    "Edit(~/.claude/settings.json)", "Write(~/.claude/settings.json)",
    "Edit(~/.cursor/hooks.json)", "Write(~/.cursor/hooks.json)",
    "Edit(~/.databrickscfg)", "Write(~/.databrickscfg)",
]


def _is_ours(cmd: str) -> bool:
    """Recognise hooks written by this installer (also with Windows 8.3 short names)."""
    c = cmd.lower()
    return "databricks_guard" in c or ("hook --agent" in c and "databr" in c)


def say(msg: str) -> None:
    print(msg, flush=True)


def backup(p: Path) -> None:
    if p.exists():
        shutil.copy2(p, p.with_name(p.name + ".bak"))


def load_json(p: Path) -> dict:
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8") or "{}")
    except ValueError:
        raise SystemExit(f"{p} is not valid JSON; fix it or move it away, then re-run.")


def save_json(p: Path, data: dict) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    backup(p)
    p.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def union(a: list, b: list) -> list:
    return a + [x for x in b if x not in a]


# --------------------------------------------------------------------------------------
# Interpreters and hook commands (must work in cmd, PowerShell, Git Bash, sh/zsh)
# --------------------------------------------------------------------------------------
def base_python() -> str:
    """Prefer the base interpreter so hooks don't break if a virtualenv is deleted."""
    if sys.prefix != getattr(sys, "base_prefix", sys.prefix):
        b = getattr(sys, "_base_executable", "")
        if b and Path(b).is_file():
            return b
    return sys.executable


def has_sdk(python: str) -> bool:
    return subprocess.run([python, "-c", "import databricks.sdk"], capture_output=True).returncode == 0


def win_short(path: str) -> str:
    try:
        import ctypes
        buf = ctypes.create_unicode_buffer(32768)
        if ctypes.windll.kernel32.GetShortPathNameW(path, buf, 32768):  # type: ignore[attr-defined]
            return buf.value
    except Exception:
        pass
    return path


def shell_word(path: str) -> str:
    if OSNAME == "Windows":
        from pathlib import PureWindowsPath
        pp = PureWindowsPath(path)
        p = (win_short(str(pp.parent)).rstrip("\\/") + "/" + pp.name).replace("\\", "/")
        # forward slashes work in cmd, PowerShell and Git Bash
        if " " in p:
            say(f"  warning: path has spaces and no 8.3 short name: {p}\n"
                "           hooks may not run under PowerShell; `doctor` below will tell you.")
            return f'"{p}"'
        return p
    return shlex.quote(path)


def hook_command(python: str, agent: str) -> str:
    script = str(svc.paths()["bin"] / "databricks_guard.py")
    cmd = f"{shell_word(python)} {shell_word(script)} hook --agent {agent} --require-profile agent"
    if OSNAME == "Windows" and agent == "cursor":
        # Cursor runs hooks through PowerShell: `&` runs a (possibly quoted) program path, and
        # `exit $LASTEXITCODE` passes the guard's exit code 2 (= deny) through instead of 1.
        cmd = f"& {cmd}; exit $LASTEXITCODE"
    return cmd


# --------------------------------------------------------------------------------------
# Repo part
# --------------------------------------------------------------------------------------
def install_repo(repo: Path) -> list:
    done = []
    g = repo / ".guards"
    if GUARDS_SRC.resolve() != g.resolve():
        shutil.copytree(GUARDS_SRC, g, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns("__pycache__", "setup"))
    # Setup kit so teammates can run:  python3 .guards/setup/install.py --user-only
    kit = g / "setup"
    if HERE.resolve() != kit.resolve():
        (kit / "claude").mkdir(parents=True, exist_ok=True)
        (kit / "cursor" / "rules").mkdir(parents=True, exist_ok=True)
        shutil.copy2(HERE / "install.py", kit / "install.py")
        shutil.copy2(HERE / "CLAUDE.md", kit / "CLAUDE.md")
        shutil.copy2(HERE / "claude" / "settings.json", kit / "claude" / "settings.json")
        shutil.copy2(HERE / "cursor" / "rules" / "databricks-metadata-only.mdc", kit / "cursor" / "rules")
    done.append(".guards/  (guard, proxy, service helper, tests, README, setup/install.py)")

    # Portable settings only. Hooks live in the user-level settings with this machine's Python.
    p = repo / ".claude" / "settings.json"
    src = load_json(HERE / "claude" / "settings.json")
    cur = load_json(p)
    cur.setdefault("env", {}).update(src.get("env", {}))
    cur.setdefault("permissions", {})["deny"] = union(cur.get("permissions", {}).get("deny", []),
                                                     src.get("permissions", {}).get("deny", []))
    pre = cur.get("hooks", {}).get("PreToolUse", [])
    kept = [e for e in pre if not any(_is_ours(h.get("command", ""))
                                      for h in e.get("hooks", []))]
    if len(kept) != len(pre):
        cur["hooks"]["PreToolUse"] = kept
        done.append(".claude/settings.json  (removed old machine-specific hook; now user-level)")
    if not cur.get("hooks", {}).get("PreToolUse", True):
        cur["hooks"].pop("PreToolUse")
        if not cur["hooks"]:
            cur.pop("hooks")
    save_json(p, cur)
    done.append(".claude/settings.json  (env DATABRICKS_CONFIG_PROFILE=agent + deny list)")

    # Old project-level Cursor hooks used `sh` and `python3` (break on Windows): remove ours.
    ch = repo / ".cursor" / "hooks.json"
    if ch.exists():
        data = load_json(ch)
        changed = False
        for ev, entries in list(data.get("hooks", {}).items()):
            kept = [e for e in entries if not _is_ours(e.get("command", ""))]
            if len(kept) != len(entries):
                changed = True
                data["hooks"][ev] = kept
                if not kept:
                    data["hooks"].pop(ev)
        if changed:
            if data.get("hooks"):
                save_json(ch, data)
            else:
                backup(ch)
                ch.unlink()
            done.append(".cursor/hooks.json  (removed old project hook; now user-level)")

    rules = repo / ".cursor" / "rules"
    rules.mkdir(parents=True, exist_ok=True)
    shutil.copy2(HERE / "cursor" / "rules" / "databricks-metadata-only.mdc", rules)
    done.append(".cursor/rules/databricks-metadata-only.mdc")

    cm = repo / "CLAUDE.md"
    rule = (HERE / "CLAUDE.md").read_text(encoding="utf-8")
    if not cm.exists():
        cm.write_text(rule, encoding="utf-8")
        done.append("CLAUDE.md  (created)")
    else:
        text = cm.read_text(encoding="utf-8")
        backup(cm)
        if MARK in text:
            cm.write_text(text[:text.index(MARK)] + rule, encoding="utf-8")
            done.append("CLAUDE.md  (rule updated)")
        else:
            cm.write_text(text.rstrip() + "\n\n---\n\n" + rule, encoding="utf-8")
            done.append("CLAUDE.md  (rule appended)")

    gi = repo / ".gitignore"
    lines = gi.read_text(encoding="utf-8").splitlines() if gi.exists() else []
    add = [x for x in (".databricks-guard/", "*.bak", ".claude/settings.local.json") if x not in lines]
    if add:
        gi.write_text("\n".join(lines + add) + "\n", encoding="utf-8")
        done.append(".gitignore")
    return done


# --------------------------------------------------------------------------------------
# User part (this computer)
# --------------------------------------------------------------------------------------
# --------------------------------------------------------------------------------------
# Databricks CLI + sign-in: the user has already set these up. We only check and report.
# --------------------------------------------------------------------------------------
def find_cli() -> str:
    cli = shutil.which("databricks")
    if cli:
        return cli
    if OSNAME == "Windows":
        la = os.environ.get("LOCALAPPDATA", "")
        cand = Path(la) / "Microsoft" / "WinGet" / "Links" / "databricks.exe"
        if cand.is_file():
            os.environ["PATH"] = str(cand.parent) + os.pathsep + os.environ.get("PATH", "")
            return str(cand)
    return ""


def signed_in(cli: str, profile: str) -> bool:
    try:
        r = subprocess.run([cli, "current-user", "me", "-p", profile, "-o", "json"], capture_output=True,
                           text=True, timeout=90)
        return r.returncode == 0
    except Exception:
        return False


def check_databricks(args) -> None:
    """Expected: the Databricks CLI is installed and the user is signed in (OAuth U2M). Never blocks."""
    up = args.upstream_profile
    cli = find_cli()
    if not cli:
        say("  ! The Databricks command-line tool wasn't found. The guardrails install anyway, but the\n"
            "    gateway needs it to use your sign-in. Install it yourself (README, Troubleshooting).")
        return
    if signed_in(cli, up):
        say(f"  Databricks sign-in for profile [{up}]: OK")
    else:
        say(f"  ! Not signed in to Databricks for profile [{up}]. The guardrails install anyway; the gateway\n"
            f"    starts working as soon as you sign in yourself:  databricks auth login --profile {up}\n"
            "    (If your profile has another name, the user can re-run with --upstream-profile NAME.)")


def install_user(args) -> list:
    done = []
    hook_py = base_python()

    # Proxy interpreter must have databricks-sdk (needed for OAuth U2M).
    proxy_py = next((p for p in dict.fromkeys([sys.executable, hook_py]) if has_sdk(p)), None)
    if not proxy_py:
        if args.no_pip:
            raise SystemExit(f"databricks-sdk is required for OAuth U2M. Run:\n  {hook_py} -m pip install "
                             "--user databricks-sdk\nthen re-run install.py")
        say(f"  installing databricks-sdk for {hook_py} (pip --user) ...")
        r = subprocess.run([hook_py, "-m", "pip", "install", "--user", "--quiet", "databricks-sdk"])
        if r.returncode != 0 or not has_sdk(hook_py):
            raise SystemExit("could not install databricks-sdk; install it manually and re-run")
        proxy_py = hook_py

    cfg = svc.install_files(args.upstream_profile, args.port, proxy_py)
    done.append(f"~/.databricks-guard/bin/  (guard + proxy; python: {proxy_py})")
    if not cfg.get("databricks_cli"):
        done.append("  ! databricks CLI not found: install it, then `databricks auth login`")

    # Claude Code (user level: applies to every project on this computer)
    cs = HOME / ".claude" / "settings.json"
    data = load_json(cs)
    data.setdefault("env", {})["DATABRICKS_CONFIG_PROFILE"] = "agent"
    hooks = data.setdefault("hooks", {})
    pre = [e for e in hooks.get("PreToolUse", [])
           if not any(_is_ours(h.get("command", "")) for h in e.get("hooks", []))]
    pre.append({"matcher": CLAUDE_MATCHER,
                "hooks": [{"type": "command", "command": hook_command(hook_py, "claude"), "timeout": 30}]})
    hooks["PreToolUse"] = pre
    repo_deny = load_json(HERE / "claude" / "settings.json").get("permissions", {}).get("deny", [])
    data.setdefault("permissions", {})["deny"] = union(data.get("permissions", {}).get("deny", []),
                                                      repo_deny + USER_DENY)
    save_json(cs, data)
    done.append(f"~/.claude/settings.json  (hook: {hook_command(hook_py, 'claude')})")

    # Cursor (user level)
    cu = HOME / ".cursor" / "hooks.json"
    data = load_json(cu)
    data.setdefault("version", 1)
    hk = data.setdefault("hooks", {})
    for ev in CURSOR_EVENTS:
        entries = [e for e in hk.get(ev, []) if not _is_ours(e.get("command", ""))]
        entries.append({"command": hook_command(hook_py, "cursor"), "failClosed": True})
        hk[ev] = entries
    save_json(cu, data)
    done.append("~/.cursor/hooks.json  (beforeShellExecution, beforeMCPExecution, beforeReadFile)")

    # Agent profile
    cfgfile = Path(os.environ.get("DATABRICKS_CONFIG_FILE") or HOME / ".databrickscfg")
    cp = configparser.ConfigParser()
    cp.read(cfgfile, encoding="utf-8")
    want = f"http://127.0.0.1:{args.port}"
    if cp.has_section("agent"):
        host = cp.get("agent", "host", fallback="")
        if host.rstrip("/") != want:
            done.append(f"  ! [agent] profile exists with host={host}; expected {want}. Not changed.")
        else:
            done.append(f"{cfgfile}  ([agent] profile already present)")
    else:
        backup(cfgfile)
        with open(cfgfile, "a", encoding="utf-8") as fh:
            fh.write(f"\n[agent]\n; coding agents use this: local metadata-only proxy, no real credentials\n"
                     f"host  = {want}\ntoken = local-proxy-placeholder\nretry_timeout_seconds = 15\n")
        done.append(f"{cfgfile}  (added [agent] -> {want})")
    up = args.upstream_profile
    if up != "DEFAULT" and not cp.has_section(up):
        done.append(f"  ! upstream profile [{up}] not found; run: databricks auth login --profile {up}")

    # Login service
    if args.no_autostart:
        done.append("autostart skipped: run the proxy yourself:\n      "
                    f"{proxy_py} {svc.paths()['bin'] / 'dbx_metadata_proxy.py'} --upstream-profile {up} "
                    f"--log {svc.paths()['log']}")
    elif OSNAME in ("Darwin", "Windows"):
        ns = argparse.Namespace(upstream_profile=up, port=args.port, python=proxy_py, dry_run=args.dry_run)
        rc = svc.cmd_install(ns, cfg=cfg)
        done.append("login service " + ("(dry run)" if args.dry_run else "installed and running" if rc == 0
                                        else "installed (not answering yet; see `proxy_service.py status`)"))
    else:
        done.append(f"autostart not supported on {OSNAME}; run the proxy manually (see README)")
    return done


def _utf8_console() -> None:
    """Windows consoles default to cp1252; never let printing a message crash a guard."""
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except Exception:
            pass


def uninstall_user() -> list:
    """Remove everything this installer added on this computer (logs are kept)."""
    done = []
    try:
        osname = svc.system()
        if osname in ("Darwin", "Windows"):
            svc.cmd_uninstall(argparse.Namespace(dry_run=False))
            done.append("login service removed")
    except Exception as e:
        done.append(f"  ! could not remove login service: {e}")
    repo_deny = load_json(HERE / "claude" / "settings.json").get("permissions", {}).get("deny", [])
    ours = set(repo_deny + USER_DENY)
    cs = HOME / ".claude" / "settings.json"
    if cs.exists():
        data = load_json(cs)
        pre = data.get("hooks", {}).get("PreToolUse", [])
        data.setdefault("hooks", {})["PreToolUse"] = [
            e for e in pre if not any(_is_ours(h.get("command", "")) for h in e.get("hooks", []))]
        if not data["hooks"]["PreToolUse"]:
            data["hooks"].pop("PreToolUse")
        if not data["hooks"]:
            data.pop("hooks")
        if data.get("env", {}).get("DATABRICKS_CONFIG_PROFILE") == "agent":
            data["env"].pop("DATABRICKS_CONFIG_PROFILE")
            if not data["env"]:
                data.pop("env")
        if "permissions" in data:
            data["permissions"]["deny"] = [x for x in data["permissions"].get("deny", []) if x not in ours]
            if not data["permissions"]["deny"]:
                data["permissions"].pop("deny")
            if not data["permissions"]:
                data.pop("permissions")
        save_json(cs, data)
        done.append("~/.claude/settings.json  (hook removed)")
    cu = HOME / ".cursor" / "hooks.json"
    if cu.exists():
        data = load_json(cu)
        for ev in list(data.get("hooks", {})):
            data["hooks"][ev] = [e for e in data["hooks"][ev] if not _is_ours(e.get("command", ""))]
            if not data["hooks"][ev]:
                data["hooks"].pop(ev)
        save_json(cu, data)
        done.append("~/.cursor/hooks.json  (hooks removed)")
    cfgfile = Path(os.environ.get("DATABRICKS_CONFIG_FILE") or HOME / ".databrickscfg")
    if cfgfile.exists():
        cp = configparser.ConfigParser()
        cp.read(cfgfile, encoding="utf-8")
        if cp.has_section("agent") and "127.0.0.1" in cp.get("agent", "host", fallback=""):
            backup(cfgfile)
            lines, out, skip = cfgfile.read_text(encoding="utf-8").splitlines(), [], False
            for ln in lines:
                if ln.strip().startswith("["):
                    skip = ln.strip() == "[agent]"
                if not skip:
                    out.append(ln)
            cfgfile.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")
            done.append(f"{cfgfile}  ([agent] profile removed)")
    done.append("kept: ~/.databricks-guard/ (logs) and the repo files; delete them by hand if you like")
    return done


def main() -> int:
    _utf8_console()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("repo", nargs="?", default=".")
    ap.add_argument("--repo-only", action="store_true", help="only write the shared repo files")
    ap.add_argument("--user-only", action="store_true", help="only set up this computer")
    ap.add_argument("--no-autostart", action="store_true", help="don't install the login service")
    ap.add_argument("--upstream-profile", default="DEFAULT", help="your OAuth U2M profile (default DEFAULT)")
    ap.add_argument("--port", type=int, default=8787)
    ap.add_argument("--no-pip", action="store_true", help="don't pip-install databricks-sdk")
    ap.add_argument("--skip-doctor", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="print service commands instead of running them")
    ap.add_argument("--skip-databricks-check", action="store_true",
                    help="don't check the Databricks CLI or sign-in (tests / advanced)")
    ap.add_argument("--uninstall", action="store_true", help="remove hooks, [agent] profile and login service "
                                                              "from this computer")
    args = ap.parse_args()
    if args.uninstall:
        say("Removing the Databricks guard from this computer:")
        for d in uninstall_user():
            say(f"  {d}")
        say("\nRestart Cursor and Claude so they stop using the hooks.")
        return 0

    say(f"Databricks guard installer ({OSNAME}, Python {platform.python_version()})")
    if not args.repo_only and not args.skip_databricks_check and not args.dry_run:
        say("\nChecking Databricks:")
        check_databricks(args)
    if not args.user_only:
        repo = Path(args.repo).resolve()
        if not repo.is_dir():
            raise SystemExit(f"not a directory: {repo}")
        if repo == HERE:
            raise SystemExit("point this at your repository, e.g.  python3 install.py ~/code/my-repo")
        say(f"\nRepo: {repo}")
        for d in install_repo(repo):
            say(f"  {d}")
    if not args.repo_only:
        say(f"\nThis computer ({HOME}):")
        for d in install_user(args):
            say(f"  {d}")
        if not args.skip_doctor and not args.dry_run:
            say("\nSelf-test:")
            subprocess.run([sys.executable, str(svc.paths()["bin"] / "proxy_service.py"), "doctor"])
    say("""
Next:
  - If you haven't signed in:  databricks auth login --host https://<workspace> --profile DEFAULT
    (the proxy picks the login up automatically)
  - Restart Cursor and Claude Code so they load the hooks.
  - Check any time:  python3 ~/.databricks-guard/bin/proxy_service.py status   (Windows: py ...)
                     python3 .guards/databricks_guard.py verify               (in the repo)""")
    return 0


if __name__ == "__main__":
    sys.exit(main())
