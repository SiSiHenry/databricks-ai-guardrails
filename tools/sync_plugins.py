#!/usr/bin/env python3
"""
Rebuild the plugin copies from the main files, so there is one source of truth.

    python3 tools/sync_plugins.py           # update the plugin folders
    python3 tools/sync_plugins.py --check   # exit 1 if anything is out of date (used by the tests)

What it does:
  1. Writes the setup-kit fingerprint (TRUSTED_KIT_SHA256) into guards/databricks_guard.py.
  2. Copies the guard into both plugins (Claude: plugins/…, Cursor: cursor-plugins/…).
  3. Builds the Cursor plugin's setup kit (installer + guard + gateway + service helper + rules).
  4. Builds the Cursor plugin's always-on rule from cursor/rules/databricks-metadata-only.mdc.
"""
import hashlib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GUARD = ROOT / "guards" / "databricks_guard.py"
CLAUDE_PLUGIN = ROOT / "plugins" / "databricks-ai-guardrails"
CURSOR_PLUGIN = ROOT / "cursor-plugins" / "databricks-ai-guardrails"
KIT = CURSOR_PLUGIN / "setup"
KIT_FILES = ("install.py", "guards/dbx_metadata_proxy.py", "guards/proxy_service.py")

KIT_COPY = {
    "install.py": "install.py",
    "CLAUDE.md": "CLAUDE.md",
    "claude/settings.json": "claude/settings.json",
    "cursor/rules/databricks-metadata-only.mdc": "cursor/rules/databricks-metadata-only.mdc",
    "guards/dbx_metadata_proxy.py": "guards/dbx_metadata_proxy.py",
    "guards/proxy_service.py": "guards/proxy_service.py",
    "guards/README.md": "guards/README.md",
}

CURSOR_RULE_EXTRA = """
---

## 8. Setup check (Cursor plugin)

This rule comes from the Databricks AI Guardrails plugin. Full protection needs a one-time setup on
each computer. If `databricks auth profiles` does not list a profile named `agent`, or the `agent`
profile can't connect, tell the user in plain words:

> "To finish setting up the Databricks guardrails on this computer, type **/setup-databricks-guardrails**
> in this chat."

Until then, still follow every rule above: read metadata only, write code for the user, and never
run queries.
"""


def kit_sha256(base: Path) -> str:
    """Must match databricks_guard.kit_sha256()."""
    h = hashlib.sha256()
    for rel in KIT_FILES:
        h.update(rel.encode() + b"\0" + (base / rel).read_bytes().replace(b"\r\n", b"\n") + b"\0")
    return h.hexdigest()


def planned() -> dict:
    """Return {path: bytes} for every generated file."""
    out = {}
    digest = kit_sha256(ROOT)
    guard = GUARD.read_text(encoding="utf-8")
    guard = re.sub(r'^TRUSTED_KIT_SHA256 = ".*"$', f'TRUSTED_KIT_SHA256 = "{digest}"', guard, count=1,
                   flags=re.M)
    gb = guard.encode("utf-8")
    out[GUARD] = gb
    out[CLAUDE_PLUGIN / "scripts" / "databricks_guard.py"] = gb
    out[CURSOR_PLUGIN / "scripts" / "databricks_guard.py"] = gb
    out[KIT / "guards" / "databricks_guard.py"] = gb
    for src, dst in KIT_COPY.items():
        out[KIT / dst] = (ROOT / src).read_bytes()
    rule = (ROOT / "cursor" / "rules" / "databricks-metadata-only.mdc").read_text(encoding="utf-8")
    out[CURSOR_PLUGIN / "rules" / "databricks-metadata-only.mdc"] = (rule.rstrip() + "\n" + CURSOR_RULE_EXTRA).encode()
    return out


def main() -> int:
    check = "--check" in sys.argv
    stale = []
    for path, data in planned().items():
        if not path.is_file() or path.read_bytes() != data:
            stale.append(path.relative_to(ROOT))
            if not check:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
    if check:
        if stale:
            print("Out of date (run: python3 tools/sync_plugins.py):\n  " + "\n  ".join(map(str, stale)))
            return 1
        print("plugins are in sync")
        return 0
    print(("updated:\n  " + "\n  ".join(map(str, stale))) if stale else "already in sync")
    return 0


if __name__ == "__main__":
    sys.exit(main())
