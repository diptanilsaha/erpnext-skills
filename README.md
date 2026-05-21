# Skills

A collection of patterns, conventions, and reference guides for writing logic in ERPNext.

Each document captures hard-won knowledge from real migrations and feature work — meant
to be consulted before starting a task and updated whenever something new is learned.

## Contents

| File | What it covers |
|---|---|
| [raw_sql_to_query_builder.md](raw_sql_to_query_builder.md) | Migrating `frappe.db.sql` to `frappe.qb` for MariaDB/PostgreSQL compatibility |

## How to use

- Read the relevant skill document before starting a task in that area.
- After completing a task, update the document with any new patterns or edge cases
  encountered.

---

> **WARNING** — Every line in this repository is a candidate for being fed directly
> into code. Review each document carefully before using its content in a PR.
> Do not push incomplete, speculative, or untested patterns.
