"""Fixed ledger cases for accounts-code-review. engine.py runs them when plan.json has "ledger": true.

Every submitted s0 document with live GL or payment ledger entries goes through each
case that applies to it, in this order:

    cancel              cancel it: no live rows remain, and the reversal nets every account to zero
    amend               cancel, amend, submit: the amended voucher posts the same rows as the original
    pay_full            pay the outstanding: the outstanding and its payment ledger balance become zero
    pay_partial_cancel  pay half, then cancel the payment: the outstanding follows each step
    return_full         return everything: the return's party GL is the negative of the original's

Each case runs in a savepoint and is rolled back, so it never changes the company's
snapshot. It records its outcome, the ledger rows of the vouchers it touched, and
the rules it breaks, including every new invariant violation. Amounts and rates come
from the document, so the same document gives the same case result on every run.
"""

import itertools
import re

import frappe
from frappe.utils import flt
from pr_ledger import CREATED, DATE, _name_map, _Normalizer, _sort_key, check_invariants, outcome_of

from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry
from erpnext.controllers.sales_and_purchase_return import make_return_doc

PAYABLE = ("Sales Invoice", "Purchase Invoice")
RETURNABLE = ("Sales Invoice", "Purchase Invoice", "Delivery Note", "Purchase Receipt")
PARTY_ACCOUNT = {"Sales Invoice": "debit_to", "Purchase Invoice": "credit_to"}
TOLERANCE = 0.005
# A voucher that a case creates and rolls back has a name from a series that every
# company shares, so its number depends on what ran before. Errors show it masked.
SERIES_NAME = re.compile(r"\b(?:[A-Z]+-)+\d{4}-\d{3,}\b")
_savepoints = itertools.count()


def run_cases(lab, labels):
	"""{"<label>:<case>": {"outcome", "violations", "ledger"}} for each case that applies."""
	out = {}
	for label in labels:
		doctype, name = lab.registry[label]
		if frappe.db.get_value(doctype, name, "docstatus") != 1 or not _has_ledger(doctype, name):
			continue
		for case, fn in CASES:
			result = _run_one(lab, label, fn)
			if result is not None:
				out[f"{label}:{case}"] = result
	return out


def _run_one(lab, label, fn):
	"""Run one case in a savepoint; always roll it back. None when the case does not apply."""
	savepoint = f"ledger_case_{next(_savepoints)}"
	frappe.db.savepoint(savepoint)
	registry, owners, outcomes = dict(lab.registry), dict(lab.owners), dict(lab.outcomes)
	created = {doctype: list(names) for doctype, names in CREATED.items()}
	company = lab.ctx.company
	before = set(check_invariants(company))
	result = error = None
	try:
		doc = frappe.get_doc(*lab.registry[label])
		result = fn(lab, doc)
		if result is None:
			return None
		touched, violations = result
		names = {**_name_map(lab), **{d.name: f"<{role}>" for role, d in touched.items()}}
		norm = _Normalizer(names, company, lab.ctx.abbr)
		new = sorted(set(check_invariants(company)) - before)
		result = {
			"outcome": "ok",
			"violations": sorted([norm(v) for v in violations] + [f"invariant: {norm(v)}" for v in new]),
			"ledger": {f"<{role}>": _ledger_rows(d.doctype, d.name, norm) for role, d in sorted(touched.items())},
		}
	except Exception as e:
		error = outcome_of(e)
	finally:
		frappe.db.rollback(save_point=savepoint)
		lab.registry, lab.owners, lab.outcomes = registry, owners, outcomes
		CREATED.clear()
		CREATED.update(created)
		frappe.local.message_log = []
	if error is None:
		return result
	norm = _Normalizer(_name_map(lab), company, lab.ctx.abbr)  # after the rollback: names that still exist
	return {"outcome": SERIES_NAME.sub("<new>", norm(error)), "violations": [], "ledger": {}}


# ---------------------------------------------------------------- cases


def case_cancel(lab, doc):
	doc.cancel()
	return {"self": doc}, _cancelled(doc)


def case_amend(lab, doc):
	original = _posting(doc.doctype, doc.name)
	doc.cancel()
	amended = frappe.copy_doc(doc)
	amended.amended_from = doc.name
	amended.docstatus = 0
	amended.insert()
	amended.submit()
	violations = _cancelled(doc)
	if _posting(amended.doctype, amended.name) != original:
		violations.append("the amended voucher posts different GL or payment ledger rows than the original")
	return {"self": doc, "amended": amended}, violations


def case_pay_full(lab, doc):
	if doc.doctype not in PAYABLE or abs(flt(doc.outstanding_amount)) < TOLERANCE:
		return None
	payment = _pay(lab, doc, None)
	doc.reload()
	violations = []
	if abs(flt(doc.outstanding_amount)) > TOLERANCE:
		violations.append(f"outstanding is {flt(doc.outstanding_amount, 2)} after a full payment")
	balance = _ple_balance(doc)
	if abs(balance) > TOLERANCE:
		violations.append(f"payment ledger balance is {balance} after a full payment")
	return {"self": doc, "payment": payment}, violations


def case_pay_partial_cancel(lab, doc):
	if doc.doctype not in PAYABLE or abs(flt(doc.outstanding_amount)) < TOLERANCE:
		return None
	start = flt(doc.outstanding_amount)
	half = flt(start / 2, doc.precision("outstanding_amount"))
	payment = _pay(lab, doc, half)
	doc.reload()
	violations = []
	if abs(flt(doc.outstanding_amount) - (start - half)) > TOLERANCE:
		violations.append(
			f"outstanding is {flt(doc.outstanding_amount, 2)} after paying {half} of {start}; it should be {flt(start - half, 2)}"
		)
	payment.cancel()
	doc.reload()
	if abs(flt(doc.outstanding_amount) - start) > TOLERANCE:
		violations.append(
			f"outstanding is {flt(doc.outstanding_amount, 2)} after the payment is cancelled; it should be {start}"
		)
	return {"self": doc, "payment": payment}, violations + _cancelled(payment)


def case_return_full(lab, doc):
	if doc.doctype not in RETURNABLE or doc.get("is_return"):
		return None
	ret = make_return_doc(doc.doctype, doc.name)
	ret.posting_date = DATE
	ret.set_posting_time = 1
	ret.insert()
	ret.submit()
	violations = []
	field = PARTY_ACCOUNT.get(doc.doctype)
	if field:
		account, party = doc.get(field), doc.get("customer") or doc.get("supplier")
		original, returned = _party_net(doc, account, party), _party_net(ret, account, party)
		if abs(original + returned) > TOLERANCE:
			violations.append(f"a full return posts {returned} to the party account against {original} on the original")
	return {"self": doc, "return": ret}, violations


CASES = [
	("cancel", case_cancel),
	("amend", case_amend),
	("pay_full", case_pay_full),
	("pay_partial_cancel", case_pay_partial_cancel),
	("return_full", case_return_full),
]


# ---------------------------------------------------------------- helpers


def _pay(lab, doc, amount):
	"""A payment at the document's own rate, so no exchange gain or loss and no rate lookup."""
	pe = get_payment_entry(doc.doctype, doc.name, party_amount=amount, bank_account=lab.ctx.bank, reference_date=DATE)
	pe.posting_date = pe.reference_date = DATE
	pe.reference_no = "ledger-case"
	if amount is not None:
		pe.references[0].allocated_amount = amount
	rate = flt(doc.get("conversion_rate")) or 1
	if pe.paid_from_account_currency != pe.paid_to_account_currency:
		if pe.payment_type == "Receive":
			pe.source_exchange_rate = rate
			pe.received_amount = pe.base_received_amount = flt(pe.paid_amount * rate, 2)
		else:
			pe.target_exchange_rate = rate
			pe.paid_amount = pe.base_paid_amount = flt(pe.received_amount * rate, 2)
	pe.insert()
	pe.submit()
	return pe


def _has_ledger(doctype, name):
	return any(
		frappe.db.exists(table, {"voucher_type": doctype, "voucher_no": name})
		for table in ("GL Entry", "Payment Ledger Entry")
	)


def _cancelled(doc):
	"""Rules after a cancel: no live rows, and original plus reversal net to zero per account."""
	violations = []
	if frappe.db.exists("GL Entry", {"voucher_type": doc.doctype, "voucher_no": doc.name, "is_cancelled": 0}):
		violations.append(f"live GL Entry rows remain after {doc.doctype} is cancelled")
	if frappe.db.exists(
		"Payment Ledger Entry", {"voucher_type": doc.doctype, "voucher_no": doc.name, "delinked": 0}
	):
		violations.append(f"live Payment Ledger Entry rows remain after {doc.doctype} is cancelled")
	for row in frappe.db.sql(
		"""select account, sum(debit) - sum(credit) net from `tabGL Entry`
		where voucher_type=%s and voucher_no=%s group by account""",
		(doc.doctype, doc.name),
		as_dict=1,
	):
		if abs(flt(row.net)) > TOLERANCE:
			violations.append(f"cancel leaves {flt(row.net, 2)} on {row.account}")
	return violations


def _posting(doctype, name):
	"""Live GL and payment ledger rows of a voucher, without names, for comparing two vouchers."""
	gl = frappe.get_all(
		"GL Entry",
		{"voucher_type": doctype, "voucher_no": name, "is_cancelled": 0},
		["account", "party", "debit", "credit", "cost_center"],
	)
	ple = frappe.get_all(
		"Payment Ledger Entry",
		{"voucher_type": doctype, "voucher_no": name, "delinked": 0},
		["account", "party", "amount", "amount_in_account_currency"],
	)
	rows = lambda rs: sorted(_sort_key({k: flt(v, 2) if isinstance(v, float) else v for k, v in r.items()}) for r in rs)  # noqa: E731
	return {"gl": rows(gl), "ple": rows(ple)}


def _ple_balance(doc):
	return flt(
		frappe.db.sql(
			"""select coalesce(sum(amount_in_account_currency), 0) from `tabPayment Ledger Entry`
			where against_voucher_type=%s and against_voucher_no=%s and delinked=0""",
			(doc.doctype, doc.name),
		)[0][0],
		2,
	)


def _party_net(doc, account, party):
	return flt(
		frappe.db.sql(
			"""select coalesce(sum(debit) - sum(credit), 0) from `tabGL Entry`
			where voucher_type=%s and voucher_no=%s and account=%s and party=%s and is_cancelled=0""",
			(doc.doctype, doc.name, account, party),
		)[0][0],
		2,
	)


def _ledger_rows(doctype, name, norm):
	gl = frappe.get_all(
		"GL Entry",
		{"voucher_type": doctype, "voucher_no": name},
		["account", "party", "debit", "credit", "against_voucher", "is_cancelled"],
	)
	ple = frappe.get_all(
		"Payment Ledger Entry",
		{"voucher_type": doctype, "voucher_no": name},
		["account", "party", "amount", "against_voucher_no", "delinked"],
	)
	return {
		"gl": sorted((norm(r) for r in gl), key=_sort_key),
		"ple": sorted((norm(r) for r in ple), key=_sort_key),
	}
