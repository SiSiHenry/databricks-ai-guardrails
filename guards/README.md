# Databricks metadata-only guard (macOS + Windows, OAuth U2M, runs locally)

A deterministic check that goes with the rule in `CLAUDE.md` and
`.cursor/rules/databricks-metadata-only.mdc`.
- **What the agent may do:** read Unity Catalog metadata and write code.
- **What it may never do:** run SQL or read data.
- **What you need:** nothing beyond Python 3.9+ and `databricks-sdk`. No access to workspace
  audit logs is required.

```
 Cursor / Claude agent
        │  every shell / file / MCP call
        ▼
 ① guard hook (~/.databricks-guard/bin/databricks_guard.py)
        │    blocks violations, logs to <repo>/.databricks-guard/decisions.jsonl
        ▼  allowed calls only
 databricks CLI / SDK  (profile "agent" → http://127.0.0.1:8787, placeholder token)
        ▼
 ② metadata proxy (login service, runs as YOU)
        │    forwards ONLY Unity Catalog metadata GETs using your OAuth U2M login,
        │    403s everything else, logs every request to ~/.databricks-guard/proxy.jsonl
        ▼
 Databricks workspace (every request is made as you)

 ③ verify ──► reads both logs ──► COMPLIANT / NOT COMPLIANT
```

## How OAuth U2M fits

You sign in once with `databricks auth login`. The CLI keeps the token in the macOS Keychain
or Windows Credential Manager. Anything using that login acts **as you**, so Databricks can't
tell the agent's requests apart from yours. That's why the boundary lives on the laptop:

| Profile | Used by | Points at | Credentials |
|---|---|---|---|
| `DEFAULT` (your U2M profile) | **you**, and the proxy | the real workspace | your U2M login |
| `agent` | **the coding agent only** | `http://127.0.0.1:8787` | placeholder, no real token |

Your own Databricks use is unchanged.

## Setup (once per developer)

Prerequisites: Python 3.9+, and the Databricks CLI signed in with U2M.

| | macOS | Windows |
|---|---|---|
| Sign in (if not yet) | `databricks auth login --host https://<ws> --profile DEFAULT` | same |
| Run the installer | `python3 install.py ~/code/my-repo` | `py install.py C:\code\my-repo` |
| Then | restart Cursor and Claude Code | restart Cursor and Claude Code |

The installer:
1. **Writes the repo files.** That's the rules, `.guards/` and the portable `.claude/settings.json`.
   Commit these once for the team.
2. **Sets up this computer:**
   - copies the guard and proxy to `~/.databricks-guard/bin/` (Windows: `%USERPROFILE%\.databricks-guard\bin\`);
   - writes the **user-level** hooks into `~/.claude/settings.json` and `~/.cursor/hooks.json`,
     using **this machine's Python by absolute path**, so they run under cmd, PowerShell,
     Git Bash, zsh and sh;
   - adds the `[agent]` profile to `~/.databrickscfg` (keeps a `.bak`);
   - installs `databricks-sdk` with `pip --user` if it's missing (skip with `--no-pip`).
3. **Installs the login service** so the proxy starts automatically:
   - **macOS:** a LaunchAgent `com.databricks-guard.proxy`. It starts at login and restarts if it stops.
   - **Windows:** a hidden scheduled task `DatabricksGuardProxy`. It starts at logon, has no time
     limit, restarts on failure and runs with `pythonw` (no console window).

   Both run inside your logged-in session, so they can use your Keychain / Credential Manager login.
4. **Runs `doctor`**, a self-test (see below).

Options: `--upstream-profile NAME` (if your U2M profile isn't `DEFAULT`), `--port N`,
`--no-autostart`, `--repo-only` (repo files only), `--user-only` (this computer only).
Re-running is safe; it updates in place.

**Teammates (after the repo files are committed):** clone the repo, then set up their computer only:

| macOS | Windows |
|---|---|
| `python3 .guards/setup/install.py --user-only` | `py .guards\setup\install.py --user-only` |

## Day to day

Nothing to do: the proxy starts when you log in. If you sign in to Databricks after logging in
to your computer, the proxy picks the login up within about 15 seconds. Until then it answers
the agent with "waiting for the developer's Databricks login".

| Task | macOS | Windows |
|---|---|---|
| Is it running, and as whom? | `python3 ~/.databricks-guard/bin/proxy_service.py status` | `py %USERPROFILE%\.databricks-guard\bin\proxy_service.py status` |
| Full self-test | `… proxy_service.py doctor` | `… proxy_service.py doctor` |
| Restart (e.g. after re-login) | `… proxy_service.py restart` | `… proxy_service.py restart` |
| Remove the service | `… proxy_service.py uninstall` | `… proxy_service.py uninstall` |
| Compliance check (in the repo) | `python3 .guards/databricks_guard.py verify` | `py .guards\databricks_guard.py verify` |

`doctor` checks, on this machine:
1. Each installed hook command really **blocks** a SQL query and **allows** `git status`, in every
   shell present (Windows: cmd, PowerShell, pwsh, Git Bash; macOS: sh, zsh, bash).
2. The proxy is listening, knows whom it acts as, and refuses a SQL statement request (403).
3. The `[agent]` profile points at the proxy.

`verify` exits `1` (NOT COMPLIANT) when any of these happened:
- the proxy blocked a request;
- the proxy forwarded something not on the allowlist;
- a hook blocked a call;
- a re-scanned transcript contains a violation.

It warns when Databricks commands ran but the proxy saw no traffic, and when either log is
missing. Useful flags: `--since 2026-11-10`, `--transcripts ~/.claude/projects/`, `--strict`,
`--json`. The proxy log is shared by all your repos, so `verify` shows all agent traffic from
this computer.

## What is allowed

| Layer | Allowed |
|---|---|
| SDK | `catalogs.list/get`, `schemas.list/get`, `tables.list/get/list_summaries/exists`, `metastores.current/summary`, `current_user.me`, with `WorkspaceClient(profile="agent")` |
| CLI | `databricks -p agent catalogs|schemas|tables list|get…` (also `$env:DATABRICKS_CONFIG_PROFILE="agent"`) |
| Proxy (HTTP) | `GET /api/2.1/unity-catalog/{catalogs,schemas,tables}[/{name}]`, `tables/{name}/exists`, `table-summaries`, `metastore_summary`, `current-metastore-assignment`, `scim/v2/Me`, `/.well-known/databricks-config` |
| Files | Writing any code (SQL, PySpark, notebooks). The agent just can't run it. |

## What is blocked

The full list is in the rule file. In short:
- **Execution**: SQL in any form, Spark / Databricks Connect, notebooks, jobs, bundles, clusters
  and warehouses
- **Data reads**: Genie, dashboards, serving, vector search, files, workspace export, secrets,
  storage credentials
- **Indirect routes** (bash/zsh, cmd and PowerShell):
  - scripts, notebooks, `.ps1`/`.cmd` files and Makefiles that would do any of the above
  - `powershell -Command`, `cmd /c`, `-EncodedCommand`, `iex (irm …)`, code piped into interpreters
- **Credentials**:
  - `~/.databrickscfg`, the token cache, Keychain / Credential Manager (`security`, `cmdkey`, `keyring`, …)
  - `databricks auth token`, `$env:DATABRICKS_TOKEN` / `%DATABRICKS_TOKEN%`, env dumps
- **Profile bypass**: any profile but `agent`, `host=`/`token=`, `--host`, `DATABRICKS_*` overrides
  (`export`, `$env:`, `set`, `setx`)
- **Tampering**:
  - editing or deleting the guard, logs or hook configs;
  - starting, stopping or reconfiguring the proxy or its service (`launchctl`, `schtasks`,
    `Stop-ScheduledTask`, `taskkill … python`, `pkill python`, …)

## Tests

`python3 -m unittest discover -s .guards/tests` (Windows: `py -m unittest discover -s .guards\tests`).
There are 51 tests, including:
- a real `databricks-sdk` client going through the proxy, and a simulated U2M login;
- Windows and PowerShell command patterns;
- LaunchAgent and Task Scheduler definitions;
- the installer, including migrating an older install.

## Limits

- **Testing.** Every change is tested automatically on real macOS, Windows and Linux machines
  (`.github/workflows/tests.yml`). That includes a real install of the hooks and the login service
  on macOS and Windows. Still, run `doctor` on your own machine once: it is the definitive check
  for your setup.
- **Same OS user.** The agent runs as you. The hook blocks the known ways to reach your U2M
  token, and `verify` warns if traffic skips the proxy. This is a strong guardrail, not a
  sandbox. For a hard boundary:
  - run the agent in a container or VM that can reach only the proxy; or
  - have the proxy log in as a dedicated identity with Unity Catalog `BROWSE` only.
- **Fails closed.** If a guard crashes, the call is denied. If the proxy is down, the agent's
  Databricks calls fail; they never fall back to your real login.
- **Windows paths with spaces.** The installer uses 8.3 short names. If short names are
  disabled and your Python path has spaces, `doctor` will flag PowerShell. Fix it by
  installing Python in a path without spaces, or enabling 8.3 names.
