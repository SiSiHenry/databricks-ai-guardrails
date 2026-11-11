---
name: setup-databricks-guardrails
description: Finish setting up Databricks AI Guardrails on this computer (one time). Installs the background service that keeps Databricks access metadata-only and adds the rule to this project. Assumes the user is already signed in to Databricks.
---

# Set up Databricks AI Guardrails on this computer

The user is probably not technical. Before each step, say in one plain sentence what you are about to
do. When Cursor asks to run a command, tell the user to click **Run**. Never show tokens or
passwords. Don't edit any settings file by hand.

## 1. Find Python

- **Mac:** run `python3 --version`.
- **Windows:** run `py --version`, then `python --version` if that fails.

It must print Python 3.9 or higher. Use the command that worked as **PY** below.

If none works, tell the user:
> "This needs Python. Please install it from https://www.python.org/downloads/ (on Windows, tick
> **Add python.exe to PATH**), then quit and reopen Cursor and type /setup-databricks-guardrails again."

Then stop.

## 2. Find this plugin's installer

- **Mac:** `find ~/.cursor/plugins -path '*databricks-ai-guardrails*/setup/install.py' 2>/dev/null`
- **Windows:** `Get-ChildItem "$HOME\.cursor\plugins" -Recurse -Filter install.py -ErrorAction SilentlyContinue | Where-Object { $_.FullName -like '*databricks-ai-guardrails*setup*' } | Select-Object -ExpandProperty FullName`

Use the first path printed as **INSTALLER**. If nothing is found, follow
https://raw.githubusercontent.com/SiSiHenry/databricks-ai-guardrails/main/AGENT_INSTALL.md instead
and stop here.

## 3. Run the installer for this project

Run exactly this, from the open project folder, with nothing else on the line:

- **Mac:** `PY "INSTALLER" "$PWD"`
- **Windows:** `PY "INSTALLER" "$PWD"`

The user is already signed in to Databricks (OAuth). Don't run any `databricks auth` command.

How to read the result:
- **The user's Databricks profile isn't called DEFAULT.** Add `--upstream-profile <NAME>`. If you don't
  know the name, run `databricks auth profiles` and ask the user which one is theirs.
- **`Not signed in to Databricks`.** Finish the setup anyway, then tell the user their sign-in seems to
  have expired and that they should sign in again themselves. The guardrails pick it up automatically.
- **Success:** the last line must be `RESULT: ALL CHECKS PASSED`. If it says `PROBLEMS FOUND`, tell the
  user the lines starting with `FAIL`, in plain words.

The guard allows this command **once**, for the first setup. After that, it blocks the AI from
re-running or changing the setup; the user makes changes themselves (README, "Changing settings").

## 4. Finish

Tell the user, in friendly words:
> "All set! Please quit Cursor completely (Mac: Cmd + Q, Windows: File → Exit) and open it again.
> Then try: 1) *List the tables in one of my Databricks catalogs* (works), 2) *Run SELECT 1 on
> Databricks* (blocked), 3) *Write a query that counts rows per day in one of my tables* (I write it,
> you run it)."
