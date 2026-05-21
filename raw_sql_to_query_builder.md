# Migrating Raw SQL to Frappe Query Builder

> **Living document** — updated each time a new migration is done. Patterns and
> edge cases will be added as we encounter them.

## Why Migrate?

1. **PostgreSQL support** — `frappe.db.sql` with hand-written SQL and MariaDB-specific
   syntax breaks on PostgreSQL. The Query Builder emits correct SQL for both engines
   automatically. Every raw SQL block is a Postgres blocker.
2. **Parameterisation** — the builder never interpolates user values into SQL strings;
   all values become bound parameters, eliminating injection risk.
3. **Readability and refactoring safety** — field renames are caught at the Python level
   rather than silently breaking a string.

Reference: https://github.com/frappe/pypika (Frappe's fork, pinned in
`apps/frappe/pyproject.toml`). Frappe-specific extensions live in
`frappe/query_builder/` — `builder.py`, `functions.py`, `utils.py`, `terms.py`.

---

## How the Query Builder is Wired in Frappe

`frappe.qb` is a database-type-aware builder instance (`MariaDB`, `Postgres`, or
`SQLite`), all inheriting from `frappe.query_builder.builder.Base`. On startup,
`patch_all()` monkey-patches:

- `.run(**kwargs)` onto every `QueryBuilder` — executes via `frappe.local.db`
- `.walk()` — returns `(sql_string, params)` without executing
- Aggregate shortcuts: `frappe.qb.max(...)`, `.min(...)`, `.avg(...)`, `.sum(...)`

`DocType(name)` prepends `tab` to the doctype name, validates it, and returns a
pypika `Table`. Attribute and subscript access on any table are monkey-patched to
return `Field(name, table=table)`, giving every column automatic table scope.

---

## Imports

```python
from frappe.query_builder import DocType          # table reference
from frappe.query_builder.functions import IfNull  # IFNULL(expr, fallback)
```

Everything from `pypika` is also re-exported through `frappe.query_builder`, so
`Order`, `Criterion`, `Case`, etc. are available without a separate pypika import.

---

## Basic Select

```python
# Before
frappe.db.sql("select * from `tabNote` where public = 1", as_dict=True)

# After
Note = DocType("Note")
result = frappe.qb.from_(Note).select("*").where(Note.public == 1).run(as_dict=True)
```

`frappe.qb.from_` also accepts a doctype name string directly.

---

## WHERE Conditions

Multiple `.where()` calls are AND-chained:

```python
query = frappe.qb.from_(Note).select("*")
query = query.where(Note.owner == frappe.session.user)
query = query.where(Note.public == 1)
```

**Logical operators inside a single `.where()`:**

```python
# AND → &    OR → |    NOT → ~
query = query.where(
    (Table.from_date.isnull() | (Table.from_date <= date))
    & (Table.to_date.isnull() | (Table.to_date >= date))
)
```

**NULL checks:**

```python
query = query.where(Table.field.isnull())      # IS NULL
query = query.where(Table.field.isnotnull())   # IS NOT NULL
```

**Comparisons:**

```python
Table.field == value      # =
Table.field != value      # !=
Table.field < value       # <
Table.field <= value      # <=
Table.field > value       # >
Table.field >= value      # >=
Table.field.like("A%")    # LIKE
```

---

## Handling Optional Fields (IFNULL + IN)

The common Frappe pattern for optional filter fields — blank/NULL means "applies to
all", a value restricts to that value — maps to `IFNULL(field, '') IN ('', value)`:

```python
from frappe.query_builder.functions import IfNull

# Generic optional field
query = query.where(IfNull(Table.city, "").isin(["", value or ""]))

# Exact-match field (e.g. tax_category)
query = query.where(IfNull(Table.tax_category, "") == (value or ""))
```

Always normalise Python `None` to `""` with `value or ""` — pypika renders `None`
as SQL `NULL` which is technically correct (via IFNULL on the left) but misleading.

---

## Scoped vs Unscoped Field Access

| Expression | Table context | Use when |
|---|---|---|
| `Table.field_name` | ✓ scoped | field name known at write time |
| `Table[key]` | ✓ scoped | field name comes from a variable |
| `Field(key)` | ✗ bare | avoid — ambiguous in queries with a JOIN |

Frappe patches `__getattr__` and `__getitem__` on all table objects so both
`Table.name` and `Table["name"]` return `Field("name", table=Table)` automatically.

---

## ORDER BY, LIMIT, OFFSET

```python
from pypika import Order

query = (
    frappe.qb.from_(Table)
    .select(Table.name, Table.priority)
    .orderby(Table.priority, order=Order.desc)
    .limit(10)
    .offset(20)
)
```

`frappe.qb.desc` and `frappe.qb.asc` are available as shortcuts.

---

## Frappe-Specific Functions

All defined in `frappe/query_builder/functions.py`:

| Import | SQL equivalent | Notes |
|---|---|---|
| `IfNull(field, default)` | `IFNULL(field, default)` | Also aliased as `Ifnull` |
| `GroupConcat` | `GROUP_CONCAT` / `STRING_AGG` | `ImportMapper` — DB-aware |
| `CombineDatetime` | `TIMESTAMP(date, time)` | MariaDB/Postgres variant |
| `DateFormat` | `DATE_FORMAT` / `TO_CHAR` | MariaDB/Postgres variant |
| `Cast_` | `CAST(val AS type)` | Handles MariaDB's VARCHAR quirk |
| `Month`, `MonthName`, `Quarter` | Date part extractors | |

For functions that differ between MariaDB and PostgreSQL, use `ImportMapper`
instead of `if frappe.db.db_type == "mariadb"` branches:

```python
from frappe.query_builder.utils import ImportMapper, db_type_is

MyFunc = ImportMapper({
    db_type_is.MARIADB: MariaDBImpl,
    db_type_is.POSTGRES: PostgresImpl,
})
```

---

## Nested Set / Hierarchy Queries

For hierarchical doctypes (NestedSet), fetch all ancestors using `lft`/`rgt` bounds
and pass the names to `.isin()`:

```python
def get_parent_groups(doctype_name, group_name):
    lft, rgt = frappe.db.get_value(doctype_name, group_name, ["lft", "rgt"])
    Group = DocType(doctype_name)
    return (
        frappe.qb.from_(Group)
        .select(Group.name)
        .where(Group.lft <= lft)   # ancestor.lft <= node.lft
        .where(Group.rgt >= rgt)   # ancestor.rgt >= node.rgt
        .orderby(Group.lft)
        .run(as_dict=True)
    )

# Consuming in a filter
groups = [""] + [d.name for d in get_parent_groups("Customer Group", value)]
query = query.where(IfNull(Table.customer_group, "").isin(groups))
```

---

## Migration Checklist

- [ ] Import `DocType` from `frappe.query_builder`; import functions as needed
- [ ] Replace `` `tabDoctype` `` string with `DocType("Doctype")`
- [ ] Remove all f-string / `.format()` user-input interpolation — qb parameterises automatically
- [ ] Replace `IFNULL(col, val)` with `IfNull(Table.col, val)`
- [ ] Replace `IN ('', val)` with `.isin(["", value or ""])`
- [ ] Replace raw comparisons (`= %s`, `!= %s`) with `== value`, `!= value`
- [ ] Replace `col IS NULL` / `col IS NOT NULL` with `.isnull()` / `.isnotnull()`
- [ ] Use `Table[key]` for dynamic field names, not bare `Field(key)`
- [ ] Remove `frappe.db.escape()` and `cstr()` calls on values — no longer needed
- [ ] Replace `frappe.db.sql("...", params, as_dict=True)` with `.run(as_dict=True)`
- [ ] Normalise Python `None` values with `value or ""` before passing to `.isin()`
- [ ] Replace `if db_type == "mariadb"` branches with `ImportMapper`
- [ ] Verify the query runs correctly on both MariaDB and PostgreSQL
