"""Requirement scenarios for this review. engine.py runs them after the library, in every company.

lab.ctx: company, abbr, currency, foreign_currency, receivable, payable, income, expense,
         cash, bank, tax, receivable_eur (in foreign_currency), cost_center, warehouse,
         customer, customer_eur, supplier, service_item, stock_item.
         The variant's settings are already applied.
lab.reg(label, doc)       register a document; its snapshot key is the label (no dots).
lab.get(label)            the registered document.
lab.attempt(label, fn)    run fn; record "ok" or the error under outcomes.<label>.
                          A refusal by a validation is recorded as "blocked: <error>".

Post on DATE (or day(n)). Pass every account, currency and conversion_rate.
Never read today's date, a random value, or a site record outside lab.ctx.

A risk scenario (risks.json) builds the risk's state through the standard document API only:
no db_set, ignore_validate, flags or SQL. The run reads its build outcome: "ok" means a user
can reach the state, "blocked: ..." means a validation refuses it.
"""

import frappe
from library import scenario
from pr_ledger import DATE, day


def s0_build(lab):
	"""The requirement's Repro, with the reporter's data. One function per reported case."""
	raise NotImplementedError("write the Repro")


def s0_legacy(lab):
	"""What happens later to the Repro's documents (cancel, return, pay), if the requirement involves it."""


# Ids must not clash with library.SCENARIOS. The title appears in the report.
def r1_build(lab):
	"""Risk r1: try to reach its state the way a user does. One scenario per path."""
	raise NotImplementedError("build the state of risk r1")


SCENARIOS = [
	scenario(
		"s0", "<one line: the reported case, in the reporter's words>", ["requirement"], s0_build, s0_legacy
	),
	scenario("r1", "<risk r1's title>", ["risk"], r1_build, lambda lab: None),
]


# Fields to add to the snapshot of each document, beyond pr_ledger.DOC_FIELDS: the new
# or changed fields of a feature, so assertions and the base/PR comparison can read them.
DOC_FIELDS = {}  # e.g. {"Sales Invoice": ["discount_account"]}


def reports(ctx):
	"""Extra reports from the blast radius: {label: (report_name, filters)}. Use DATE-based filters."""
	return {}
