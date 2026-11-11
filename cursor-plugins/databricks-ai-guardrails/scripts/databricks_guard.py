#!/usr/bin/env python3
"""
databricks_guard.py: deterministic enforcement and verification for the
"Databricks: Metadata Only, Generate Code, Never Execute" rule.

Standard library only (Python 3.8+). Same input gives the same verdict.

Subcommands
-----------
  hook        Pre-execution hook. Reads the hook JSON on stdin and blocks violating calls.
              --agent claude   Claude Code PreToolUse hook (exit 2 + stderr = block)
              --agent cursor   Cursor beforeShellExecution / beforeMCPExecution / preToolUse
  check       Classify one command (or a --file) and print the verdict. Handy for testing.
  scan        After the fact: scan Claude Code transcripts (*.jsonl), or any JSONL of
              {tool_name, tool_input} / {command}, for calls that broke the rule.
  report      Summarize the decision log the hook writes (.databricks-guard/decisions.jsonl).
  audit       Check an exported Databricks audit log (system.access.audit) or query history
              (system.query.history) for events caused by the agent's principal.
  audit-sql   Print the SQL a HUMAN runs to export those audit rows (the agent never runs it).
  verify      LOCAL check for when audit logs aren't available: reads the metadata proxy's
              request log (.databricks-guard/proxy.jsonl) plus the hook log, and optionally
              re-scans transcripts. Exit 1 if anything broke the rule.

Exit codes for check/scan/report/audit: 0 = clean, 1 = violations found, 3 = usage error.
"""
from __future__ import annotations

import argparse
import csv
import datetime as _dt
import hashlib
import json
import os
import re
import shlex
import sys
import tempfile
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

VERSION = "1.0.0"
RULE_NAME = "Databricks metadata-only rule"

# --------------------------------------------------------------------------------------
# POLICY. Everything here is data, so the rule file and this checker stay in sync.
# --------------------------------------------------------------------------------------

# databricks-sdk WorkspaceClient calls the agent MAY execute: (service, method)
SDK_ALLOW: Set[Tuple[str, str]] = {
    ("catalogs", "list"), ("catalogs", "get"),
    ("schemas", "list"), ("schemas", "get"),
    ("tables", "list"), ("tables", "get"), ("tables", "list_summaries"), ("tables", "exists"),
    ("metastores", "current"), ("metastores", "summary"),
    ("current_user", "me"),
}

# WorkspaceClient service attribute names. Any call <svc>.<method>( where svc is in
# this set and the pair is not in SDK_ALLOW is denied (default deny).
SDK_SERVICES: Set[str] = {
    "access_control", "account_access_control_proxy", "alerts", "alerts_legacy", "apps",
    "artifact_allowlists", "catalogs", "clean_rooms", "cluster_policies", "clusters",
    "command_execution", "connections", "consumer_listings", "credentials", "current_user",
    "dashboard_widgets", "dashboards", "data_sources", "dbfs", "dbsql_permissions",
    "experiments", "external_locations", "files", "functions", "genie", "git_credentials",
    "global_init_scripts", "grants", "groups", "instance_pools", "instance_profiles",
    "ip_access_lists", "jobs", "lakeview", "libraries", "metastores", "model_registry",
    "model_versions", "online_tables", "permissions", "pipelines", "policy_families",
    "provider_listings", "providers", "quality_monitors", "queries", "queries_legacy",
    "query_execution", "query_history", "query_visualizations", "recipients",
    "registered_models", "repos", "schemas", "secrets", "service_principals",
    "serving_endpoints", "shares", "statement_execution", "storage_credentials",
    "system_schemas", "table_constraints", "tables", "temporary_path_credentials",
    "temporary_table_credentials", "token_management", "tokens", "users",
    "vector_search_endpoints", "vector_search_indexes", "volumes", "warehouses",
    "workspace", "workspace_bindings", "workspace_conf", "database", "lakebase",
}

# Service names that are denied even when only referenced (aliasing, getattr tricks).
SDK_SERVICE_REFERENCE_DENY = {
    "statement_execution": "databrickssql.commandSubmit / executeAdhocQuery",
    "command_execution": "notebook.runCommand",
    "temporary_table_credentials": "unityCatalog.generateTemporaryTableCredential",
    "temporary_path_credentials": "unityCatalog.generateTemporaryPathCredential",
    "query_execution": "dashboards.executeQuery",
}

# Specific method names denied wherever they appear as a call (catches aliased clients).
SDK_METHOD_DENY = {
    "execute_statement": "databrickssql.commandSubmit",
    "get_statement_result_chunk_n": "databrickssql.downloadQueryResult",
    "execute_command": "notebook.runCommand",
    "create_and_wait": "clusters.create",
    "ensure_cluster_is_running": "clusters.start",
    "run_now": "jobs.runNow",
    "run_now_and_wait": "jobs.runNow",
    "submit_and_wait": "jobs.submitRun",
    "start_conversation": "aibiGenie.executeQuery",
    "start_conversation_and_wait": "aibiGenie.executeQuery",
    "create_message_and_wait": "aibiGenie.executeMessageQuery",
    "execute_message_query": "aibiGenie.executeMessageQuery",
    "execute_message_attachment_query": "aibiGenie.executeMessageAttachmentQuery",
    "get_message_query_result": "aibiGenie.getMessageQueryResult",
    "get_message_attachment_query_result": "aibiGenie.getMessageAttachmentQueryResult",
    "query_index": "vectorSearch query",
    "scan_index": "vectorSearch scan",
    "generate_temporary_table_credentials": "unityCatalog.generateTemporaryTableCredential",
    "generate_temporary_path_credentials": "unityCatalog.generatePathCredential",
    "get_secret": "secrets.getSecret",
    "download_to": "filesystem.filesGet",
}

# Other code patterns that execute queries or read data. Applied only when the text
# touches Databricks (see DATABRICKS_MARKERS).
CODE_DENY: List[Tuple[str, str]] = [
    (r"\bfrom\s+databricks\s+import\s+sql\b|\bdatabricks\.sql\b|\bsql\.connect\s*\(",
     "databricks-sql-connector (executes SQL on a warehouse)"),
    (r"\bDatabricksSession\b|\bdatabricks\.connect\b",
     "Databricks Connect session (executes Spark remotely)"),
    (r"\bspark\.(sql|table|createDataFrame|range)\s*\(|\bspark\.(read|readStream|catalog)\s*\.\s*\w+",
     "Spark query/read"),
    (r"\bdbutils\.(fs|notebook|secrets|jobs|data|widgets|library)\b",
     "dbutils (file/secret/notebook access)"),
    (r"/api/2\.\d/sql/statements", "SQL Statement Execution REST API"),
    (r"jdbc:databricks:|databricks\+connector://|databricks://|\bSimba\b",
     "JDBC/ODBC/SQLAlchemy connection to Databricks"),
    (r"\b\w*(cursor|cur|conn|connection|engine)\.(execute|executemany|exec_driver_sql)\s*\(",
     "DB-API/SQLAlchemy execute"),
    (r"\b(pd|pandas|pl|polars)\.read_(sql|sql_query|sql_table|database)\w*\s*\(",
     "dataframe read_sql"),
    (r"\.api_client\.do\s*\(|\bApiClient\b\s*\(.*\)\.do\s*\(",
     "raw ApiClient.do (bypasses the allowlist)"),
    (r"\bgetattr\s*\(\s*\w+\s*,\s*[\"'](statement_execution|command_execution|"
     r"temporary_table_credentials|genie|jobs|clusters)[\"']",
     "dynamic attribute access to a denied service"),
    (r"%sql\b|^\s*%%sql\b|\bsqlContext\.sql\s*\(",
     "notebook SQL magic"),
]

HTTP_LIB = re.compile(r"\b(requests|httpx|urllib\.request|urllib3|aiohttp|http\.client)\b")
HTTP_WRITE = re.compile(r"\b(requests|httpx|session|client)\.(post|put|patch|delete|request)\s*\(",
                        re.I)

DATABRICKS_MARKERS = re.compile(
    r"databricks|DATABRICKS_|\bdbutils\b|WorkspaceClient|DatabricksSession|dbsqlcli|"
    r"\.cloud\.databricks\.com|azuredatabricks\.net|gcp\.databricks\.com",
    re.I,
)

UC_METADATA_PATH = re.compile(
    r"^/api/2\.[01]/unity-catalog/((catalogs|schemas|tables)(/[^/\s?'\"]+)?|"
    r"tables/[^/\s?'\"]+/exists|table-summaries|metastore_summary|current-metastore-assignment)"
    r"(\?[^\s'\"]*)?$"
)

# ---- Local-only mode (no access to workspace audit logs) -------------------------------
# With --require-profile <name> (or DBX_GUARD_REQUIRED_PROFILE), the agent may talk to
# Databricks ONLY through that profile, which points at the local metadata proxy.
CTX: Dict[str, object] = {"required_profile": os.environ.get("DBX_GUARD_REQUIRED_PROFILE") or None,
                          "env_profile_ok": False,
                          # "cowork": Claude Cowork sandbox (plugin). Connector names can be opaque there,
                          # so any tool whose NAME says it runs queries is denied, Databricks hint or not.
                          "mode": os.environ.get("DBX_GUARD_MODE", "local")}

STRICT_QUERY_TOOL = re.compile(
    r"(execute|run|submit|exec)[_-]?(sql|query|queries|statement|command|notebook|job|code|python|spark)|"
    r"(^|[_-])(sql|dbsql|hql|spark[_-]?sql)($|[_-])|statement|genie|warehouse|query[_-]?(data|table|rows)|"
    r"(sample|preview|read)[_-]?(table|rows|data)", re.I)

CRED_FILES = re.compile(r"\.databrickscfg|\.databricks[/\\]token-cache|token-cache\.json|"
                        r"databricks[/\\]\.?credentials|\.netrc\b", re.I)
CRED_SHELL = re.compile(
    r"\bdatabricks\s+(auth\s+(token|env|describe\s+.*--sensitive)|configure)\b|"
    # OAuth U2M tokens live in the OS keychain (CLI >= 1.0) - block keychain readers
    r"\bsecurity\s+(find-(generic|internet)-password|dump-keychain|export)\b|"
    r"\bsecret-tool\s+(lookup|search)\b|\bcmdkey\b|Get-StoredCredential|\bkeyring\s+get\b|"
    r"\bkeyring\.get_(password|credential)\b|\bgnome-keyring|\bkwallet-query\b|"
    r"/oidc/v1/token\b|"
    r"\$\{?DATABRICKS_(TOKEN|CLIENT_SECRET|PASSWORD)\b|"
    # Windows: PowerShell / cmd env reads and Credential Manager
    r"\$env:DATABRICKS_(TOKEN|CLIENT_SECRET|PASSWORD)\b|%DATABRICKS_(TOKEN|CLIENT_SECRET|PASSWORD)%|"
    r"\[(System\.)?Environment\]::GetEnvironmentVariable\(\s*['\"]DATABRICKS_|"
    r"\bGet-(Item|Content|ChildItem)\s+env:\\?DATABRICKS_|\bset\s+DATABRICKS_?\w*\s*($|[;&|])|"
    r"\bvaultcmd\b|\bCredRead|Windows\.Security\.Credentials|PasswordVault|"
    r"\b(printenv|getenv)\s+DATABRICKS_(TOKEN|CLIENT_SECRET|PASSWORD)\b", re.I)
ENV_DUMP = re.compile(r"(^|[;&|(]\s*)(env|printenv|set|export\s+-p|declare\s+-x)\s*($|[;&|)])|"
                      r"\b(Get-ChildItem|gci|dir|ls|Get-Item|gi)\s+env:\\?\s*($|[;&|)])|"
                      r"\[(System\.)?Environment\]::GetEnvironmentVariables\(", re.M | re.I)
SHELL_ENV_OVERRIDE = re.compile(
    r"(^|[\s;&|(])(export\s+|setenv\s+)?DATABRICKS_(HOST|TOKEN|CLIENT_ID|CLIENT_SECRET|CONFIG_FILE|"
    r"ACCOUNT_ID|AUTH_TYPE|AUTH_STORAGE|PASSWORD|USERNAME|AZURE_\w+|GOOGLE_\w+|SERVERLESS_\w+|CLUSTER_ID|"
    r"WAREHOUSE_ID)\s*=")
SHELL_PROFILE_ASSIGN = re.compile(r"(^|[\s;&|(])(export\s+)?DATABRICKS_CONFIG_PROFILE\s*=\s*['\"]?([\w.-]+)")
WIN_ENV_OVERRIDE = re.compile(
    r"(\$env:|\bset\s+\"?|\bsetx\s+|SetEnvironmentVariable\(\s*['\"])DATABRICKS_(HOST|TOKEN|CLIENT_ID|"
    r"CLIENT_SECRET|CONFIG_FILE|ACCOUNT_ID|AUTH_TYPE|AUTH_STORAGE|PASSWORD|USERNAME|AZURE_\w+|GOOGLE_\w+|"
    r"CLUSTER_ID|WAREHOUSE_ID)\b", re.I)
WIN_PROFILE_ASSIGN = re.compile(r"(?:\$env:|\bset\s+\"?)DATABRICKS_CONFIG_PROFILE\s*=\s*['\"]?([\w.-]+)", re.I)
CODE_CLIENT_CALL = re.compile(
    r"\b(WorkspaceClient|AccountClient|Config|sql\.connect|DatabricksSession\.builder\.\w+)\s*\(", re.S)
CODE_CRED_KW = re.compile(r"\b(host|token|client_secret|client_id|password|username|config_file|"
                          r"azure_\w+|google_\w+|auth_type|credentials_strategy|credentials_provider|"
                          r"server_hostname|access_token)\s*=")
CODE_PROFILE_KW = re.compile(r"\bprofile\s*=\s*(['\"])([\w.-]*)\1|\bprofile\s*=\s*([^'\"\s,)][^,)]*)")
CODE_ENV_WRITE = re.compile(r"os\.environ\s*(\[\s*['\"]DATABRICKS_\w+['\"]\s*\]\s*=|"
                            r"\.(update|setdefault)\s*\([^)]*DATABRICKS_)|os\.putenv\s*\(\s*['\"]DATABRICKS_")
PROTECTED = re.compile(r"databricks-guard|\.guards[/\\]|\.cursor[/\\]hooks\.json|"
                       r"\.claude[/\\]settings[\w.]*json|dbx_metadata_proxy|databricks_guard\.py|"
                       r"proxy_service\.py|run_proxy\.py|proxy-config\.json|DatabricksGuardProxy|"
                       r"\.cursor[/\\]plugins|\.claude[/\\]plugins", re.I)
WRITE_OPS = re.compile(r"(^|[\s;&|(])(rm|mv|cp|tee|truncate|chmod|chown|ln|unlink|shred|install|"
                       r"rsync|dd|kill|pkill|killall)\b|\bsed\s+(-\w*\s+)*-i|>{1,2}\s*\S*"
                       r"(\.databricks-guard|\.guards/|hooks\.json|settings[\w.]*json)|\bgit\s+(checkout|"
                       r"restore|rm|stash|clean)\b|"
                       # Windows / PowerShell file and process ops, service control on both OSes
                       r"\b(Remove-Item|ri|del|erase|rd|rmdir|Move-Item|mi|Rename-Item|ren|Set-Content|sc|"
                       r"Out-File|Add-Content|ac|Clear-Content|clc|Copy-Item|cpi|New-Item|ni|icacls|attrib|"
                       r"takeown|Stop-Process|spps|taskkill|Stop-ScheduledTask|Unregister-ScheduledTask|"
                       r"Disable-ScheduledTask|Set-ScheduledTask|Register-ScheduledTask)\b|"
                       r"\bschtasks(\.exe)?\s+/(delete|end|change|create)\b|"
                       r"\blaunchctl\s+(bootout|unload|remove|disable|kill|stop|bootstrap|load|enable)\b", re.I)
REMOTE_EXEC = re.compile(
    r"\b(iex|Invoke-Expression)\b[^\n]*\b(irm|iwr|Invoke-RestMethod|Invoke-WebRequest|DownloadString|"
    r"DownloadFile|curl|wget)\b|\b(irm|iwr|Invoke-RestMethod|Invoke-WebRequest)\b[^\n]*\|\s*(iex|"
    r"Invoke-Expression)\b|\b(curl|wget)\b[^\n|]*\|\s*(sudo\s+)?(ba|z|k|da)?sh\b|"
    r"\b(curl|wget)\b[^\n|]*\|\s*python", re.I)
PROXY_START = re.compile(r"\b(dbx_metadata_proxy|run_proxy)\.py\b(?![^\n]*\s(-h|--help)\b)|"
                         r"\bproxy_service\.py\s+(install|uninstall|restart)\b|"
                         r"\binstall\.py\b[^\n]*(--user-only|--no-autostart|--upstream-profile|--uninstall)", re.I)
PROXY_KILL = re.compile(r"\b(pkill|killall)\s+(-\w+\s+)*['\"]?(python|Python)|\btaskkill\b[^\n]*python|"
                        r"\b(Stop-Process|spps)\b[^\n]*python|Get-Process\s+python\w*[^\n]*\|\s*(Stop-Process|spps)|"
                        r"\bkill\s+(-\d+\s+)?\$\(\s*(pgrep|lsof)|\blsof\s+-ti?\s*:?\s*8787[^\n]*\|\s*xargs\s+kill",
                        re.I)


def _call_args(code: str, start: int) -> str:
    """Text inside the parentheses that open at code[start-1] (balanced, bounded)."""
    depth, i = 1, start
    while i < len(code) and depth and i - start < 4000:
        ch = code[i]
        depth += ch == "("
        depth -= ch == ")"
        i += 1
    return code[start:i - 1]


def check_profile_and_creds_code(code: str, where: str, v: "Verdict") -> None:
    req = CTX["required_profile"]
    if CRED_FILES.search(code):
        v.add("deny", "code reads Databricks credential files", where)
    if CODE_ENV_WRITE.search(code):
        v.add("deny", "code overrides DATABRICKS_* environment variables", where)
    if not req:
        return
    for m in CODE_CLIENT_CALL.finditer(code):
        fn = m.group(1)
        args = _call_args(code, m.end())
        if fn == "AccountClient":
            v.add("deny", "AccountClient is not allowed for the agent", where)
            continue
        if fn.startswith("sql.connect") or fn.startswith("DatabricksSession"):
            continue  # already denied by CODE_DENY
        kw = CODE_CRED_KW.search(args)
        if kw:
            v.add("deny", f"{fn}({kw.group(1)}=...) bypasses the '{req}' proxy profile", where)
            continue
        pm = CODE_PROFILE_KW.search(args)
        if pm:
            val = pm.group(2) if pm.group(2) is not None else None
            if val != req:
                v.add("deny", f"{fn}(profile={val or pm.group(3).strip()!s}) must be profile='{req}'", where)
        elif fn == "WorkspaceClient" and not CTX["env_profile_ok"]:
            v.add("deny", f"WorkspaceClient() without profile='{req}' (and DATABRICKS_CONFIG_PROFILE "
                          f"is not set to '{req}') would bypass the local metadata proxy", where)


def check_shell_guardrails(command: str, v: "Verdict") -> None:
    """Credential, override, and tamper checks on raw shell text (always on)."""
    where = command[:200]
    if CRED_FILES.search(command) or CRED_SHELL.search(command):
        v.add("deny", "accesses Databricks credentials (config file, token cache, token env vars)", where)
    if ENV_DUMP.search(command):
        v.add("deny", "dumps the environment (may expose Databricks credentials)", where)
    if SHELL_ENV_OVERRIDE.search(command) or WIN_ENV_OVERRIDE.search(command):
        v.add("deny", "sets DATABRICKS_* host/credential variables (bypasses the approved profile)", where)
    req = CTX["required_profile"]
    assigned = [m.group(3) for m in SHELL_PROFILE_ASSIGN.finditer(command)] + \
        [m.group(1) for m in WIN_PROFILE_ASSIGN.finditer(command)]
    for val in assigned:
        if req and val != req:
            v.add("deny", f"DATABRICKS_CONFIG_PROFILE={val} (must be '{req}')", where)
        elif req:
            CTX["env_profile_ok"] = True
    if PROTECTED.search(command) and WRITE_OPS.search(command):
        v.add("deny", "modifies or stops the guard, its logs, its hook config, or the metadata proxy", where)
    if REMOTE_EXEC.search(command):
        v.add("deny", "executes code downloaded at run time; cannot be verified", where)
    if PROXY_START.search(command):
        v.add("deny", "only the developer starts, stops or reconfigures the metadata proxy", where)
    if PROXY_KILL.search(command):
        v.add("deny", "would stop Python processes, including the metadata proxy", where)
API_PATH = re.compile(r"/api/\d\.\d/[A-Za-z0-9_\-./{}$%]+(\?[^\s'\"]*)?")
DBX_HOST_HINT = re.compile(r"\.cloud\.databricks\.com|azuredatabricks\.net|gcp\.databricks\.com|"
                           r"\$\{?DATABRICKS_|\$env:DATABRICKS_|%DATABRICKS_|(127\.0\.0\.1|localhost):8787|"
                           r"/api/2\.\d/|/oidc/", re.I)

# Databricks CLI: (group, verb) pairs that are allowed. Everything else is denied.
CLI_ALLOW: Set[Tuple[str, str]] = {
    ("catalogs", "list"), ("catalogs", "get"),
    ("schemas", "list"), ("schemas", "get"),
    ("tables", "list"), ("tables", "get"), ("tables", "list-summaries"), ("tables", "exists"),
    ("metastores", "current"), ("metastores", "summary"),
    ("current-user", "me"),
    ("auth", "profiles"), ("auth", "describe"),
}
CLI_ALWAYS_OK = {"--version", "-v", "version", "--help", "-h", "help", "completion"}
CLI_FLAGS_WITH_VALUE = {"-p", "--profile", "-o", "--output", "--log-level", "--log-file",
                        "--log-format", "-t", "--target", "--host", "--account-id"}

# Executables whose arguments are code or scripts we must inspect.
PY_INTERPRETERS = re.compile(r"^(python(\d+(\.\d+)?)?|py|ipython|pypy3?)$")
SHELLS = {"bash", "sh", "zsh", "dash", "ksh"}
RUNNER_PREFIXES = {"uv", "uvx", "poetry", "pipenv", "hatch", "pdm", "rye", "conda", "mamba"}
WRAPPERS = {"sudo", "env", "time", "nohup", "nice", "exec", "command", "xargs", "timeout",
            "stdbuf", "caffeinate"}
DBT_EXEC_VERBS = {"run", "build", "test", "seed", "snapshot", "show", "run-operation",
                  "compile", "debug", "docs", "source", "retry", "clone"}
SQL_CLIENTS = {"dbsqlcli", "databricks-sql-cli", "isql", "beeline", "spark-sql",
               "spark-submit", "pyspark", "databricks-connect"}
HTTP_CLIENTS = {"curl", "wget", "http", "https", "xh", "httpie"}
MOCK_MARKERS = re.compile(r"create_autospec|MagicMock|\bMock\(|mock\.patch|@patch|monkeypatch|"
                          r"unittest\.mock|pytest_mock|mocker\.")

# MCP tool classification
MCP_DATABRICKS_HINT = re.compile(r"databricks|dbsql|genie|unity|\buc[_-]|lakehouse|"
                                 r"lakebase|delta|spark|warehouse", re.I)
MCP_ALLOW_NAME = re.compile(
    r"(^|[_\-.])(list|get|describe|show)[_\-]?(catalogs?|schemas?|tables?|table[_\-]?summar(y|ies)|"
    r"metastores?|columns?)($|[_\-.])", re.I)
MCP_DENY_NAME = re.compile(
    r"sql|query|queries|statement|execute|exec|run|command|genie|sample|preview|read|"
    r"download|export|secret|credential|search|notebook|job|cluster|warehouse|"
    r"select|fetch|rows?|data|ask|chat|spark|python|code|upload|write|create|update|delete",
    re.I)
SQL_IN_ARGS = re.compile(
    r"\b(select|show\s+(tables|schemas|databases|catalogs|columns|create)|describe|"
    r"insert|update|delete|merge|create|drop|alter|optimize|vacuum|explain|with)\b"
    r"[\s\S]{0,200}?\b(from|table|into|as|in|\w+\.\w+)\b", re.I)

# Audit-log events (service_name, action_name)
AUDIT_ALLOWED: Set[Tuple[str, str]] = {
    ("unityCatalog", a) for a in (
        "listCatalogs", "getCatalog", "listSchemas", "getSchema", "listTables", "getTable",
        "listTableSummaries", "getMetastore", "getMetastoreSummary", "tableExists",
        "getCurrentMetastoreAssignment", "metadataSnapshot")
} | {
    ("accounts", a) for a in (
        "tokenLogin", "oidcTokenAuthorization", "mintOAuthToken", "mintOAuthAuthorizationCode",
        "accountInHouseOAuthClientAuthentication", "jwtLogin", "login", "logout")
} | {("accounts", "getCurrentUser"), ("iam", "getCurrentUser")}

AUDIT_DENIED: Dict[Tuple[str, str], str] = {
    ("databrickssql", "commandSubmit"): "SQL statement submitted",
    ("databrickssql", "commandFinish"): "SQL statement finished",
    ("databrickssql", "executeAdhocQuery"): "ad-hoc SQL query",
    ("databrickssql", "downloadQueryResult"): "query result download",
    ("notebook", "runCommand"): "notebook command executed",
    ("jobs", "runNow"): "job run triggered",
    ("jobs", "submitRun"): "one-time job run submitted",
    ("jobs", "runCommand"): "command run in a job",
    ("unityCatalog", "generateTemporaryTableCredential"): "direct table storage credential",
    ("unityCatalog", "generateTemporaryPathCredential"): "direct path storage credential",
    ("unityCatalog", "generateTemporaryVolumeCredential"): "direct volume storage credential",
    ("secrets", "getSecret"): "secret read",
    ("workspace", "workspaceExport"): "workspace export",
    ("dashboards", "executeQuery"): "dashboard query",
    ("dashboards", "getQueryResult"): "dashboard query result",
    ("dashboards", "triggerDashboardSnapshot"): "dashboard snapshot",
    ("alerts", "previewAlertExecute"): "alert query preview",
    ("alerts", "runNowAlert"): "alert query run",
    ("clusters", "create"): "compute created",
    ("clusters", "start"): "compute started",
    ("clusters", "restart"): "compute restarted",
    ("serverlessCompute", "createServerlessCompute"): "serverless compute created",
    ("dbfs", "read"): "DBFS file read",
    ("filesystem", "filesGet"): "file download",
    ("dbfs", "mount"): "storage mount",
}
for _a in ("executeQuery", "getQueryResult", "executeMessageQuery", "executeMessageAttachmentQuery",
           "getMessageQueryResult", "getMessageAttachmentQueryResult", "genieExecuteMessageQuery",
           "genieExecuteMessageAttachmentQuery", "executeFullQueryResult",
           "summarizeSqlExecutionResults"):
    AUDIT_DENIED[("aibiGenie", _a)] = "Genie query"
for _a in ("createGenieChatResponse", "runCodeInSandbox", "mcpToolInvocation", "mcpProxy"):
    AUDIT_DENIED[("genieChat", _a)] = "Genie chat / sandbox execution"

LOG_DIR_NAME = ".databricks-guard"
LOG_FILE_NAME = "decisions.jsonl"
MAX_SCAN_FILES = 200
MAX_FILE_BYTES = 2_000_000
MAX_IMPORT_DEPTH = 4


# --------------------------------------------------------------------------------------
# Verdict
# --------------------------------------------------------------------------------------
ORDER = {"allow": 0, "warn": 1, "deny": 2}


class Verdict:
    def __init__(self) -> None:
        self.level = "allow"
        self.findings: List[Dict[str, str]] = []
        self.scanned_files: List[str] = []

    def add(self, level: str, reason: str, where: str = "", audit: str = "") -> None:
        if any(f["reason"] == reason and f["level"] == level for f in self.findings):
            return
        self.findings.append({"level": level, "reason": reason, "where": where, "audit": audit})
        if ORDER[level] > ORDER[self.level]:
            self.level = level

    def merge(self, other: "Verdict") -> None:
        for f in other.findings:
            self.add(f["level"], f["reason"], f["where"], f["audit"])
        for s in other.scanned_files:
            if s not in self.scanned_files:
                self.scanned_files.append(s)

    def summary(self) -> str:
        lines = []
        for f in self.findings:
            if f["level"] == "allow":
                continue
            s = f"[{f['level'].upper()}] {f['reason']}"
            if f["audit"]:
                s += f" (audit: {f['audit']})"
            if f["where"]:
                s += f" @ {f['where']}"
            lines.append(s)
        return "\n".join(lines) or "allowed"

    def to_dict(self) -> dict:
        return {"verdict": self.level, "findings": self.findings, "scanned_files": self.scanned_files}


# --------------------------------------------------------------------------------------
# Code analysis
# --------------------------------------------------------------------------------------
SDK_CALL = re.compile(r"\.([a-z_][a-z0-9_]*)\s*\.\s*([a-z_][a-z0-9_]*)\s*\(")
METHOD_CALL = re.compile(r"\b([a-z_][a-z0-9_]*)\s*\(")
SERVICE_REF = re.compile(r"\b(" + "|".join(map(re.escape, SDK_SERVICE_REFERENCE_DENY)) + r")\b")


def _strip_comments(code: str) -> str:
    out = []
    for line in code.splitlines():
        s = line.lstrip()
        if s.startswith("#") and not s.startswith("#!"):
            continue
        if s.startswith("--"):
            continue
        out.append(line)
    return "\n".join(out)


def analyze_code(code: str, where: str = "<inline>", force: bool = False) -> Verdict:
    """Analyze Python (or similar) source that is about to be EXECUTED."""
    v = Verdict()
    if not force and not DATABRICKS_MARKERS.search(code):   # comments count as markers
        return v
    code = _strip_comments(code)

    for m in SDK_CALL.finditer(code):
        svc, meth = m.group(1), m.group(2)
        if svc in SDK_SERVICES:
            if (svc, meth) in SDK_ALLOW:
                v.add("allow", f"metadata call {svc}.{meth}()", where)
            else:
                v.add("deny", f"SDK call {svc}.{meth}() is not on the metadata allowlist", where,
                      SDK_SERVICE_REFERENCE_DENY.get(svc, SDK_METHOD_DENY.get(meth, "")))

    for m in METHOD_CALL.finditer(code):
        name = m.group(1)
        if name in SDK_METHOD_DENY:
            v.add("deny", f"call to {name}()", where, SDK_METHOD_DENY[name])

    for m in SERVICE_REF.finditer(code):
        v.add("deny", f"reference to denied SDK service '{m.group(1)}'", where,
              SDK_SERVICE_REFERENCE_DENY[m.group(1)])

    for pat, why in CODE_DENY:
        if re.search(pat, code, re.M):
            v.add("deny", why, where)

    check_profile_and_creds_code(code, where, v)

    if HTTP_LIB.search(code):
        paths = [p.group(0) for p in API_PATH.finditer(code)]
        if HTTP_WRITE.search(code):
            v.add("deny", "HTTP write call (POST/PUT/PATCH/DELETE) in Databricks code", where)
        elif not paths:
            v.add("deny", "raw HTTP client used against Databricks without an allowlisted "
                          "Unity Catalog metadata path", where)
        else:
            for p in paths:
                if not UC_METADATA_PATH.match(p):
                    v.add("deny", f"HTTP call to non-metadata API path {p}", where)
    return v


def notebook_source(path: Path) -> str:
    try:
        nb = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        cells = nb.get("cells", [])
        return "\n".join("".join(c.get("source", [])) if isinstance(c.get("source"), list)
                         else str(c.get("source", "")) for c in cells
                         if c.get("cell_type") == "code")
    except Exception:
        return path.read_text(encoding="utf-8", errors="replace")


def read_source(path: Path) -> str:
    if path.suffix == ".ipynb":
        return notebook_source(path)
    try:
        if path.stat().st_size > MAX_FILE_BYTES:
            return path.read_bytes()[:MAX_FILE_BYTES].decode("utf-8", errors="replace")
    except OSError:
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


IMPORT_RE = re.compile(r"^\s*(?:from\s+(\.*[\w.]*)\s+import\s+([\w*,\s()]+)|import\s+([\w.,\s]+))",
                       re.M)


def _resolve_module(mod: str, base_dir: Path, roots: Sequence[Path]) -> List[Path]:
    dots = len(mod) - len(mod.lstrip("."))
    name = mod.lstrip(".")
    candidates_dirs = [base_dir] if dots else list(roots) + [base_dir]
    if dots > 1:
        d = base_dir
        for _ in range(dots - 1):
            d = d.parent
        candidates_dirs = [d]
    out = []
    rel = Path(*name.split(".")) if name else Path()
    for d in candidates_dirs:
        for cand in (d / rel.with_suffix(".py") if name else None,
                     d / rel / "__init__.py"):
            if cand is not None and cand.is_file():
                out.append(cand.resolve())
                break
    return out


def collect_local_sources(entry: Path, roots: Sequence[Path]) -> List[Path]:
    """Entry file plus local modules it imports (bounded depth and count)."""
    seen: List[Path] = []
    queue: List[Tuple[Path, int]] = [(entry.resolve(), 0)]
    while queue and len(seen) < MAX_SCAN_FILES:
        p, depth = queue.pop(0)
        if p in seen or not p.is_file():
            continue
        seen.append(p)
        if p.suffix not in (".py", ".ipynb") or depth >= MAX_IMPORT_DEPTH:
            continue
        src = read_source(p)
        for r in _referenced_files(src, p.parent):
            if r.resolve() not in seen:
                queue.append((r.resolve(), depth + 1))
        for m in IMPORT_RE.finditer(src):
            mods: List[str] = []
            if m.group(1) is not None:
                base = m.group(1)
                mods.append(base)
                for nm in re.split(r"[,\s()]+", m.group(2)):
                    if nm and nm != "*" and nm != "as":
                        mods.append((base + "." if base and not base.endswith(".") else base) + nm)
            else:
                mods.extend(x.strip().split(" ")[0] for x in m.group(3).split(","))
            for mod in mods:
                if not mod:
                    continue
                for r in _resolve_module(mod, p.parent, roots):
                    if r not in seen:
                        queue.append((r, depth + 1))
    return seen


def analyze_files(paths: Iterable[Path], roots: Sequence[Path], soften_mocked: bool = False) -> Verdict:
    v = Verdict()
    all_files: List[Path] = []
    for p in paths:
        for f in collect_local_sources(p, roots):
            if f not in all_files:
                all_files.append(f)
    texts = {f: read_source(f) for f in all_files[:MAX_SCAN_FILES]}
    combined_touches = any(DATABRICKS_MARKERS.search(t) for t in texts.values())
    for f, t in texts.items():
        v.scanned_files.append(str(f))
        if f.suffix == ".sh":
            v.merge(analyze_shell(t, cwd=f.parent, roots=roots, depth=1))
            continue
        fv = analyze_code(t, where=str(f), force=combined_touches)
        if soften_mocked and fv.level == "deny" and MOCK_MARKERS.search(t):
            for fd in fv.findings:
                if fd["level"] == "deny":
                    fd["level"] = "warn"
                    fd["reason"] += " (file uses mocks; verify no live workspace is hit)"
            fv.level = max((fd["level"] for fd in fv.findings), key=ORDER.get, default="allow")
        v.merge(fv)
    return v


# --------------------------------------------------------------------------------------
# Shell analysis
# --------------------------------------------------------------------------------------
HEREDOC_RE = re.compile(r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")


def _split_heredocs(command: str) -> Tuple[List[str], List[Tuple[str, str]]]:
    """Return (shell lines, [(heredoc_owner_line, body)])."""
    lines = command.splitlines() or [command]
    shell_lines: List[str] = []
    heredocs: List[Tuple[str, str]] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        m = HEREDOC_RE.search(line)
        shell_lines.append(line)
        if m:
            delim = m.group(2)
            body = []
            i += 1
            while i < len(lines) and lines[i].strip() != delim:
                body.append(lines[i])
                i += 1
            heredocs.append((line, "\n".join(body)))
        i += 1
    return shell_lines, heredocs


WIN_PATH_HINT = re.compile(r"(^|[\s\"'=(])[A-Za-z]:\\|\.\\|\\\\|[\w~.-]\\[\w~.-]")


def _exe_name(tok: str) -> str:
    """'C:/Py/python.exe' -> 'python'; '/usr/bin/python3' -> 'python3'."""
    name = re.split(r"[/\\]", tok)[-1].lower()
    for suf in (".exe", ".com", ".bat", ".cmd"):
        if name.endswith(suf) and name not in (".cmd", ".bat"):
            return name[: -len(suf)]
    return name


def _tokenize(line: str) -> List[List[str]]:
    """Split a shell line into simple commands (token lists). Handles POSIX, cmd and PowerShell."""
    if WIN_PATH_HINT.search(line):
        line = line.replace("\\", "/")          # Windows paths: backslash is not an escape there
    line = line.replace("`", " ; ").replace("$(", " ; ").replace(")", " ; ")
    try:
        lex = shlex.shlex(line, posix=True, punctuation_chars=";&|()<>")
        lex.whitespace_split = True
        lex.commenters = ""
        toks = list(lex)
    except ValueError:
        toks = re.split(r"\s+", line)
    segs: List[List[str]] = [[]]
    for t in toks:
        if t and set(t) <= set(";&|()<>"):
            # Redirections like > file: drop the operator, keep going in same segment
            if set(t) <= set("<>"):
                segs[-1].append("__REDIR__")
                continue
            segs.append([])
        elif t:
            segs[-1].append(t)
    out = []
    for s in segs:
        # remove redirect targets
        clean: List[str] = []
        skip = False
        for t in s:
            if skip:
                skip = False
                continue
            if t == "__REDIR__":
                skip = True
                continue
            clean.append(t)
        if clean:
            out.append(clean)
    return out


def _unwrap(tokens: List[str]) -> List[str]:
    """Drop env assignments and wrappers like sudo/env/uv run/poetry run."""
    t = list(tokens)
    changed = True
    while t and changed:
        changed = False
        while t and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", t[0]):
            t.pop(0)
            changed = True
        if t and _exe_name(t[0]) in WRAPPERS:
            t.pop(0)
            while t and t[0].startswith("-"):
                t.pop(0)
                if t and re.match(r"^\d+[smhd]?$", t[0]):
                    t.pop(0)
            changed = True
        if t and _exe_name(t[0]) in RUNNER_PREFIXES:
            runner = _exe_name(t.pop(0))
            if runner == "uvx":
                changed = True
                continue
            while t and (t[0].startswith("-") or t[0] in ("run", "exec", "tool")):
                t.pop(0)
            changed = True
    return t


def _resolve_path(arg: str, cwd: Path) -> Optional[Path]:
    p = Path(os.path.expanduser(arg))
    if not p.is_absolute():
        p = cwd / p
    return p if p.exists() else None


def _check_databricks_cli(args: List[str], v: Verdict, where: str) -> None:
    req = CTX["required_profile"]
    prof = None
    for i, a in enumerate(args):
        if a in ("-p", "--profile") and i + 1 < len(args):
            prof = args[i + 1]
        elif a.startswith("--profile="):
            prof = a.split("=", 1)[1]
        if a == "--host" or a.startswith("--host="):
            v.add("deny", "databricks CLI --host override bypasses the approved profile", where)
            return
    if req and not (prof == req or (prof is None and CTX["env_profile_ok"])):
        if not any(a in CLI_ALWAYS_OK for a in args[:1]) and "--help" not in args and "-h" not in args:
            v.add("deny", f"databricks CLI must use the '{req}' profile (add -p {req})", where)
            return
    rest = [a for a in args]
    pos: List[str] = []
    i = 0
    while i < len(rest):
        a = rest[i]
        if a in CLI_FLAGS_WITH_VALUE:
            i += 2
            continue
        if a.startswith("-") and a not in CLI_ALWAYS_OK:
            i += 1
            continue
        pos.append(a)
        i += 1
    if not pos or pos[0] in CLI_ALWAYS_OK or any(a in ("--help", "-h") for a in args):
        v.add("allow", "databricks CLI help/version", where)
        return
    group = pos[0]
    verb = pos[1] if len(pos) > 1 else ""
    if group == "api":
        method = verb.lower()
        path = pos[2] if len(pos) > 2 else ""
        if method == "get" and UC_METADATA_PATH.match(path):
            v.add("allow", f"databricks api get {path}", where)
        else:
            v.add("deny", f"`databricks api {method} {path}` is not an allowlisted metadata GET",
                  where, "databrickssql.commandSubmit" if "sql/statements" in path else "")
        return
    if (group, verb) in CLI_ALLOW:
        v.add("allow", f"databricks {group} {verb}", where)
        return
    audit = {
        "sql": "databrickssql.commandSubmit", "jobs": "jobs.runNow / submitRun",
        "clusters": "clusters.create/start", "fs": "dbfs/filesystem read",
        "workspace": "workspace.workspaceExport", "secrets": "secrets.getSecret",
        "genie": "aibiGenie.executeQuery", "bundle": "jobs.runNow (bundle run/deploy)",
        "statement-execution": "databrickssql.commandSubmit", "warehouses": "warehouse control",
        "pipelines": "pipeline update", "lakeview": "dashboards.executeQuery",
        "temporary-table-credentials": "unityCatalog.generateTemporaryTableCredential",
    }.get(group, "")
    v.add("deny", f"`databricks {group} {verb}` is not on the CLI metadata allowlist", where, audit)


def _has_pipe_into(command: str, exe: str) -> bool:
    return bool(re.search(r"\|\s*(\S*/)?(sudo\s+)?" + re.escape(exe) + r"(\s|$)", command))


REF_FILE = re.compile(r"[\"']([\w./~-]+\.(?:py|ipynb|sh))[\"']")


def _referenced_files(code: str, base: Path) -> List[Path]:
    """Local scripts named in string literals (exec(open('x.py').read()), runpy, subprocess)."""
    out = []
    for m in REF_FILE.finditer(code):
        p = _resolve_path(m.group(1), base)
        if p and p.is_file():
            out.append(p)
    return out


def _dbt_targets_databricks(cwd: Path) -> bool:
    for p in (cwd / "profiles.yml", Path.home() / ".dbt" / "profiles.yml"):
        try:
            if p.is_file() and re.search(r"type:\s*['\"]?databricks", p.read_text(errors="replace")):
                return True
        except OSError:
            pass
    req = "".join(read_source(p) for p in (cwd / "requirements.txt", cwd / "pyproject.toml")
                  if p.is_file())
    return "dbt-databricks" in req


# Hash of the setup kit files the plugin may run for FIRST-TIME setup (install.py and the proxy /
# service helpers). Written by tools/sync_plugins.py; a test checks it. The kit's copy of this guard
# must also be byte-identical to the running guard.
TRUSTED_KIT_SHA256 = "b00bd2b08a4b0766283fdfd6b5279e5358cf3d79bd5a3fe8cd0552959d22cd0b"
TRUSTED_KIT_FILES = ("install.py", "guards/dbx_metadata_proxy.py", "guards/proxy_service.py")
SETUP_ALLOWED_FLAGS = {"--databricks-host": 1, "--upstream-profile": 1, "--port": 1, "--skip-doctor": 0}


def kit_sha256(kit: Path) -> str:
    h = hashlib.sha256()
    for rel in TRUSTED_KIT_FILES:
        h.update(rel.encode() + b"\0" + (kit / rel).read_bytes().replace(b"\r\n", b"\n") + b"\0")
    return h.hexdigest()


def trusted_first_setup(command: str) -> bool:
    """True only for: <python> <this plugin>/setup/install.py [project] [allowed flags], before any
    install exists on this computer, with an untampered kit. Lets a plugin set itself up by chat."""
    kit = Path(__file__).resolve().parent.parent / "setup"
    installer = kit / "install.py"
    try:
        if not installer.is_file() or (USER_GUARD_DIR / "proxy-config.json").exists():
            return False
        norm = lambda b: b.replace(b"\r\n", b"\n")
        if norm((kit / "guards" / "databricks_guard.py").read_bytes()) != norm(Path(__file__).resolve().read_bytes()):
            return False
        if kit_sha256(kit) != TRUSTED_KIT_SHA256:
            return False
    except OSError:
        return False
    if "\n" in command.strip() or re.search(r"[;&|`<>]|\$\(", command):
        return False
    segs = _tokenize(command)
    if len(segs) != 1:
        return False
    toks = _unwrap(segs[0])
    if not toks or not PY_INTERPRETERS.match(_exe_name(toks[0])):
        return False
    args = toks[1:]
    if args[:1] == ["-3"]:                       # Windows: py -3 install.py
        args = args[1:]
    if not args:
        return False
    try:
        if Path(os.path.expanduser(args[0])).resolve() != installer.resolve():
            return False
    except OSError:
        return False
    rest, positional, i = args[1:], 0, 0
    while i < len(rest):
        a = rest[i]
        if a.startswith("--"):
            name = a.split("=", 1)[0]
            if name not in SETUP_ALLOWED_FLAGS:
                return False
            i += 1 + (SETUP_ALLOWED_FLAGS[name] if "=" not in a else 0)
            continue
        positional += 1
        i += 1
    return positional <= 1


def analyze_shell(command: str, cwd: Path, roots: Optional[Sequence[Path]] = None,
                  depth: int = 0) -> Verdict:
    v = Verdict()
    roots = list(roots or [cwd])
    if depth > 3:
        v.add("deny", "shell nesting too deep to verify", "<shell>")
        return v
    if depth == 0 and trusted_first_setup(command):
        v.add("allow", "first-time setup with the plugin's own verified installer", command[:200])
        return v
    check_shell_guardrails(command, v)
    shell_lines, heredocs = _split_heredocs(command)

    interpreter_seen = False
    files_to_scan: List[Path] = []
    pytest_run = False

    for line in shell_lines:
        for seg in _tokenize(line):
            toks = _unwrap(seg)
            if not toks:
                continue
            exe = _exe_name(toks[0])
            args = toks[1:]
            where = " ".join(seg)[:200]

            # A script executed directly: ./run.sh, .\run.ps1, tool.cmd, ./x.py
            direct = _resolve_path(toks[0], cwd) if re.search(r"[/\\]|\.(ps1|sh|cmd|bat|py)$", toks[0], re.I) \
                else None
            if direct and direct.is_file():
                interpreter_seen = True
                if direct.suffix.lower() in (".py", ".ipynb"):
                    files_to_scan.append(direct)
                else:
                    v.scanned_files.append(str(direct))
                    v.merge(analyze_shell(read_source(direct), direct.parent, roots, depth + 1))
                continue

            if exe in ("powershell", "pwsh", "powershell_ise"):
                interpreter_seen = True
                low = [a.lower() for a in args]
                if any(a in ("-encodedcommand", "-enc", "-e", "-ec") for a in low):
                    v.add("deny", "encoded PowerShell command cannot be verified", where)
                    continue
                if "-file" in low or "-f" in low:
                    i = low.index("-file") if "-file" in low else low.index("-f")
                    p = _resolve_path(args[i + 1], cwd) if i + 1 < len(args) else None
                    if p and p.is_file():
                        v.scanned_files.append(str(p))
                        v.merge(analyze_shell(read_source(p), p.parent, roots, depth + 1))
                    else:
                        v.add("deny", "PowerShell -File target not found; cannot verify", where)
                    continue
                rest = [a for a in args if not a.startswith("-") or a.lower() in ("-command", "-c")]
                rest = [a for a in rest if a.lower() not in ("-command", "-c")]
                if rest:
                    v.merge(analyze_shell(" ".join(rest), cwd, roots, depth + 1))
                elif _has_pipe_into(command, toks[0].split("/")[-1]) and not heredocs:
                    v.add("deny", f"commands piped into {exe} via stdin cannot be verified", where)
                continue
            if exe == "cmd":
                low = [a.lower() for a in args]
                for flag in ("/c", "/k", "/r"):
                    if flag in low:
                        v.merge(analyze_shell(" ".join(args[low.index(flag) + 1:]), cwd, roots, depth + 1))
                        break
                continue
            if exe in ("invoke-expression", "iex", "start-process", "saps", "start", "invoke-command", "icm"):
                interpreter_seen = True
                text = " ".join(args)
                if re.search(r"\b(irm|iwr|Invoke-RestMethod|Invoke-WebRequest|DownloadString|curl|wget)\b",
                             text, re.I):
                    v.add("deny", "executes code downloaded at run time; cannot be verified", where)
                else:
                    v.merge(analyze_shell(text.replace("-ArgumentList", " ").replace("-FilePath", " "),
                                          cwd, roots, depth + 1))
                continue

            if exe == "databricks":
                _check_databricks_cli(args, v, where)
                continue
            if exe in SQL_CLIENTS:
                if exe in ("spark-submit", "pyspark") and not DATABRICKS_MARKERS.search(command):
                    v.add("warn", f"{exe} invoked (no Databricks marker found)", where)
                else:
                    v.add("deny", f"{exe} executes SQL/Spark", where, "databrickssql.commandSubmit")
                continue
            if exe == "dbt":
                verb = next((a for a in args if not a.startswith("-")), "")
                if verb in DBT_EXEC_VERBS and _dbt_targets_databricks(cwd):
                    v.add("deny", f"`dbt {verb}` connects to and queries the Databricks warehouse",
                          where, "databrickssql.commandSubmit")
                continue
            if exe in HTTP_CLIENTS:
                text = " ".join(args)
                if DBX_HOST_HINT.search(text):
                    paths = [p.group(0) for p in API_PATH.finditer(text)]
                    write = re.search(r"(^|\s)(-X|--request)\s*(POST|PUT|PATCH|DELETE)|"
                                      r"(^|\s)(-d|--data\S*|-F|--form|--json|-T|--upload-file)\b|"
                                      r"--post-(data|file)", text, re.I)
                    if write or not paths or any(not UC_METADATA_PATH.match(p) for p in paths):
                        v.add("deny", f"{exe} request to Databricks is not a metadata GET", where,
                              "databrickssql.commandSubmit" if "sql/statements" in text else "")
                    else:
                        v.add("allow", f"{exe} GET on Unity Catalog metadata", where)
                continue
            if exe in SHELLS or exe in ("eval", "source", "."):
                interpreter_seen = True
                if exe in SHELLS and not [a for a in args if not a.startswith("-")] \
                        and _has_pipe_into(command, exe) and not heredocs:
                    v.add("deny", f"commands piped into {exe} via stdin cannot be verified", where)
                    continue
                if "-c" in args:
                    idx = args.index("-c")
                    if idx + 1 < len(args):
                        v.merge(analyze_shell(args[idx + 1], cwd, roots, depth + 1))
                elif exe == "eval":
                    v.merge(analyze_shell(" ".join(args), cwd, roots, depth + 1))
                else:
                    for a in args:
                        p = _resolve_path(a, cwd)
                        if p and p.is_file():
                            v.merge(analyze_shell(read_source(p), p.parent, roots, depth + 1))
                            v.scanned_files.append(str(p))
                            break
                continue
            if PY_INTERPRETERS.match(exe) or exe in ("jupyter", "papermill", "pytest", "py.test",
                                                       "nbconvert", "marimo", "streamlit"):
                interpreter_seen = True
                if exe in ("pytest", "py.test") or (len(args) >= 2 and args[0] == "-m"
                                                     and args[1] == "pytest"):
                    pytest_run = True
                    targets = [a for a in args if not a.startswith("-") and a not in ("-m", "pytest")]
                    found = [p for p in (_resolve_path(a.split("::")[0], cwd) for a in targets) if p]
                    if not found:
                        found = [p for p in (cwd / "tests", cwd / "test") if p.is_dir()]
                        found += sorted(cwd.glob("test_*.py"))
                    for p in found:
                        files_to_scan.extend(sorted(p.rglob("*.py"))[:MAX_SCAN_FILES] if p.is_dir() else [p])
                    continue
                if "-c" in args:
                    idx = args.index("-c")
                    if idx + 1 < len(args):
                        v.merge(analyze_code(args[idx + 1], where="python -c"))
                        files_to_scan.extend(_referenced_files(args[idx + 1], cwd))
                    continue
                script_args = [a for a in args if not a.startswith("-")]
                if (not script_args or script_args[0] == "-") and _has_pipe_into(command, exe) \
                        and not heredocs:
                    v.add("deny", f"code piped into {exe} via stdin cannot be verified", where)
                    continue
                if "-m" in args:
                    idx = args.index("-m")
                    if idx + 1 < len(args):
                        mod = args[idx + 1]
                        for r in _resolve_module(mod, cwd, roots):
                            files_to_scan.append(r)
                        main = cwd / Path(*mod.split(".")) / "__main__.py"
                        if main.is_file():
                            files_to_scan.append(main)
                    continue
                for a in args:
                    if a.startswith("-"):
                        continue
                    p = _resolve_path(a, cwd)
                    if p and p.is_file():
                        files_to_scan.append(p)
                    elif p and p.is_dir():
                        main = p / "__main__.py"
                        if main.is_file():
                            files_to_scan.append(main)
                continue
            if exe in ("make", "tox", "nox", "just", "task", "invoke"):
                for cfg in ("Makefile", "makefile", "tox.ini", "noxfile.py", "justfile",
                            "Taskfile.yml", "tasks.py"):
                    p = cwd / cfg
                    if p.is_file():
                        t = read_source(p)
                        v.scanned_files.append(str(p))
                        sv = analyze_shell(t, cwd, roots, depth + 1) if cfg not in (
                            "noxfile.py", "tasks.py") else analyze_code(t, str(p))
                        for fd in sv.findings:
                            if fd["level"] == "deny":
                                v.add("deny", f"{exe} target may run: {fd['reason']}", str(p), fd["audit"])
                continue

    for owner, body in heredocs:
        owner_toks = _unwrap((_tokenize(owner) or [[]])[0])
        exe = _exe_name(owner_toks[0]) if owner_toks else ""
        if PY_INTERPRETERS.match(exe):
            v.merge(analyze_code(body, where="heredoc → python"))
        elif exe in SHELLS:
            v.merge(analyze_shell(body, cwd, roots, depth + 1))
        # heredocs written to files (cat > x <<EOF) are code generation: allowed

    if interpreter_seen and not heredocs:
        # Inline code (e.g. python - <<<'...' or quoted code) still gets a code scan.
        inline = analyze_code(command, where="command text")
        for fd in inline.findings:
            if fd["level"] == "deny":
                v.add(fd["level"], fd["reason"], fd["where"], fd["audit"])

    if files_to_scan:
        v.merge(analyze_files(files_to_scan, roots, soften_mocked=pytest_run))
    return v


# --------------------------------------------------------------------------------------
# MCP analysis
# --------------------------------------------------------------------------------------
def analyze_mcp(tool_name: str, tool_input, server_hint: str = "") -> Verdict:
    v = Verdict()
    blob = tool_input if isinstance(tool_input, str) else json.dumps(tool_input or {}, sort_keys=True)
    name = tool_name or ""
    is_dbx = bool(MCP_DATABRICKS_HINT.search(name) or MCP_DATABRICKS_HINT.search(server_hint)
                  or DATABRICKS_MARKERS.search(blob))
    where = f"mcp:{name}"
    short = name.split("__")[-1]
    if CTX.get("mode") == "cowork" and STRICT_QUERY_TOOL.search(short) and not (
            MCP_ALLOW_NAME.search(short) and not re.search(r"sql|query|statement|execute|sample|preview|"
                                                           r"rows|genie", short, re.I)):
        v.add("deny", f"connector tool '{short}' runs queries; in Cowork, data-querying tools are blocked "
                      "(Databricks or not, since connector names can hide the service)", where,
              "databrickssql.commandSubmit / aibiGenie.executeQuery")
        return v
    if not is_dbx:
        return v
    if SQL_IN_ARGS.search(blob):
        v.add("deny", "MCP tool arguments contain a SQL statement", where, "databrickssql.commandSubmit")
    if MCP_ALLOW_NAME.search(short) and not re.search(
            r"sql|query|statement|execute|sample|preview|rows|data|genie|read", short, re.I):
        if v.level != "deny":
            v.add("allow", f"Databricks MCP metadata tool {short}", where)
        return v
    v.add("deny", f"Databricks MCP tool '{short}' is not an allowlisted metadata tool", where,
          "aibiGenie/databrickssql (query execution)" if MCP_DENY_NAME.search(short) else "")
    return v


# --------------------------------------------------------------------------------------
# Unified tool-call classifier
# --------------------------------------------------------------------------------------
def classify_tool_call(tool_name: str, tool_input, cwd: Path, server_hint: str = "") -> Verdict:
    tn = tool_name or ""
    ti = tool_input if tool_input is not None else {}
    if isinstance(ti, str):
        try:
            ti = json.loads(ti)
        except ValueError:
            pass
    req = CTX["required_profile"]
    CTX["env_profile_ok"] = bool(req) and os.environ.get("DATABRICKS_CONFIG_PROFILE") == req

    # File tools: credentials may not be read; guard files may not be changed.
    if isinstance(ti, dict) and tn in ("Read", "Write", "Edit", "MultiEdit", "NotebookEdit", "Grep",
                                       "Glob", "LS", "read_file", "edit_file", "write",
                                       "beforeReadFile", "search_replace", "delete_file"):
        target = " ".join(str(ti.get(k, "")) for k in ("file_path", "path", "notebook_path",
                                                       "target_file", "pattern", "glob"))
        v = Verdict()
        if CRED_FILES.search(target):
            v.add("deny", f"{tn} on Databricks credential file", f"{tn}:{target[:200]}")
        if tn not in ("Read", "Grep", "Glob", "LS", "read_file", "beforeReadFile") and \
                PROTECTED.search(target):
            v.add("deny", f"{tn} would modify the guard, its logs, or hook config", f"{tn}:{target[:200]}")
        return v
    if tn in ("Bash", "Shell", "run_terminal_cmd", "terminal", "shell", "BashOutput") or (
            isinstance(ti, dict) and "command" in ti and not tn.startswith("mcp")):
        cmd = ti.get("command", "") if isinstance(ti, dict) else str(ti)
        return analyze_shell(str(cmd), cwd)
    if tn.startswith("mcp__") or tn.startswith("mcp_") or server_hint:
        return analyze_mcp(tn, ti, server_hint)
    if tn in ("NotebookEdit", "Write", "Edit", "MultiEdit", "Read", "Glob", "Grep", "LS",
              "edit_file", "write", "read_file", "codebase_search", "grep_search"):
        return Verdict()   # code generation / local reads are allowed
    # Unknown tool: inspect any obvious command/code payload.
    v = Verdict()
    if isinstance(ti, dict):
        for k in ("command", "cmd", "code", "script", "sql", "query", "statement"):
            if k in ti and isinstance(ti[k], str):
                if k in ("sql", "query", "statement") and SQL_IN_ARGS.search(ti[k]) and \
                        DATABRICKS_MARKERS.search(json.dumps(ti) + tn):
                    v.add("deny", f"tool {tn} carries SQL for Databricks", f"tool:{tn}",
                          "databrickssql.commandSubmit")
                elif k in ("command", "cmd"):
                    v.merge(analyze_shell(ti[k], cwd))
                else:
                    v.merge(analyze_code(ti[k], where=f"tool:{tn}"))
    return v


# --------------------------------------------------------------------------------------
# Logging
# --------------------------------------------------------------------------------------
def _project_dir(payload: dict) -> Path:
    for key in ("CLAUDE_PROJECT_DIR", "CURSOR_PROJECT_DIR", "DBX_GUARD_PROJECT_DIR"):
        if os.environ.get(key):
            return Path(os.environ[key])
    roots = payload.get("workspace_roots") or []
    if roots:
        return Path(roots[0])
    if payload.get("cwd"):
        return Path(payload["cwd"])
    return Path.cwd()


def log_decision(project: Path, record: dict) -> None:
    if os.environ.get("DBX_GUARD_NO_LOG"):
        return
    try:
        default = (Path(tempfile.gettempdir()) / "databricks-guard") if CTX.get("mode") == "cowork" \
            else project / LOG_DIR_NAME          # don't litter the user's folder from the Cowork sandbox
        d = Path(os.environ.get("DBX_GUARD_LOG_DIR", default))
        d.mkdir(parents=True, exist_ok=True)
        with open(d / LOG_FILE_NAME, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, sort_keys=True) + "\n")
    except OSError:
        pass


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")


# --------------------------------------------------------------------------------------
# Hook entry points
# --------------------------------------------------------------------------------------
def _block_message(v: Verdict) -> str:
    if CTX.get("mode") == "cowork":
        return (f"BLOCKED by {RULE_NAME}.\n{v.summary()}\n"
                "Only Databricks metadata (catalog, schema, table and column names) may be read. Write the "
                "query or code into a file in the user's folder for them to review and run instead. Do "
                "not try another route to the same data.")
    return (f"BLOCKED by {RULE_NAME}.\n{v.summary()}\n"
            "Only Unity Catalog metadata calls (catalogs/schemas/tables list|get) may be executed. "
            "Write the query or code to a file for a human to review and run instead. Do not try "
            "another route to the same data.")


def run_hook(agent: str, stdin_text: str) -> int:
    try:
        payload = json.loads(stdin_text or "{}")
    except ValueError:
        payload = {}
    project = _project_dir(payload)
    cwd = Path(payload.get("cwd") or project)
    event = payload.get("hook_event_name", "")
    try:
        if agent == "cursor":
            if event == "beforeShellExecution" or ("command" in payload and "tool_name" not in payload):
                tool_name, tool_input = "Shell", {"command": payload.get("command", "")}
                server = ""
            elif event == "beforeReadFile":
                tool_name, tool_input = "beforeReadFile", {"file_path": payload.get("file_path", "")}
                server = ""
            elif event == "beforeMCPExecution":
                tool_name = payload.get("tool_name", "")
                tool_input = payload.get("tool_input", payload.get("arguments", {}))
                server = " ".join(str(payload.get(k, "")) for k in ("url", "command", "server_name",
                                                                     "server"))
                tool_name = tool_name if tool_name.startswith("mcp") else "mcp__" + tool_name
            else:  # preToolUse or anything else
                tool_name = payload.get("tool_name", "")
                tool_input = payload.get("tool_input", {})
                server = ""
        else:
            tool_name = payload.get("tool_name", "")
            tool_input = payload.get("tool_input", {})
            server = ""
        v = classify_tool_call(tool_name, tool_input, cwd, server)
    except Exception as exc:  # fail closed
        if os.environ.get("DBX_GUARD_FAIL_OPEN") == "1":
            return 0
        v = Verdict()
        v.add("deny", f"guard internal error ({type(exc).__name__}: {exc}); failing closed", "guard")
        tool_name, tool_input = payload.get("tool_name", "?"), payload.get("tool_input", {})

    rec = {
        "ts": _now(), "agent": agent, "event": event or "PreToolUse", "tool": tool_name,
        "input": (json.dumps(tool_input, sort_keys=True) if not isinstance(tool_input, str)
                  else tool_input)[:4000],
        "verdict": v.level, "findings": [f for f in v.findings if f["level"] != "allow"],
        "session": payload.get("session_id") or payload.get("conversation_id") or "",
        "guard_version": VERSION,
    }
    rec["input_sha256"] = hashlib.sha256(rec["input"].encode()).hexdigest()
    rec["databricks"] = bool(DATABRICKS_MARKERS.search(rec["input"]))
    rec["required_profile"] = CTX["required_profile"] or ""
    log_decision(project, rec)

    if agent == "cursor":
        if v.level == "deny":
            msg = _block_message(v)
            print(json.dumps({"continue": True, "permission": "deny",
                              "user_message": f"Blocked by {RULE_NAME}: {v.summary()}",
                              "agent_message": msg,
                              "userMessage": f"Blocked by {RULE_NAME}", "agentMessage": msg}))
            return 2
        print(json.dumps({"continue": True, "permission": "allow"}))
        return 0

    # Claude Code: exit 2 + stderr blocks the call and feeds the reason to Claude.
    if v.level == "deny":
        sys.stderr.write(_block_message(v) + "\n")
        return 2
    return 0


# --------------------------------------------------------------------------------------
# scan: after-the-fact transcript check
# --------------------------------------------------------------------------------------
def iter_tool_calls(path: Path):
    """Yield (location, tool_name, tool_input, cwd) from Claude Code transcripts or generic JSONL."""
    files = sorted(path.rglob("*.jsonl")) if path.is_dir() else [path]
    for f in files:
        with open(f, encoding="utf-8", errors="replace") as fh:
            for ln, line in enumerate(fh, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except ValueError:
                    continue
                cwd = obj.get("cwd", "")
                msg = obj.get("message") if isinstance(obj.get("message"), dict) else None
                if msg and isinstance(msg.get("content"), list):
                    for item in msg["content"]:
                        if isinstance(item, dict) and item.get("type") == "tool_use":
                            yield f"{f}:{ln}", item.get("name", ""), item.get("input", {}), cwd
                elif "tool_name" in obj:
                    yield f"{f}:{ln}", obj["tool_name"], obj.get("tool_input", {}), cwd
                elif "command" in obj and isinstance(obj["command"], str):
                    yield f"{f}:{ln}", "Shell", {"command": obj["command"]}, cwd


def cmd_scan(args) -> int:
    total = viol = warn = 0
    out = []
    for target in args.paths:
        p = Path(os.path.expanduser(target))
        if not p.exists():
            print(f"not found: {p}", file=sys.stderr)
            return 3
        for loc, tn, ti, cwd in iter_tool_calls(p):
            total += 1
            v = classify_tool_call(tn, ti, Path(args.cwd or cwd or "."))
            if v.level == "deny":
                viol += 1
            elif v.level == "warn":
                warn += 1
            if v.level != "allow":
                out.append({"location": loc, "tool": tn, "input": ti, **v.to_dict()})
    if args.json:
        print(json.dumps({"tool_calls": total, "violations": viol, "warnings": warn,
                          "items": out}, indent=2, default=str))
    else:
        print(f"Scanned {total} tool calls: {viol} violation(s), {warn} warning(s).")
        for item in out:
            snippet = json.dumps(item["input"], default=str)[:160]
            print(f"\n[{item['verdict'].upper()}] {item['location']}  {item['tool']}  {snippet}")
            for fd in item["findings"]:
                if fd["level"] != "allow":
                    print(f"   - {fd['reason']}" + (f"  (audit: {fd['audit']})" if fd["audit"] else ""))
    return 1 if viol or (args.strict and warn) else 0


# --------------------------------------------------------------------------------------
# report: summarize decision log
# --------------------------------------------------------------------------------------
def cmd_report(args) -> int:
    path = Path(args.log) if args.log else Path.cwd() / LOG_DIR_NAME / LOG_FILE_NAME
    if not path.is_file():
        print(f"no decision log at {path}", file=sys.stderr)
        return 3
    since = None
    if args.since:
        since = _dt.datetime.fromisoformat(args.since)
        if since.tzinfo is None:
            since = since.replace(tzinfo=_dt.timezone.utc)
    counts = {"allow": 0, "warn": 0, "deny": 0}
    by_agent: Dict[str, Dict[str, int]] = {}
    denies = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if since and _dt.datetime.fromisoformat(r["ts"]) < since:
                continue
            counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
            a = by_agent.setdefault(r.get("agent", "?"), {"allow": 0, "warn": 0, "deny": 0})
            a[r["verdict"]] = a.get(r["verdict"], 0) + 1
            if r["verdict"] in ("deny", "warn"):
                denies.append(r)
    if args.json:
        print(json.dumps({"counts": counts, "by_agent": by_agent, "events": denies}, indent=2))
    else:
        print(f"Decision log: {path}")
        print(f"  allowed={counts['allow']}  warned={counts['warn']}  blocked={counts['deny']}")
        for ag, c in sorted(by_agent.items()):
            print(f"  {ag:8s} allowed={c['allow']} warned={c['warn']} blocked={c['deny']}")
        for r in denies:
            print(f"\n[{r['verdict'].upper()}] {r['ts']} {r['agent']} {r['tool']}: {r['input'][:160]}")
            for fd in r.get("findings", []):
                print(f"   - {fd['reason']}" + (f"  (audit: {fd['audit']})" if fd.get("audit") else ""))
    fail_on = args.fail_on
    if fail_on == "never":
        return 0
    if fail_on == "warn" and (counts["warn"] or counts["deny"]):
        return 1
    return 1 if counts["deny"] else 0


# --------------------------------------------------------------------------------------
# audit: verify against Databricks audit logs / query history exports
# --------------------------------------------------------------------------------------
def _load_rows(path: Path) -> List[dict]:
    text = path.read_text(encoding="utf-8", errors="replace")
    if path.suffix.lower() == ".csv":
        return list(csv.DictReader(text.splitlines()))
    text = text.strip()
    if text.startswith("["):
        return json.loads(text)
    rows = []
    for line in text.splitlines():
        line = line.strip()
        if line:
            try:
                rows.append(json.loads(line))
            except ValueError:
                pass
    return rows


def _maybe_json(x):
    if isinstance(x, str) and x[:1] in "{[":
        try:
            return json.loads(x)
        except ValueError:
            return x
    return x


def _principal_of(row: dict) -> str:
    for k in ("principal", "email", "user_email", "executed_by", "executed_as",
              "user_identity.email", "user_name"):
        if row.get(k):
            return str(row[k])
    ui = _maybe_json(row.get("user_identity") or row.get("userIdentity") or {})
    if isinstance(ui, dict):
        return str(ui.get("email") or ui.get("subject_name") or "")
    return str(ui or "")


def cmd_audit(args) -> int:
    principals = {p.lower() for p in (args.principal or [])}
    extra_allow = set()
    for s in args.allow_extra or []:
        if "." in s:
            svc, act = s.split(".", 1)
            extra_allow.add((svc, act))
    rows = []
    for f in args.files:
        rows.extend(_load_rows(Path(f)))
    total = len(rows)
    considered = 0
    violations, unexpected, ok = [], [], 0
    for r in rows:
        who = _principal_of(r).lower()
        if principals and who not in principals:
            continue
        considered += 1
        # system.query.history export: any statement by the agent principal is a violation.
        if "statement_text" in r or "statement_id" in r and "service_name" not in r:
            violations.append({"row": r, "why": "SQL statement executed by agent principal",
                               "event": "system.query.history"})
            continue
        svc = str(r.get("service_name") or r.get("serviceName") or "")
        act = str(r.get("action_name") or r.get("actionName") or "")
        key = (svc, act)
        params = _maybe_json(r.get("request_params") or r.get("requestParams") or {})
        if key in AUDIT_DENIED:
            violations.append({"row": r, "why": AUDIT_DENIED[key], "event": f"{svc}.{act}"})
        elif svc == "unityCatalog" and isinstance(params, dict) and \
                re.search(r"READ|WRITE", str(params.get("operation", ""))):
            violations.append({"row": r, "why": f"storage credential operation {params.get('operation')}",
                               "event": f"{svc}.{act}"})
        elif key in AUDIT_ALLOWED or key in extra_allow:
            ok += 1
        else:
            unexpected.append({"row": r, "why": "event not on the metadata allowlist (default deny)",
                               "event": f"{svc}.{act}"})
    fail = len(violations) + (len(unexpected) if args.strict else 0)
    if args.json:
        print(json.dumps({"rows": total, "agent_rows": considered, "allowed": ok,
                          "violations": violations, "unexpected": unexpected}, indent=2, default=str))
    else:
        scope = ", ".join(sorted(principals)) or "ALL principals"
        print(f"Audit rows: {total}; rows for {scope}: {considered}")
        print(f"  allowed metadata events: {ok}")
        print(f"  VIOLATIONS: {len(violations)}")
        print(f"  unexpected (not allowlisted): {len(unexpected)}"
              + ("  [counted as failures: --strict]" if args.strict else ""))
        for item in violations + (unexpected if args.verbose or args.strict else []):
            r = item["row"]
            ts = r.get("event_time") or r.get("start_time") or r.get("timestamp") or ""
            print(f"\n  {item['event']}  {ts}  {_principal_of(r)}\n    -> {item['why']}")
            st = r.get("statement_text")
            if st:
                print(f"    statement: {str(st)[:200]}")
        if not principals:
            print("\nNote: no --principal given. Pass the agent's service principal / user so "
                  "human activity is not counted.")
    return 1 if fail else 0


AUDIT_SQL = """-- Run this as a HUMAN or in CI with your own credentials. The agent must never run it.
-- Export the results to CSV/JSON, then:  python databricks_guard.py audit <file> --principal <id>
-- Note: databrickssql.commandSubmit/commandFinish and notebook.runCommand appear only when
--       verbose audit logging is enabled for the workspace.

-- 1) Every audit event caused by the agent principal(s)
SELECT event_time, workspace_id, service_name, action_name,
       user_identity.email AS principal,
       request_params, response.status_code AS status_code, source_ip_address, user_agent
FROM system.access.audit
WHERE event_date >= current_date() - INTERVAL {days} DAYS
  AND user_identity.email IN ({principals})
ORDER BY event_time;

-- 2) Every SQL statement run by the agent principal(s). Any row here is a violation.
SELECT start_time, workspace_id, executed_by, statement_id, statement_type,
       LEFT(statement_text, 500) AS statement_text, execution_status, client_application
FROM system.query.history
WHERE start_time >= current_date() - INTERVAL {days} DAYS
  AND executed_by IN ({principals})
ORDER BY start_time;
"""


def cmd_audit_sql(args) -> int:
    ps = ", ".join("'" + p.replace("'", "''") + "'" for p in (args.principal or ["<agent-principal>"]))
    print(AUDIT_SQL.format(days=int(args.days), principals=ps))
    return 0


# --------------------------------------------------------------------------------------
# verify: fully local compliance check (no workspace audit-log access needed)
# --------------------------------------------------------------------------------------
PROXY_LOG_NAME = "proxy.jsonl"
USER_GUARD_DIR = Path(os.environ.get("DBX_GUARD_HOME") or Path.home()) / LOG_DIR_NAME


def _read_jsonl(path: Path) -> List[dict]:
    out = []
    if path.is_file():
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                try:
                    out.append(json.loads(line))
                except ValueError:
                    pass
    return out


def _proxy_allowlist():
    """Use the proxy's own allowlist so verify and proxy can't drift apart."""
    here = Path(__file__).resolve().parent
    sys.path.insert(0, str(here))
    try:
        import dbx_metadata_proxy as px  # type: ignore
        return px.is_allowed
    except Exception:
        return lambda m, p: m == "GET" and bool(UC_METADATA_PATH.match(p) or
                                               p in ("/api/2.0/preview/scim/v2/Me",
                                                     "/.well-known/databricks-config"))
    finally:
        sys.path.pop(0)


def cmd_verify(args) -> int:
    d = Path(args.log_dir)
    since = None
    if args.since:
        since = _dt.datetime.fromisoformat(args.since)
        if since.tzinfo is None:
            since = since.replace(tzinfo=_dt.timezone.utc)

    def in_window(r):
        if not since:
            return True
        try:
            return _dt.datetime.fromisoformat(r["ts"]) >= since
        except (KeyError, ValueError):
            return True

    if args.proxy_log:
        proxy_path = Path(args.proxy_log)
    elif (d / PROXY_LOG_NAME).is_file():
        proxy_path = d / PROXY_LOG_NAME
    else:                                   # login service writes to ~/.databricks-guard/proxy.jsonl
        proxy_path = USER_GUARD_DIR / PROXY_LOG_NAME
    proxy = [r for r in _read_jsonl(proxy_path) if in_window(r)]
    hooks = [r for r in _read_jsonl(d / LOG_FILE_NAME) if in_window(r)]
    allowed = _proxy_allowlist()

    violations: List[str] = []
    warnings: List[str] = []

    fwd = [r for r in proxy if r.get("decision") == "forwarded"]
    blk = [r for r in proxy if r.get("decision") == "blocked"]
    err = [r for r in proxy if r.get("decision") == "error"]
    for r in blk:
        violations.append(f"proxy BLOCKED {r.get('method')} {r.get('path')} at {r.get('ts')} "
                          f"(ua: {r.get('user_agent', '')[:60]})")
    for r in fwd:
        if not allowed(r.get("method", ""), r.get("path", "")):
            violations.append(f"proxy FORWARDED a non-allowlisted request {r.get('method')} "
                              f"{r.get('path')} at {r.get('ts')} (proxy modified?)")
    hook_deny = [r for r in hooks if r.get("verdict") == "deny"]
    hook_warn = [r for r in hooks if r.get("verdict") == "warn"]
    for r in hook_deny:
        why = "; ".join(f.get("reason", "") for f in r.get("findings", []))[:200]
        violations.append(f"hook BLOCKED {r.get('agent')} {r.get('tool')} at {r.get('ts')}: {why}")
    for r in hook_warn:
        warnings.append(f"hook WARN {r.get('agent')} {r.get('tool')} at {r.get('ts')}")

    dbx_allowed = [r for r in hooks if r.get("verdict") == "allow" and r.get("databricks")]
    if not proxy_path.is_file():
        warnings.append(f"no proxy log at {proxy_path}: the metadata proxy has not been used")
    elif dbx_allowed and not proxy:
        warnings.append(f"{len(dbx_allowed)} Databricks command(s) ran but the proxy saw no traffic "
                        "in this window: the agent may be using another profile")
    if not (d / LOG_FILE_NAME).is_file():
        warnings.append(f"no hook decision log at {d / LOG_FILE_NAME}: hooks may not be installed")
    unprofiled = [r for r in hooks if not r.get("required_profile")]
    if hooks and len(unprofiled) == len(hooks):
        warnings.append("hooks are running without --require-profile; proxy use is not enforced")

    transcript_viol = 0
    for t in args.transcripts or []:
        p = Path(os.path.expanduser(t))
        if not p.exists():
            warnings.append(f"transcript path not found: {p}")
            continue
        for loc, tn, ti, cwd in iter_tool_calls(p):
            v = classify_tool_call(tn, ti, Path(cwd or "."))
            if v.level == "deny":
                transcript_viol += 1
                violations.append(f"transcript {loc}: {tn} -> {v.summary().splitlines()[0]}")

    result = {
        "window_since": args.since or "all",
        "proxy": {"forwarded": len(fwd), "blocked": len(blk), "errors": len(err)},
        "hooks": {"allowed": sum(r.get('verdict') == 'allow' for r in hooks),
                  "warned": len(hook_warn), "blocked": len(hook_deny)},
        "transcript_violations": transcript_viol,
        "violations": violations, "warnings": warnings,
        "compliant": not violations and not (args.strict and warnings),
    }
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print("Local Databricks compliance check")
        print(f"  window: {result['window_since']}")
        print(f"  proxy log: {proxy_path}")
        print(f"  proxy  : forwarded={len(fwd)} blocked={len(blk)} errors={len(err)}")
        print(f"  hooks  : allowed={result['hooks']['allowed']} warned={len(hook_warn)} "
              f"blocked={len(hook_deny)}")
        if args.transcripts:
            print(f"  transcripts: {transcript_viol} violation(s)")
        for s in violations:
            print(f"  VIOLATION  {s}")
        for s in warnings:
            print(f"  warning    {s}")
        print("RESULT: " + ("COMPLIANT" if result["compliant"] else "NOT COMPLIANT"))
    return 0 if result["compliant"] else 1


# --------------------------------------------------------------------------------------
# check
# --------------------------------------------------------------------------------------
def cmd_check(args) -> int:
    cwd = Path(args.cwd or ".").resolve()
    if args.file:
        v = analyze_files([Path(args.file)], [cwd])
    elif args.mcp:
        v = analyze_mcp(args.mcp, args.command or "{}")
    else:
        v = analyze_shell(args.command or "", cwd)
    if args.json:
        print(json.dumps(v.to_dict(), indent=2))
    else:
        print(f"{v.level.upper()}: {v.summary()}")
    return 1 if v.level == "deny" else 0


def _utf8_console() -> None:
    """Windows consoles default to cp1252; never let printing a message crash a guard."""
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except Exception:
            pass


def main(argv: Optional[List[str]] = None) -> int:
    _utf8_console()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", action="version", version=VERSION)
    sub = ap.add_subparsers(dest="cmd", required=True)

    h = sub.add_parser("hook", help="run as a pre-execution hook (reads JSON on stdin)")
    h.add_argument("--agent", choices=["claude", "cursor"], required=True)
    h.add_argument("--require-profile", metavar="NAME",
                   help="agent may reach Databricks only via this profile (the local metadata proxy)")
    h.add_argument("--mode", choices=["local", "cowork"], default=None,
                   help="cowork: running inside the Claude Cowork sandbox (plugin); stricter connector rules")

    c = sub.add_parser("check", help="classify a command, file, or MCP call")
    c.add_argument("command", nargs="?", help="shell command (or MCP args JSON with --mcp)")
    c.add_argument("--file", help="classify a script/notebook as if it were executed")
    c.add_argument("--mcp", metavar="TOOL_NAME", help="classify an MCP tool call")
    c.add_argument("--cwd")
    c.add_argument("--require-profile", metavar="NAME")
    c.add_argument("--json", action="store_true")

    vf = sub.add_parser("verify", help="LOCAL compliance check: proxy log + hook log (+ transcripts)")
    vf.add_argument("--log-dir", default=LOG_DIR_NAME)
    vf.add_argument("--proxy-log", help="proxy log (default: ./.databricks-guard/proxy.jsonl, "
                                        "else ~/.databricks-guard/proxy.jsonl)")
    vf.add_argument("--since", help="ISO timestamp")
    vf.add_argument("--transcripts", nargs="*", help="Claude Code transcript files/dirs to re-check")
    vf.add_argument("--strict", action="store_true", help="warnings also fail")
    vf.add_argument("--json", action="store_true")

    s = sub.add_parser("scan", help="scan agent transcripts / JSONL tool-call logs")
    s.add_argument("paths", nargs="+")
    s.add_argument("--cwd", help="resolve script paths relative to this directory")
    s.add_argument("--strict", action="store_true", help="warnings also fail")
    s.add_argument("--json", action="store_true")

    r = sub.add_parser("report", help="summarize the hook decision log")
    r.add_argument("--log")
    r.add_argument("--since", help="ISO timestamp")
    r.add_argument("--fail-on", choices=["deny", "warn", "never"], default="deny")
    r.add_argument("--json", action="store_true")

    a = sub.add_parser("audit", help="check exported system.access.audit / system.query.history rows")
    a.add_argument("files", nargs="+")
    a.add_argument("--principal", action="append", help="agent principal (email or SP application id)")
    a.add_argument("--allow-extra", action="append", metavar="service.action")
    a.add_argument("--strict", action="store_true", help="non-allowlisted events also fail")
    a.add_argument("--verbose", action="store_true")
    a.add_argument("--json", action="store_true")

    q = sub.add_parser("audit-sql", help="print the export SQL for a human to run")
    q.add_argument("--principal", action="append")
    q.add_argument("--days", default=7)

    args = ap.parse_args(argv)
    if getattr(args, "require_profile", None):
        CTX["required_profile"] = args.require_profile
    if getattr(args, "mode", None):
        CTX["mode"] = args.mode
    if args.cmd == "hook":
        return run_hook(args.agent, sys.stdin.read())
    return {"check": cmd_check, "scan": cmd_scan, "report": cmd_report,
            "audit": cmd_audit, "audit-sql": cmd_audit_sql, "verify": cmd_verify}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
