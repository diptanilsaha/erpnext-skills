# Skills

A collection of patterns, conventions, and reference guides for writing logic in ERPNext.

Each document captures hard-won knowledge from real migrations and feature work — meant
to be consulted before starting a task and updated whenever something new is learned.

## Contents

| File | What it covers |
|---|---|
| [raw_sql_to_query_builder.md](raw_sql_to_query_builder.md) | Migrating `frappe.db.sql` to `frappe.qb` for MariaDB/PostgreSQL compatibility |
| [accounts-code-review/](accounts-code-review/) | Agent skill: reviews an ERPNext Accounts PR against its issue or ticket, runs a before/after ledger comparison on a bench site, checks each failure case for reachability, and says if the PR is mergeable |

## Install a skill

Skill directories (with a `SKILL.md`) install into an agent:

```
npx skills add diptanilsaha/erpnext-skills --skill accounts-code-review
```

Read the skill's own `README.md` for what it needs and what it changes.

## How to use

- Read the relevant skill document before starting a task in that area.
- After completing a task, update the document with any new patterns or edge cases
  encountered.

---

> **WARNING** — Every line in this repository is a candidate for being fed directly
> into code. Review each document carefully before using its content in a PR.
> Do not push incomplete, speculative, or untested patterns.
