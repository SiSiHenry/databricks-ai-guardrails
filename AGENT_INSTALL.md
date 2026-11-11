# Instructions for the AI assistant: install Databricks AI Guardrails

You are an AI assistant (Cursor or the Claude app's Code tab) running on the user's own computer.
The user asked you to install Databricks AI Guardrails for the project folder that is open now.
The user is probably **not technical**.

**How to communicate:**
- Before each step, say in one plain sentence what you are about to do.
- When the app asks the user to approve a command, tell them to click **Run** / **Allow**.
- Never show tokens or passwords. Don't paste long command output into the chat; summarise it.

**What not to do:**
- Don't edit any settings file by hand. The installer does all of it.
- Don't skip a step. If a step fails, stop and tell the user what happened in plain words.

---

## Step 1: Work out the computer type and the Python command

Run **one** of these and note which works:

| Computer | Try in this order | Works when it prints |
|---|---|---|
| Mac | `python3 --version` | `Python 3.9` or higher |
| Windows (PowerShell) | `py --version`, then `python --version` | `Python 3.9` or higher |

Use the command that worked as **PY** in all later steps: `python3` on Mac; `py` or `python` on
Windows.

If none works, stop and tell the user:
> "This needs Python, which isn't installed yet. Please download it from
> https://www.python.org/downloads/ and install it. On Windows, tick **Add python.exe to PATH**
> in the first screen. Then fully quit and reopen this app and ask me again."

On a Mac, a pop-up may offer to install "command line developer tools". Tell the user to click
**Install** and wait, then retry.

## Step 2: Download the tool to a temporary folder

**Mac:**

```
curl -fsSL -o /tmp/dbx-guardrails.zip https://github.com/SiSiHenry/databricks-ai-guardrails/archive/refs/heads/main.zip && rm -rf /tmp/dbx-guardrails && unzip -oq /tmp/dbx-guardrails.zip -d /tmp/dbx-guardrails && echo OK
```

The installer is now at `/tmp/dbx-guardrails/databricks-ai-guardrails-main/install.py`.

**Windows (PowerShell):**

```
Invoke-WebRequest https://github.com/SiSiHenry/databricks-ai-guardrails/archive/refs/heads/main.zip -OutFile "$env:TEMP\dbx-guardrails.zip"; Expand-Archive "$env:TEMP\dbx-guardrails.zip" "$env:TEMP\dbx-guardrails" -Force; "OK"
```

The installer is now at `$env:TEMP\dbx-guardrails\databricks-ai-guardrails-main\install.py`.

## Step 3: Nothing to do for Databricks sign-in

The user already has the Databricks command-line tool installed and is signed in to their workspace
(OAuth). Don't install the CLI and don't run any `databricks auth` command. The installer only
**checks** and reports.

## Step 4: Run the installer for the open project folder

Run it **from the project folder** (your current working folder):

| Computer | Command |
|---|---|
| Mac | `python3 /tmp/dbx-guardrails/databricks-ai-guardrails-main/install.py "$(pwd)"` |
| Windows | `PY "$env:TEMP\dbx-guardrails\databricks-ai-guardrails-main\install.py" "$PWD"` (replace `PY` with `py` or `python` from Step 1) |

The installer:
- sets up the guard for Cursor and Claude on this computer;
- adds the rule files to the project;
- starts a small background service that launches every time the user logs in;
- runs a self-test.

The last line of its output must say:

```
RESULT: ALL CHECKS PASSED
```

If the user's Databricks profile isn't called **DEFAULT**, add `--upstream-profile <NAME>`.

If it says `PROBLEMS FOUND`, read the lines that start with `FAIL` and fix what you can:

| FAIL line mentions | What to do |
|---|---|
| `acting as: error`, or the installer printed `Not signed in` | Tell the user their Databricks sign-in has expired and ask them to sign in again themselves (for example with `databricks auth login --profile DEFAULT` in their own terminal). Then run `PY ~/.databricks-guard/bin/proxy_service.py doctor` (Windows: `PY "$HOME\.databricks-guard\bin\proxy_service.py" doctor`) |
| `not listening` | Wait 20 seconds, then run the same `doctor` command again |
| a hook `via` some shell | Tell the user the exact line and suggest they open an issue at https://github.com/SiSiHenry/databricks-ai-guardrails/issues |

## Step 5: Tell the user what to do next

Say this, in your own friendly words:

> "Done! The Databricks guardrails are installed. From now on I can see your table and column
> names and write code for you, but I can't run queries or read your data.
>
> **One last thing:** please fully quit this app and open it again so the guard switches on.
> - **Mac:** press **Cmd + Q**.
> - **Windows:** for Cursor choose **File → Exit**; for Claude, right-click its icon by the clock
>   and choose **Quit**.
>
> Then open this project again and try these three messages:
> 1. *Use the Databricks CLI with the agent profile to list my catalogs.* (should work)
> 2. *Run the SQL query SELECT 1 on Databricks.* (should be blocked)
> 3. *Write a SQL query that counts rows per day in one of my tables.* (I write it, you run it)"

---

## After installation: rules you must follow

The project now contains `CLAUDE.md` and `.cursor/rules/databricks-metadata-only.mdc`. Follow
them:
- Use only the `agent` profile for Databricks (`databricks -p agent …`,
  `WorkspaceClient(profile="agent")`).
- Read metadata only. Write code for the user to run; never run queries yourself.
- Never run `databricks auth …` or `databricks configure` yourself, and never re-run, change, or
  uninstall the guardrails. If the user wants to remove them, give them
  the uninstall steps from the README so they can do it themselves.
