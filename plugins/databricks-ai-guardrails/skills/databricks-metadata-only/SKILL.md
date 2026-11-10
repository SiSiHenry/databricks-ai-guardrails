---
name: databricks-metadata-only
description: This skill should be used whenever a task involves Databricks, Unity Catalog, a Databricks SQL warehouse, Genie, Delta tables, or a Databricks connector, for example "what tables do we have", "describe the orders table", "write a query for", "how many rows", "show me the data", or "run this on Databricks". It defines what Claude may and may not do with Databricks.
---

# Databricks: metadata only, write code, never run it

Apply these rules to every Databricks-related step. A guard hook enforces them and blocks
violations; follow them so that nothing needs to be blocked.

## Allowed

- Read metadata: catalog, schema and table names; column names, types and comments; owner and
  table properties. A row count is allowed **only** if it is already stored in table properties
  (for example `spark.sql.statistics.numRows`). Otherwise say the count isn't in the metadata.
- Use only list / get / describe tools or commands for catalogs, schemas and tables, for example
  connector tools named like `list_catalogs`, `list_schemas`, `list_tables`, `get_table`,
  `describe_table`, or the CLI commands `databricks catalogs|schemas|tables list|get`.
- Write SQL, Python or PySpark code, notebooks or job definitions **as files** for the user.

## Never

- Run SQL or any query, including `SELECT … LIMIT 1`, `COUNT(*)`, `SHOW TABLES`, `DESCRIBE` or
  `information_schema` queries.
- Preview, sample or download rows or files. Ask Genie. Start clusters or warehouses. Run notebooks
  or jobs. Read secrets or credentials.
- Do any of the above indirectly: through a script, a different tool, a REST call, or by asking the
  user to paste query results so you can continue.
- Edit, disable or work around the guardrails plugin.

## When the user wants data

1. Look up the table's columns with a metadata tool so the code is correct.
2. Write the query into a file in the user's folder (for example `orders_per_day.sql`). Start it with
   `-- NOT EXECUTED: review before running.`
3. Explain in plain language how they can run it themselves, for example: "Open Databricks, go to
   **SQL Editor**, paste the query and click **Run**."

## When something is blocked

The guard replies with a message starting `BLOCKED by Databricks metadata-only rule`. Do not
retry the same request another way. Tell the user, in one or two plain sentences, that the
Databricks guardrail stopped the AI from reading data, then offer to write the code for them.

## Audience

Many users are not technical. Avoid jargon, file paths and command names in explanations unless
the user asks for them.
