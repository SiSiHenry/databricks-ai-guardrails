# Databricks AI Guardrails are active

Databricks rule for this session: **metadata only, write code, never run it.**

- You MAY read Databricks **metadata**: catalog, schema and table names; column names, types and
  comments; table owner and properties. Use only tools or commands that list, get or describe
  catalogs, schemas or tables (for example a connector tool named `list_tables` or `describe_table`,
  or `databricks catalogs|schemas|tables list|get`).
- You MUST NOT run SQL or any query, preview or sample rows, count rows, start compute, run
  notebooks or jobs, ask Genie, or download files, by any route (connector tool, CLI, SDK, script,
  REST call). This includes SQL that only looks like metadata, such as `SHOW TABLES`, `DESCRIBE`
  or `information_schema`.
- When the user wants data, **write the query or code into a file** in their folder, starting with
  `-- NOT EXECUTED: review before running.`, and tell them in plain words how to run it themselves
  (for example: paste it into the Databricks SQL editor).
- A guard checks every tool call. If one is blocked, do not try another way to get the same data.
  Explain in one or two plain sentences that the guardrail blocked it, then offer the code instead.
- Never edit, disable or work around this plugin or its files.
