#!/usr/bin/env python3
"""
dbx_metadata_proxy.py: a local, metadata-only gateway between the coding agent and Databricks.

Use this when you can't read the workspace audit logs. The developer runs it on their own
machine. The agent's Databricks profile points at it (http://127.0.0.1:8787) and holds only a
placeholder token. The proxy:

  * forwards ONLY allowlisted Unity Catalog metadata GETs to the real workspace,
  * adds the real credentials itself (the agent never has them),
  * returns 403 PERMISSION_DENIED for everything else (SQL statements, jobs, files, Genie, ...),
  * writes every request, allowed or blocked, to .databricks-guard/proxy.jsonl.
    That file is your local audit log.

Standard library only. If `databricks-sdk` is installed, OAuth/U2M/M2M profiles also work for the
upstream login. Without it, the upstream profile must use a personal access token.

  databricks auth login --host https://<workspace> --profile DEFAULT     # OAuth U2M, once
  python3 .guards/dbx_metadata_proxy.py --upstream-profile DEFAULT       # acts on behalf of you
  python3 .guards/dbx_metadata_proxy.py --upstream-host https://adb-123.cloud.databricks.com \
          --upstream-token-env MY_REAL_DATABRICKS_TOKEN

Agent profile (~/.databrickscfg):
  [agent]
  host  = http://127.0.0.1:8787
  token = local-proxy-placeholder
"""
from __future__ import annotations

import argparse
import configparser
import datetime as _dt
import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable, Dict, Optional, Tuple

VERSION = "1.0.0"

# (method, path regex) pairs that may be forwarded. Anything else gets 403.
ALLOW: Tuple[Tuple[str, "re.Pattern[str]"], ...] = tuple(
    ("GET", re.compile(p)) for p in (
        r"^/api/2\.[01]/unity-catalog/catalogs$",
        r"^/api/2\.[01]/unity-catalog/catalogs/[^/]+$",
        r"^/api/2\.[01]/unity-catalog/schemas$",
        r"^/api/2\.[01]/unity-catalog/schemas/[^/]+$",
        r"^/api/2\.[01]/unity-catalog/tables$",
        r"^/api/2\.[01]/unity-catalog/tables/[^/]+$",
        r"^/api/2\.[01]/unity-catalog/tables/[^/]+/exists$",
        r"^/api/2\.[01]/unity-catalog/table-summaries$",
        r"^/api/2\.[01]/unity-catalog/metastore_summary$",
        r"^/api/2\.[01]/unity-catalog/current-metastore-assignment$",
        r"^/api/2\.0/preview/scim/v2/Me$",
        r"^/\.well-known/databricks-config$",          # SDK host discovery at client start-up
    )
)

# Query parameters dropped before forwarding (none today; extend if an endpoint gains a data option).
DROP_QUERY_PARAMS: set = set()

HOP_BY_HOP = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te",
              "trailers", "transfer-encoding", "upgrade", "content-encoding", "content-length"}


def is_allowed(method: str, path: str) -> bool:
    return any(method == m and rx.match(path) for m, rx in ALLOW)


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="milliseconds")


# --------------------------------------------------------------------------------------
# Upstream authentication
# --------------------------------------------------------------------------------------
def make_upstream_auth(profile: Optional[str], host: Optional[str], token_env: Optional[str],
                       config_file: Optional[str]) -> Tuple[str, Callable[[], Dict[str, str]]]:
    """Return (upstream_host, header_factory). Header factory is called per request."""
    if host and token_env:
        tok = os.environ.get(token_env)
        if not tok:
            raise SystemExit(f"environment variable {token_env} is empty")
        return host.rstrip("/"), lambda: {"Authorization": f"Bearer {tok}"}

    profile = profile or "DEFAULT"
    try:  # prefer the SDK: supports OAuth U2M/M2M, Azure CLI, token refresh
        from databricks.sdk.core import Config  # type: ignore
        kw = {"profile": profile}
        if config_file:
            kw["config_file"] = config_file
        cfg = Config(**kw)
        if not cfg.host:
            raise SystemExit(f"profile [{profile}] has no host")
        if re.match(r"^https?://(127\.0\.0\.1|localhost)", cfg.host) and \
                os.environ.get("DBX_PROXY_ALLOW_LOCAL_UPSTREAM") != "1":
            raise SystemExit(f"profile [{profile}] points at localhost; pick the REAL workspace profile")
        lock = threading.Lock()

        def headers() -> Dict[str, str]:
            with lock:
                return dict(cfg.authenticate())   # U2M: SDK refreshes via `databricks auth token`
        headers.auth_type = cfg.auth_type or "auto"  # type: ignore[attr-defined]
        return cfg.host.rstrip("/"), headers
    except ImportError:
        pass

    path = Path(config_file or os.environ.get("DATABRICKS_CONFIG_FILE", "~/.databrickscfg")).expanduser()
    cp = configparser.ConfigParser()
    cp.read(path)
    sect = cp.defaults() if profile == "DEFAULT" else (cp[profile] if cp.has_section(profile) else None)
    if not sect or not sect.get("host") or not sect.get("token"):
        raise SystemExit(f"profile [{profile}] in {path} needs host and token "
                         "(or install databricks-sdk for OAuth profiles)")
    tok = sect["token"]
    return sect["host"].rstrip("/"), lambda: {"Authorization": f"Bearer {tok}"}


def whoami(host: str, auth: Callable[[], Dict[str, str]], timeout: float = 30.0) -> str:
    """Return the identity the upstream credentials act as (SCIM Me)."""
    req = urllib.request.Request(host + "/api/2.0/preview/scim/v2/Me",
                                 headers={**auth(), "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        me = json.loads(resp.read() or b"{}")
    return me.get("userName") or me.get("displayName") or me.get("id") or "unknown"


# --------------------------------------------------------------------------------------
# Proxy server
# --------------------------------------------------------------------------------------
class ProxyState:
    def __init__(self, upstream: str, auth: Callable[[], Dict[str, str]], log_path: Path,
                 timeout: float, acting_as: str = "") -> None:
        self.acting_as = acting_as
        self._last_whoami = 0.0
        self.resolver: Optional[Callable[[], Tuple[str, Callable[[], Dict[str, str]]]]] = None
        self.upstream = upstream
        self.auth = auth
        self.log_path = log_path
        self.timeout = timeout
        self.lock = threading.Lock()
        log_path.parent.mkdir(parents=True, exist_ok=True)

    def resolve(self) -> Tuple[str, Callable[[], Dict[str, str]]]:
        if self.resolver:
            self.upstream, self.auth = self.resolver()
            self.resolver = None
        return self.upstream, self.auth

    def ensure_identity(self) -> None:
        """Lenient start (login service): learn who we act as once the U2M login works."""
        if self.acting_as or time.time() - self._last_whoami < 30:
            return
        self._last_whoami = time.time()
        try:
            self.resolve()
            self.acting_as = whoami(self.upstream, self.auth, self.timeout)
            print(f"  now acting on behalf of: {self.acting_as}", file=sys.stderr, flush=True)
        except Exception as e:
            print(f"  upstream login not ready: {e}", file=sys.stderr, flush=True)

    def log(self, rec: dict) -> None:
        line = json.dumps(rec, sort_keys=True)
        with self.lock, open(self.log_path, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")


def make_handler(state: ProxyState):
    class Handler(BaseHTTPRequestHandler):
        server_version = f"dbx-metadata-proxy/{VERSION}"
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt, *args):  # quiet stdout; we log JSONL instead
            pass

        def _send(self, status: int, body: bytes, ctype: str = "application/json",
                  extra: Optional[Dict[str, str]] = None) -> None:
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def _handle(self) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            if length:
                self.rfile.read(length)  # drain; bodies are never forwarded
            state.ensure_identity()
            parsed = urllib.parse.urlsplit(self.path)
            path = urllib.parse.unquote(parsed.path)
            qs = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
            rec = {"ts": _now(), "method": self.command, "path": path,
                   "query": parsed.query[:2000], "client": self.client_address[0],
                   "user_agent": (self.headers.get("User-Agent") or "")[:300],
                   "body_bytes": length, "via": "agent-proxy", "acting_as": state.acting_as}

            if not is_allowed(self.command, path) or "/../" in self.path or "%2f" in self.path.lower():
                rec.update(decision="blocked", status=403)
                state.log(rec)
                msg = (f"Blocked by local metadata-only proxy: {self.command} {path} is not an "
                       "allowlisted Unity Catalog metadata request. Generate the code for a human "
                       "to run instead.")
                self._send(403, json.dumps({"error_code": "PERMISSION_DENIED", "message": msg}).encode())
                return

            q = urllib.parse.urlencode([(k, v) for k, v in qs if k not in DROP_QUERY_PARAMS])
            try:
                state.resolve()
            except BaseException as e:   # login not ready yet (lenient start)
                rec.update(decision="error", status=503, error=f"login not ready: {e}"[:500])
                state.log(rec)
                self._send(503, json.dumps({"error_code": "TEMPORARILY_UNAVAILABLE", "message":
                           "metadata proxy is waiting for the developer's Databricks login: "
                           f"{e}"[:400]}).encode())
                return
            url = state.upstream + urllib.parse.quote(path, safe="/.-_~") + (f"?{q}" if q else "")
            headers = {"Accept": "application/json", "Accept-Encoding": "identity",
                       "User-Agent": f"dbx-metadata-proxy/{VERSION} ({rec['user_agent'][:150]})"}
            try:
                headers.update(state.auth())
                req = urllib.request.Request(url, headers=headers, method="GET")
                with urllib.request.urlopen(req, timeout=state.timeout) as resp:
                    body = resp.read()
                    status = resp.status
                    ctype = resp.headers.get("Content-Type", "application/json")
            except urllib.error.HTTPError as e:
                body, status = e.read(), e.code
                ctype = e.headers.get("Content-Type", "application/json")
            except Exception as e:  # upstream unreachable / auth failure
                rec.update(decision="error", status=502, error=f"{type(e).__name__}: {e}"[:500])
                state.log(rec)
                msg = (f"metadata proxy upstream error: {e}. If your Databricks login expired, the "
                       "developer (not the agent) should run: databricks auth login --profile "
                       f"{os.environ.get('DBX_PROXY_UPSTREAM_PROFILE', 'DEFAULT')}")
                self._send(502, json.dumps({"error_code": "BAD_GATEWAY", "message": msg}).encode())
                return
            rec.update(decision="forwarded", status=status, resp_bytes=len(body))
            state.log(rec)
            self._send(status, body, ctype)

        do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = do_HEAD = do_OPTIONS = _handle

    return Handler


def serve(state: ProxyState, bind: str, port: int) -> ThreadingHTTPServer:
    if bind not in ("127.0.0.1", "localhost", "::1"):
        raise SystemExit("refusing to bind to a non-loopback address")
    return ThreadingHTTPServer((bind, port), make_handler(state))


def _utf8_console() -> None:
    """Windows consoles default to cp1252; never let printing a message crash a guard."""
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except Exception:
            pass


def main(argv=None) -> int:
    _utf8_console()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--upstream-profile", help="profile in ~/.databrickscfg with REAL credentials")
    ap.add_argument("--upstream-host", help="workspace URL (use with --upstream-token-env)")
    ap.add_argument("--upstream-token-env", help="env var holding the real token")
    ap.add_argument("--config-file", help="alternative .databrickscfg path")
    ap.add_argument("--port", type=int, default=int(os.environ.get("DBX_PROXY_PORT", 8787)))
    ap.add_argument("--bind", default="127.0.0.1")
    ap.add_argument("--log", default=os.environ.get("DBX_PROXY_LOG", ".databricks-guard/proxy.jsonl"))
    ap.add_argument("--timeout", type=float, default=30.0)
    ap.add_argument("--lenient-start", action="store_true",
                    help="keep running if the login isn't ready yet (used by the login service)")
    args = ap.parse_args(argv)
    if args.upstream_profile:
        os.environ["DBX_PROXY_UPSTREAM_PROFILE"] = args.upstream_profile

    if args.lenient_start:
        # Login service: start listening immediately; set up the upstream login on first use.
        lock = threading.Lock()
        last = [0.0]

        def resolver():
            if not lock.acquire(blocking=False):          # never make the agent wait on login setup
                raise RuntimeError("connecting to the workspace; try again in a moment")
            try:
                if time.time() - last[0] < 15:
                    raise RuntimeError("retrying shortly")
                last[0] = time.time()
                try:
                    return make_upstream_auth(args.upstream_profile, args.upstream_host,
                                              args.upstream_token_env, args.config_file)
                except SystemExit as e:
                    raise RuntimeError(str(e))
            finally:
                lock.release()
        state = ProxyState("", lambda: {}, Path(args.log).resolve(), args.timeout)
        state.resolver = resolver
        httpd = serve(state, args.bind, args.port)
        print(f"dbx-metadata-proxy {VERSION}: http://{args.bind}:{args.port} (login service mode)\n"
              f"  upstream profile: {args.upstream_profile or 'DEFAULT'}; log: {state.log_path}",
              file=sys.stderr, flush=True)
        threading.Thread(target=state.ensure_identity, daemon=True).start()
        try:
            httpd.serve_forever()
        finally:
            httpd.server_close()
        return 0
    host, auth = make_upstream_auth(args.upstream_profile, args.upstream_host,
                                    args.upstream_token_env, args.config_file)
    try:
        who = whoami(host, auth, args.timeout)
    except Exception as e:
        hint = (f"run:  databricks auth login --host {host} --profile {args.upstream_profile or 'DEFAULT'}"
                if not args.upstream_token_env else "check the token in " + args.upstream_token_env)
        if not args.lenient_start:
            raise SystemExit(f"cannot authenticate to {host}: {e}\n{hint}")
        print(f"warning: cannot authenticate to {host} yet: {e}\n  {hint}\n"
              "  starting anyway; will retry on the first request", file=sys.stderr, flush=True)
        who = ""
    auth_type = getattr(auth, "auth_type", "pat")
    state = ProxyState(host, auth, Path(args.log).resolve(), args.timeout, acting_as=who)
    httpd = serve(state, args.bind, args.port)
    print(f"dbx-metadata-proxy {VERSION}: http://{args.bind}:{args.port} -> {host}\n"
          f"  acting on behalf of: {who or '(login pending)'}  (auth: {auth_type})\n"
          f"  metadata GETs only; log: {state.log_path}\n  Ctrl-C to stop.", file=sys.stderr)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
