# Manual install (using the terminal)

Most people don't need this page: the [README](../README.md) shows how to install by **pasting one
message into Cursor or Claude**. Use this page if you prefer to type the commands yourself, or if
you use **Claude Code** or the **Cursor CLI** in a terminal.

> **What is "the terminal"?** It's a window where you type commands.
> - **Mac:** press <kbd>⌘ Cmd</kbd> + <kbd>Space</kbd>, type **Terminal**, press <kbd>Enter</kbd>.
> - **Windows:** click **Start**, type **PowerShell**, press <kbd>Enter</kbd>.
>
> To run a command, paste it in and press <kbd>Enter</kbd>.

## 1. Before you start (about 10 minutes, once)

You need three things. For each one, run the "check" command first. If it works, skip the install.

### a) Python

| | Mac | Windows |
|---|---|---|
| **Check** | `python3 --version` | `py --version` |
| **You should see** | `Python 3.9` or higher | `Python 3.9` or higher |
| **If it's missing** | Download from [python.org/downloads](https://www.python.org/downloads/) and install | Download from [python.org/downloads](https://www.python.org/downloads/). In the installer, **tick "Add python.exe to PATH"** |

> **Mac:** if a box pops up asking to install "command line developer tools", click **Install**
> and wait for it to finish.

### b) The Databricks command-line tool

| | Mac | Windows |
|---|---|---|
| **Check** | `databricks --version` | `databricks --version` |
| **You should see** | `Databricks CLI v0.2xx` or higher | `Databricks CLI v0.2xx` or higher |
| **If it's missing** | `brew install databricks/tap/databricks` | `winget install Databricks.DatabricksCLI` |

> **Mac:** if `brew` isn't found, install Homebrew first from [brew.sh](https://brew.sh), then try again.
> **Windows:** close PowerShell and open it again after installing.

More help: [Databricks CLI install guide](https://docs.databricks.com/aws/en/dev-tools/cli/install).

### c) Sign in to Databricks

1. Open Databricks in your web browser and copy the address from the address bar, **up to and
   including** `.com` or `.net`. For example, `https://adb-1234567890.12.azuredatabricks.net` or
   `https://mycompany.cloud.databricks.com`.
2. Run this, replacing the address with yours:

   ```
   databricks auth login --host https://YOUR-WORKSPACE-ADDRESS --profile DEFAULT
   ```

3. Your browser opens. Sign in as usual. When it says you're done, return to the terminal.

---

## 2. Download this tool

**Easiest:** on this page, click the green **`<> Code`** button, then **Download ZIP**.
Open your **Downloads** folder and double-click the ZIP to unpack it. You now have a folder called
**`databricks-ai-guardrails-main`**.

<details>
<summary>Prefer Git? Click here.</summary>

```
git clone https://github.com/SiSiHenry/databricks-ai-guardrails.git
```
The folder will be called `databricks-ai-guardrails` instead of `databricks-ai-guardrails-main`.
</details>

---

## 3. Install it

You'll point the installer at **your project folder**: the folder you open in Claude or Cursor.

### Mac

1. In Terminal, go to the downloaded folder:
   ```
   cd ~/Downloads/databricks-ai-guardrails-main
   ```
2. Type the start of the command below, **including the space at the end**. Don't press Enter yet:
   ```
   python3 install.py 
   ```
3. **Drag your project folder** from Finder onto the Terminal window. Its location appears after
   the command.
4. Press <kbd>Enter</kbd>.

### Windows

1. In PowerShell, go to the downloaded folder:
   ```
   cd $HOME\Downloads\databricks-ai-guardrails-main
   ```
2. In File Explorer, find your project folder. Hold <kbd>Shift</kbd>, **right-click** it, and choose
   **Copy as path**.
3. In PowerShell, type `py install.py ` (with a space at the end), then **right-click** to paste the
   path. It should look like:
   ```
   py install.py "C:\Users\you\Documents\my-project"
   ```
4. Press <kbd>Enter</kbd>.

### What you should see

The installer lists what it set up, then runs a self-test. The last line should say:

```
RESULT: ALL CHECKS PASSED
```

If it says `PROBLEMS FOUND`, see [Troubleshooting](../README.md#troubleshooting).

> **Using several projects?** Run the install command once for each project folder. The setup on
> your computer is shared, so the extra runs only add the rule files to each project.

---

## 4. Turn it on in your apps

The installer has already configured every app. Each app just needs to be **fully closed and
reopened** so it notices.

### Claude desktop app

1. **Quit** Claude completely. **Mac:** <kbd>⌘ Cmd</kbd> + <kbd>Q</kbd>. **Windows:** right-click
   the Claude icon in the taskbar, then **Close window**. Also check the system tray (next to the
   clock) and quit it there if it's still running.
2. Open Claude again and click the **Code** tab.
3. Choose your **project folder**.
4. Done. Go to [step 5](#5-check-that-it-works) to test it.

> The ordinary **chat** tab can't run commands on your computer, so it doesn't need this. Don't
> connect a Databricks connector there that can run queries.

### Claude Code (terminal)

1. Close every terminal window where `claude` is running.
2. Open a new terminal, go to your project folder, and start Claude Code:
   - **Mac:** `cd ` + drag the project folder in, press <kbd>Enter</kbd>, then type `claude`
   - **Windows:** `cd "C:\path\to\your\project"`, then `claude`
3. Done. Go to [step 5](#5-check-that-it-works).

### Cursor (editor app)

1. **Quit** Cursor completely. **Mac:** <kbd>⌘ Cmd</kbd> + <kbd>Q</kbd>. **Windows:** **File → Exit**.
2. Open Cursor and open your **project folder** (**File → Open Folder…**).
3. Done. Go to [step 5](#5-check-that-it-works).

### Cursor CLI (terminal)

1. Close every terminal window where the Cursor agent is running.
2. Open a new terminal, go to your project folder, and start it (`cursor-agent`, or `agent` in
   newer versions).
3. Done. Go to [step 5](#5-check-that-it-works).

---

## 5. Check that it works

In the app you just set up, send these three messages to the AI, one at a time.

| # | Type this to the AI | What should happen |
|---|---|---|
| 1 | *Use the Databricks CLI with the agent profile to list my catalogs.* | ✅ It runs `databricks -p agent catalogs list` and shows catalog names. |
| 2 | *Run the SQL query `SELECT 1` on Databricks.* | ❌ It's **blocked**. You'll see a message starting with **"BLOCKED by Databricks metadata-only rule"**, and the AI offers to write the code for you instead. |
| 3 | *Write a SQL query that counts rows per day in one of my tables.* | ✅ It **writes** the query but **doesn't run** it. |

If all three behave like this, you're protected. 🎉

---

