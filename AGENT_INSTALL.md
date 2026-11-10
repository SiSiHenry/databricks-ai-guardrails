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

## Step 3: Make sure the Databricks command-line tool is installed

Run `databricks --version`. If it prints `Databricks CLI v0.205` or higher, go to Step 4.

Otherwise, install it:

| Computer | Command |
|---|---|
| Mac with Homebrew (`brew --version` works) | `brew install databricks/tap/databricks` |
| Mac without Homebrew | `curl -fsSL https://raw.githubusercontent.com/databricks/setup-cli/main/install.sh \| sh`. If it says `/usr/local/bin` is not writable, tell the user it needs their Mac password and run it again with `sudo sh` in place of `sh` |
| Windows | `winget install Databricks.DatabricksCLI --accept-source-agreements --accept-package-agreements` |

**Windows only:** after installing, `databricks` may not be found until the app restarts. In that
case use the full path `"$env:LOCALAPPDATA\Microsoft\WinGet\Links\databricks.exe"` in place of
`databricks` for the rest of this guide.

## Step 4: Make sure the user is signed in to Databricks

Run `databricks auth profiles`. If a profile named **DEFAULT** is listed with **Valid: YES**, go to
Step 5.

Otherwise:

1. Ask the user:
   > "Please open Databricks in your web browser and copy the address from the address bar, up to
   > and including `.com` or `.net`, for example `https://mycompany.cloud.databricks.com`, and paste
   > it here."
2. Run this with their address:
   ```
   databricks auth login --host <ADDRESS> --profile DEFAULT
   ```
3. Tell the user:
   > "A browser window is opening. Please sign in to Databricks as usual and come back here when it
   > says you're done."
4. Run `databricks auth profiles` again and check that DEFAULT is **Valid: YES**.

If the user's existing profile has a different name, note it as **PROFILE** and add
`--upstream-profile PROFILE` to the Step 5 command.

## Step 5: Run the installer for the open project folder

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

If it says `PROBLEMS FOUND`, read the lines that start with `FAIL` and fix what you can:

| FAIL line mentions | What to do |
|---|---|
| `acting as: error` | Repeat Step 4, then run `PY ~/.databricks-guard/bin/proxy_service.py doctor` (Windows: `PY "$HOME\.databricks-guard\bin\proxy_service.py" doctor`) |
| `not listening` | Wait 20 seconds, then run the same `doctor` command again |
| a hook `via` some shell | Tell the user the exact line and suggest they open an issue at https://github.com/SiSiHenry/databricks-ai-guardrails/issues |

## Step 6: Tell the user what to do next

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
- Never re-run, change, or uninstall the guardrails. If the user wants to remove them, give them
  the uninstall steps from the README so they can do it themselves.
