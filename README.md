# Databricks AI Guardrails

**Let Claude and Cursor see the *layout* of your Databricks data, but never the data itself.**

When an AI assistant helps you write code for Databricks, it's useful for it to know which tables
and columns exist. It should **not** be able to run queries or read the rows inside those tables.
This tool makes sure of that, on your own computer, for:

| App | Supported |
|---|---|
| **Claude desktop app** (the *Code* tab) | ✅ |
| **Claude Code** (in the terminal) | ✅ |
| **Cursor** (the editor app) | ✅ |
| **Cursor CLI** (in the terminal) | ✅ (see [note](#good-to-know)) |
| **Mac** and **Windows** | ✅ |

### What the AI can and can't do

Think of a library. The AI may read the **catalogue cards** (book titles, chapter names), but it
may not **open the books**.

| ✅ The AI **can** | ❌ The AI **cannot** |
|---|---|
| List catalogs, schemas and tables | Run SQL queries |
| See column names and types | See, preview or count rows |
| Write SQL or Python code for you | Run that code against Databricks |
| | Read your Databricks password or login |

The AI can still write queries for you. **You** decide whether to run them.

---

## Contents

1. [Before you start](#1-before-you-start-about-10-minutes-once)
2. [Download this tool](#2-download-this-tool)
3. [Install it](#3-install-it)
4. [Turn it on in your apps](#4-turn-it-on-in-your-apps)
5. [Check that it works](#5-check-that-it-works)
6. [Everyday use](#6-everyday-use)
7. [Troubleshooting](#7-troubleshooting)
8. [Uninstall](#8-uninstall)
9. [For your team and IT](#9-for-your-team-and-it)

> **What is "the terminal"?** It's a window where you type commands. You'll only need it for a few
> minutes, to copy and paste the commands below.
> - **Mac:** press <kbd>⌘ Cmd</kbd> + <kbd>Space</kbd>, type **Terminal**, press <kbd>Enter</kbd>.
> - **Windows:** click **Start**, type **PowerShell**, press <kbd>Enter</kbd>.
>
> To run a command, paste it in and press <kbd>Enter</kbd>.

---

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

If it says `PROBLEMS FOUND`, see [Troubleshooting](#7-troubleshooting).

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

## 6. Everyday use

**There's nothing to do.** The guard starts automatically when you log in to your computer.

- **If the AI says it's "waiting for the developer's Databricks login"**, your Databricks sign-in
  has expired. Sign in again (step 1c). The tool picks it up within about 15 seconds.
- **To check on it at any time**, run:

  | Mac | Windows |
  |---|---|
  | `python3 ~/.databricks-guard/bin/proxy_service.py status` | `py $HOME\.databricks-guard\bin\proxy_service.py status` |

  You'll see `listening: yes` and `acting as: your-email@company.com`.
- **To run the full self-test again**, use the same command with `doctor` instead of `status`.

---

## 7. Troubleshooting

<details>
<summary><b>"python3: command not found" (Mac) or "py is not recognized" (Windows)</b></summary>

Python isn't installed, or Windows can't find it. Install it from
[python.org/downloads](https://www.python.org/downloads/). On Windows, tick **"Add python.exe to
PATH"**. Then close the terminal, open a new one, and try again.
</details>

<details>
<summary><b>The installer warns "databricks CLI not found"</b></summary>

Install the Databricks command-line tool (step 1b), close and reopen the terminal, sign in
(step 1c), then run the install command again.
</details>

<details>
<summary><b>The self-test says <code>FAIL … acting as: error</code></b></summary>

The tool can't sign in to Databricks for you. Repeat step 1c (sign in), then run the self-test
(`doctor`, see step 6).
</details>

<details>
<summary><b>The AI says "connection refused" when it uses Databricks</b></summary>

The guard's background service isn't running. Restart it:

| Mac | Windows |
|---|---|
| `python3 ~/.databricks-guard/bin/proxy_service.py restart` | `py $HOME\.databricks-guard\bin\proxy_service.py restart` |

If that doesn't help, run the install command from step 3 again.
</details>

<details>
<summary><b>The AI got blocked when it only wanted to list tables</b></summary>

It probably forgot to use the safe profile. Ask it to *"use the agent profile"*. It will then run
`databricks -p agent …`, which is allowed.
</details>

<details>
<summary><b>Test 2 in step 5 was NOT blocked</b></summary>

1. Make sure you fully quit and reopened the app (step 4).
2. Run the self-test (`doctor`, step 6). Every line should start with `ok`.
3. Make sure you opened the same project folder you gave the installer.
</details>

<details>
<summary><b>I can't see the <code>.guards</code> folder in my project</b></summary>

Folders whose names start with a dot are hidden. **Mac:** press
<kbd>⌘ Cmd</kbd> + <kbd>Shift</kbd> + <kbd>.</kbd> in Finder. **Windows:** in File Explorer choose
**View → Show → Hidden items**.
</details>

<details>
<summary><b>My Databricks profile isn't called DEFAULT</b></summary>

Add `--upstream-profile YOUR-PROFILE-NAME` to the end of the install command in step 3.
</details>

---

## 8. Uninstall

From the downloaded folder:

| Mac | Windows |
|---|---|
| `python3 install.py --uninstall` | `py install.py --uninstall` |

This:
- removes the hooks from Claude and Cursor;
- removes the background service;
- removes the `[agent]` profile;
- puts your settings back as they were.

Then quit and reopen your apps. The rule files in your project (`CLAUDE.md`, `.cursor/rules/`,
`.guards/`) stay until you delete them.

---

## 9. For your team and IT

### Teammates

If your project already contains the `.guards` folder (someone set it up and shared it), a
teammate only needs to set up **their own computer**. They run this **from inside the project folder**:

| Mac | Windows |
|---|---|
| `python3 .guards/setup/install.py --user-only` | `py .guards\setup\install.py --user-only` |

Then they follow steps 4 and 5.

### How it works

```
  AI assistant (Claude / Cursor)
        │ every command it wants to run
        ▼
  ① Guard: checks the command first and blocks anything that would query or read data
        │ allowed commands only
        ▼
  ② Local gateway on your computer: forwards only "list / describe" requests to Databricks,
        │ using YOUR sign-in. The AI never holds your login.
        ▼
  Databricks
```

There are three layers:
1. **A written rule** (`CLAUDE.md`, `.cursor/rules/`) tells the AI what's allowed.
2. **A guard** checks every command, file read and tool call **before** it runs, and blocks
   violations.
3. **A local gateway** passes only metadata requests to Databricks. Even a command that slipped
   past the guard can't read data.

Every decision is logged on your computer. To check that the AI has followed the rule, run this in
the project folder: `python3 .guards/databricks_guard.py verify` (Windows:
`py .guards\databricks_guard.py verify`).

The technical guide is in [`guards/README.md`](guards/README.md).

### Good to know

- **Same computer, same user.** The AI runs as you on your computer. The guard blocks the known
  ways it could reach your Databricks login. That makes this a strong safety net, but not a
  locked vault. For stricter setups, see the technical guide.
- **Cursor CLI.** Today the Cursor CLI only lets the guard check **shell commands**, not its other
  tools. The local gateway still allows metadata only, so data stays protected.
- **Claude chat** (not the Code tab) doesn't run commands on your computer, so it isn't covered.
  Don't give it a Databricks connector that can run queries.
- **Requirements:** macOS or Windows 10/11, Python 3.9+, Databricks CLI 0.205+, and an OAuth
  (browser) sign-in to Databricks.
