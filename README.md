# Databricks AI Guardrails

**Let Claude and Cursor see the *layout* of your Databricks data, but never the data itself.**

When an AI assistant helps you with Databricks, it's useful for it to know which tables and
columns exist. It should **not** be able to run queries or read the rows inside those tables.
This tool makes sure of that.

Think of a library. The AI may read the **catalogue cards** (book titles, chapter names), but it
may not **open the books**.

| ✅ The AI **can** | ❌ The AI **cannot** |
|---|---|
| List catalogs, schemas and tables | Run SQL queries |
| See column names and types | See, preview or count rows |
| Write SQL or Python code for you | Run that code on Databricks |
| | Read your Databricks password or login |

The AI can still write queries for you. **You** decide whether to run them.

---

## Pick the app you use

| I use… | How you set it up | Time |
|---|---|---|
| **Claude app: Cowork** | [Add a plugin with a few clicks](#claude-app-cowork) | 2 min |
| **Cursor desktop app** | [Paste one message into the chat](#cursor-desktop-app) | 10 min |
| **Claude app: Code tab** | [Paste one message into the chat](#claude-app-code-tab) | 10 min |
| **Claude Code or Cursor CLI in a terminal** | [Manual install](docs/manual-install.md) | 10 min |

Works on **Mac** and **Windows**. Using more than one app? Set up each one. They don't conflict.

---

## Claude app: Cowork

No downloads and no typing commands. You add the guardrails as a **plugin**.

1. Open the **Claude** app.
2. In the left sidebar, click **Customize**.
3. Click **Plugins**.
4. Click **Add**, then **Add marketplace**.
5. Type this and confirm:
   ```
   SiSiHenry/databricks-ai-guardrails
   ```
6. In the list that appears, find **databricks-ai-guardrails** and click **Add** (or **Install**).
7. Make sure the plugin is switched **on**.
8. **Start a new Cowork task.** Tasks that were already open don't pick up the plugin.

That's it. Now [check that it works](#check-that-it-works).

<details>
<summary>Can't use "Add marketplace"? Upload the plugin instead.</summary>

1. On this page, click the green **`<> Code`** button, then **Download ZIP**. Unzip it (double-click).
2. In the Claude app: **Customize → Plugins → Add → Upload plugin**.
3. Choose the folder **`plugins/databricks-ai-guardrails`** inside the unzipped folder.
</details>

> **Good to know (Cowork):**
> - The guard checks every tool Claude uses in Cowork, including connectors.
> - It blocks any connector tool whose name says it runs **SQL or queries**, even ones not from
>   Databricks, because a connector's name doesn't always show which service it belongs to.
> - Tools that **list or describe** tables still work.

---

## Cursor desktop app

You'll ask Cursor's AI to install the guardrails for you. You only click **Run** when it asks,
and sign in to Databricks once in your browser.

1. Open **Cursor**.
2. Open the project folder you work on (**File → Open Folder…**, or pick the project in the
   Agents window).
3. Open the AI chat (Agent). If there's a choice between **Local** and **Cloud**, choose **Local**.
4. Copy this message, paste it into the chat, and press <kbd>Enter</kbd>:

   ```
   Please install the Databricks AI Guardrails safety tool on this computer for this project.
   Read https://raw.githubusercontent.com/SiSiHenry/databricks-ai-guardrails/main/AGENT_INSTALL.md
   and follow it step by step. Explain each step to me in simple words and tell me whenever I
   need to do something.
   ```

5. Cursor will ask permission to run commands. Click **Run** each time.
6. If it asks for your **Databricks address**: open Databricks in your browser and copy the
   address from the address bar, up to `.com` or `.net` (for example
   `https://mycompany.cloud.databricks.com`). Paste it into the chat.
7. If a **browser window** opens, sign in to Databricks as usual, then return to Cursor.
8. When Cursor says it's done, **quit Cursor completely and reopen it**.
   **Mac:** <kbd>⌘ Cmd</kbd> + <kbd>Q</kbd>. **Windows:** **File → Exit**.

Now [check that it works](#check-that-it-works).

> Keep using **Local** agents for Databricks work. Cursor's **Cloud** agents run on Cursor's
> servers, where this guard isn't installed.

---

## Claude app: Code tab

Same idea: Claude installs it for you.

1. Open the **Claude** app and click the **Code** tab.
2. Choose your **project folder**.
3. Copy this message, paste it into the chat, and press <kbd>Enter</kbd>:

   ```
   Please install the Databricks AI Guardrails safety tool on this computer for this project.
   Read https://raw.githubusercontent.com/SiSiHenry/databricks-ai-guardrails/main/AGENT_INSTALL.md
   and follow it step by step. Explain each step to me in simple words and tell me whenever I
   need to do something.
   ```

4. When Claude asks permission to run a command, click **Allow**.
5. If it asks for your **Databricks address**, copy it from your browser's address bar (up to `.com`
   or `.net`) and paste it in. If a browser window opens, sign in to Databricks.
6. When Claude says it's done, **quit the Claude app completely and reopen it**.
   **Mac:** <kbd>⌘ Cmd</kbd> + <kbd>Q</kbd>. **Windows:** right-click the Claude icon next to the
   clock and choose **Quit**.

Now [check that it works](#check-that-it-works).

---

## Check that it works

Send these three messages to the AI, one at a time.

| # | Type this | What should happen |
|---|---|---|
| 1 | *List the tables in one of my Databricks catalogs.* | ✅ It shows table names. |
| 2 | *Run the SQL query `SELECT 1` on Databricks.* | ❌ **Blocked.** You'll see **"BLOCKED by Databricks metadata-only rule"** (or the AI tells you the guardrail stopped it) and it offers to write the code instead. |
| 3 | *Write a SQL query that counts rows per day in one of my tables.* | ✅ It **writes** the query into a file but **doesn't run** it. |

If all three behave like this, you're protected. 🎉

> **Cursor and the Code tab:** if test 1 fails, ask the AI to *"use the Databricks CLI with the
> agent profile"*. That's the safe route it's allowed to use.
>
> **Cowork:** test 1 needs Cowork to be able to reach Databricks, usually through a Databricks
> connector (**Customize → Connectors**). Without one, tests 2 and 3 still show the guard working.

---

## Everyday use

**Nothing to do.** In Cursor and the Code tab, the guard starts by itself when you log in to your
computer. In Cowork, the plugin stays on until you switch it off.

If the AI says it's **"waiting for the developer's Databricks login"**, your Databricks sign-in has
expired. Ask the AI: *"How do I sign in to Databricks again?"*, or run
`databricks auth login --profile DEFAULT` yourself. The guard picks up the new sign-in within
about 15 seconds.

---

## Troubleshooting

<details>
<summary><b>The AI says Python isn't installed</b></summary>

Download Python from [python.org/downloads](https://www.python.org/downloads/) and install it. On
Windows, tick **"Add python.exe to PATH"** on the first screen. Quit and reopen Cursor/Claude, then
paste the install message again.
</details>

<details>
<summary><b>Test 2 was NOT blocked</b></summary>

- **Cowork:** check the plugin is switched on (**Customize → Plugins**), then start a **new** task.
- **Cursor / Code tab:** make sure you fully quit and reopened the app. Make sure you're in the same
  project folder, and (Cursor) that the agent is **Local**. Then ask the AI: *"Run the Databricks
  guardrails self-test with proxy_service.py doctor and tell me the result."* Every line should
  start with `ok`.
</details>

<details>
<summary><b>The AI says "connection refused" or "waiting for login"</b></summary>

Ask the AI: *"Show me the Databricks guardrails status using proxy_service.py status."* If it says
it's **not listening**, restart your computer. The guard starts at login. If it says
**waiting for login**, sign in to Databricks again (see [Everyday use](#everyday-use)).
</details>

<details>
<summary><b>The AI got blocked when it only wanted to list tables</b></summary>

Ask it to *"use the agent profile"* (Cursor / Code tab), or to *"use the list or describe tool"*
(Cowork).
</details>

<details>
<summary><b>I can't see the <code>.guards</code> folder in my project</b></summary>

Folders whose names start with a dot are hidden. **Mac:** press
<kbd>⌘ Cmd</kbd> + <kbd>Shift</kbd> + <kbd>.</kbd> in Finder. **Windows:** in File Explorer choose
**View → Show → Hidden items**.
</details>

---

## Uninstall

**Cowork:** **Customize → Plugins**, open **databricks-ai-guardrails**, and remove it (or switch
it off).

**Cursor / Code tab:** for safety, the AI isn't allowed to remove the guardrails, so you do this
step yourself. Open the terminal (**Mac:** <kbd>⌘ Cmd</kbd> + <kbd>Space</kbd>, type **Terminal**;
**Windows:** **Start**, type **PowerShell**), paste these two lines and press <kbd>Enter</kbd>:

| Mac | Windows |
|---|---|
| `curl -fsSL -o /tmp/g.zip https://github.com/SiSiHenry/databricks-ai-guardrails/archive/refs/heads/main.zip && unzip -oq /tmp/g.zip -d /tmp/g && python3 /tmp/g/databricks-ai-guardrails-main/install.py --uninstall` | `iwr https://github.com/SiSiHenry/databricks-ai-guardrails/archive/refs/heads/main.zip -OutFile $env:TEMP\g.zip; Expand-Archive $env:TEMP\g.zip $env:TEMP\g -Force; py $env:TEMP\g\databricks-ai-guardrails-main\install.py --uninstall` |

Then quit and reopen your apps. The uninstaller removes the hooks, the background service and the
`[agent]` profile, and puts your settings back as they were.

---

## For your team and IT

### Teammates on the same project

Once the project contains the `.guards` folder, a teammate can paste this into Cursor or the Code
tab:

```
Please set up the Databricks AI Guardrails for this computer. Run .guards/setup/install.py
--user-only from this project folder (use py on Windows, python3 on Mac), then tell me the
self-test result and remind me to restart the app.
```

### How it works

| App | What protects you |
|---|---|
| **Cowork** | A plugin. Its check runs inside Cowork's sandbox before every tool call and blocks anything that would query or read data. |
| **Cursor, Code tab, terminals** | ① A **guard** checks every command and tool call before it runs. ② A small **local gateway** on your computer passes only "list / describe" requests to Databricks using *your* sign-in, so the AI never holds your login. |

Both use the same written rule, which tells the AI what's allowed. Every decision is logged on your
computer. To check that the AI followed the rule, ask it to run
`.guards/databricks_guard.py verify`.

Technical guide: [`guards/README.md`](guards/README.md). Cowork plugin:
[`plugins/databricks-ai-guardrails`](plugins/databricks-ai-guardrails).

### Good to know

- **A safety net, not a vault.** The AI runs as you on your computer. The guard blocks the known
  ways it could reach your Databricks login, but this is a strong safety net, not a locked vault.
  For stricter setups, see the technical guide.
- **Cursor Cloud agents** don't use your computer, so this guard doesn't apply there. Use
  **Local**.
- **Cursor CLI** currently lets the guard check only shell commands. The local gateway still
  allows metadata only.
- **Claude chat** (not Cowork or Code) doesn't run tools on your computer. Don't connect a
  Databricks connector there that can run queries.
- **Requirements:**
  - **Cowork:** nothing extra.
  - **Cursor and the Code tab:** Mac or Windows 10/11, Python 3.9+ and the Databricks CLI. The AI
    checks both, and installs the CLI if it's missing.
