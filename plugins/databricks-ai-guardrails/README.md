# Databricks AI Guardrails (Claude plugin)

Lets Claude see your Databricks **table and column names** and write code for you, but blocks it
from **running queries or reading data**.

- **Where it works:** Claude Cowork (the plugin's hooks run inside Cowork's sandbox) and Claude
  Code (the plugin follows your account).
- **What's inside:**
  - a skill with the rule;
  - a check that runs before every tool call and blocks anything that would query or read
    Databricks data, including connector tools such as `execute_sql`, `run_query` or Genie;
  - a short reminder of the rule at the start of every session.

Install in the Claude app: open **Customize → Plugins → Add → Add marketplace**, enter
`SiSiHenry/databricks-ai-guardrails`, then add **databricks-ai-guardrails**.

Install in Claude Code:

```
/plugin install databricks-ai-guardrails --marketplace SiSiHenry/databricks-ai-guardrails
```

Full instructions: https://github.com/SiSiHenry/databricks-ai-guardrails

**Note:** in Cowork, the guard blocks *any* connector tool whose name says it runs SQL or queries
(Databricks or not), because connector names don't always say which service they belong to.
