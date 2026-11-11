# Databricks AI Guardrails (Cursor plugin)

Lets Cursor see your Databricks **table and column names** and write code for you, but blocks it
from **running queries or reading data**.

Before you start, you need the Databricks command-line tool installed and an active Databricks
sign-in (OAuth) on this computer.

1. In Cursor, open **Settings** (gear icon, top right) or **Customize** in the sidebar, then
   **Plugins** (in some versions **Plugins & MCPs**). This plugin isn't in the official Cursor
   Marketplace, so don't search for it. Click **Add / +**, choose **From GitHub Repository**, paste
   `https://github.com/SiSiHenry/databricks-ai-guardrails`, then **Install** (or **Add to Cursor**)
   **Databricks AI Guardrails**, choosing **For myself (all projects)**.
2. In the Agent chat, type **`/setup-databricks-guardrails`**. Cursor finishes the setup (it asks you
   to click **Run**).
3. Quit and reopen Cursor.

What's inside:
- an always-on rule;
- hooks that check every command, tool call and file read before it runs;
- the setup command, with a bundled installer that adds the local metadata-only gateway and the
  start-at-login service. Full protection on Windows starts after step 2.

Full instructions: https://github.com/SiSiHenry/databricks-ai-guardrails
