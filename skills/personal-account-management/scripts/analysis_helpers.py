"""Pure-stdlib computation helpers for the seven-section monthly report.

This module intentionally has NO side effects and NO I/O. It accepts the
already-loaded book dict and the relevant shards, and returns a plain JSON-
serializable snapshot. The caller (an agent) is responsible for rendering
HTML from the snapshot.

Usage from a Hermes agent:

    from hermes_tools import read_file
    import json
    from pathlib import Path

    book = json.loads(read_file(str(Path(DATA_DIR) / "account-book.json")))
    july = json.loads(read_file(str(Path(DATA_DIR) / "transactions" / "2026-07.json")))
    june = json.loads(read_file(str(Path(DATA_DIR) / "transactions" / "2026-06.json")))

    snapshot = compute_monthly_snapshot(
        book=book, window_txns=july["transactions"],
        prior_window_txns=june["transactions"],
        window_start=date(2026, 7, 1), window_end=date(2026, 7, 31),
    )
    print(snapshot["net_worth_minor"], snapshot["july_savings_rate_pct"])

Tests live next to the analysis recipe in
`references/monthly-analysis-report.md`. The reference is the source of
truth; this file just makes the computations executable.
"""

from __future__ import annotations

import calendar
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from balance_history import resolved_account_state, snapshot_summary


def _currency_decimals(currency: str) -> int:
    return 0 if str(currency).upper() == "JPY" else 2


def _to_base_minor(t: dict, base_currency: str, fx_rates: list) -> int | None:
    """Resolve a transaction amount without inventing an undated rate."""
    base_currency = str(base_currency).upper()
    currency = str(t.get("currency") or base_currency).upper()
    base_amount = t.get("base_amount_minor")
    if isinstance(base_amount, int) and str(t.get("base_currency") or "").upper() == base_currency:
        return base_amount
    amount_minor = t.get("amount_minor")
    if not isinstance(amount_minor, int):
        return None
    if currency == base_currency:
        return amount_minor

    rate_id = t.get("exchange_rate_id")
    transaction_date = str(t.get("date") or "")
    candidates = [
        rate
        for rate in fx_rates
        if isinstance(rate, dict)
        and str(rate.get("from") or "").upper() == currency
        and str(rate.get("to") or "").upper() == base_currency
        and (
            (rate_id and rate.get("id") == rate_id)
            or (not rate_id and rate.get("date") == transaction_date)
        )
    ]
    if not candidates:
        return None
    rate = sorted(
        candidates,
        key=lambda item: (bool(item.get("estimate", False)), str(item.get("created_at") or "")),
    )[0]
    try:
        source_major = Decimal(amount_minor) / (Decimal(10) ** _currency_decimals(currency))
        converted_major = source_major * Decimal(str(rate["rate"]))
        target_minor = converted_major * (Decimal(10) ** _currency_decimals(base_currency))
        return int(target_minor.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    except Exception:
        return None


def _acct_delta_window(txns: list, acct_id: str, base_currency: str, fx_rates: list) -> int:
    """Net base-currency delta to one account over a list of transactions."""
    d = 0
    for t in txns:
        amt = _to_base_minor(t, base_currency, fx_rates)
        if amt is None:
            continue
        if t.get("account_id") == acct_id:
            if t["kind"] == "income":
                d += amt
            elif t["kind"] == "expense":
                d -= amt
            elif t["kind"] == "transfer":
                d -= amt
        if t.get("to_account_id") == acct_id and t["kind"] == "transfer":
            d += amt
    return d


def _shift_month_clamped(d: date, months: int) -> date:
    """Shift by whole months, clamping the day to the destination month."""
    month_index = d.year * 12 + (d.month - 1) + months
    year, zero_based_month = divmod(month_index, 12)
    month = zero_based_month + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def _shift_subscription_date(value: date, cadence: str, direction: int) -> date:
    if cadence == "weekly":
        return value + timedelta(days=7 * direction)
    months = {
        "monthly": 1,
        "quarterly": 3,
        "yearly": 12,
    }.get(cadence)
    if months is None:
        raise ValueError(f"unsupported subscription cadence: {cadence}")
    return _shift_month_clamped(value, months * direction)


def _expected_dates_in_window(sub: dict, ws: date, we: date) -> list[date]:
    """Project persisted subscription cadence into an inclusive report window."""
    cadence = str(sub.get("cadence") or "monthly")
    nbd = datetime.strptime(sub["next_billing_date"], "%Y-%m-%d").date()
    if cadence == "custom":
        return [nbd] if ws <= nbd <= we else []

    direction = -1 if nbd > we else 1
    candidate = nbd
    dates: list[date] = []
    for _ in range(2048):
        if ws <= candidate <= we:
            dates.append(candidate)
        if direction > 0 and candidate > we:
            break
        if direction < 0 and candidate < ws:
            break
        next_candidate = _shift_subscription_date(candidate, cadence, direction)
        if next_candidate == candidate:
            break
        candidate = next_candidate
    else:
        raise ValueError("subscription recurrence exceeded the bounded projection window")
    return sorted(set(dates))


def compute_monthly_snapshot(
    book: dict,
    window_txns: list,
    prior_window_txns: list | None,
    window_start: date,
    window_end: date,
) -> dict[str, Any]:
    """Compute the seven-section report snapshot from the loaded ledger.

    All amounts are in minor units (e.g., fen for CNY). The caller is
    responsible for /100 when rendering currency.
    """
    selected_month = window_end.strftime("%Y-%m")
    account_state = resolved_account_state(book, selected_month)
    base = str(account_state.get("base_currency") or book["profile"]["base_currency"]).upper()
    fx = book.get("exchange_rates", [])
    accounts = account_state.get("accounts", []) if account_state["status"] != "unavailable" else []
    budgets = book.get("budgets", [])
    subscriptions = book.get("subscriptions", [])

    # §1 Net worth uses only accounts already denominated in the captured
    # base currency. Foreign balances stay native and unconverted.
    account_summary = snapshot_summary(account_state) if account_state["status"] != "unavailable" else None
    net_worth = account_summary["base_net_worth_minor"] if account_summary else None
    foreign_balances = account_summary["foreign_balances_minor"] if account_summary else {}

    prior_month_end = window_start.replace(day=1).toordinal() - 1
    prior_date = date.fromordinal(prior_month_end)
    prior_state = resolved_account_state(book, prior_date.strftime("%Y-%m"))
    prior_summary = snapshot_summary(prior_state) if prior_state["status"] == "available" else None
    if (
        account_summary is not None
        and prior_summary is not None
        and account_summary["base_currency"] == prior_summary["base_currency"]
    ):
        prior_net_worth = prior_summary["base_net_worth_minor"]
        mom_delta = net_worth - prior_net_worth
    else:
        prior_net_worth = None
        mom_delta = None

    # §2 Cash flow. Unknown conversions are listed and excluded from base
    # subtotals; callers must not present those subtotals as complete totals.
    flow_transactions = [
        transaction
        for transaction in window_txns
        if transaction.get("kind") in {"income", "expense"}
    ]
    converted_window = [
        (transaction, _to_base_minor(transaction, base, fx))
        for transaction in flow_transactions
    ]
    unconverted_transactions = [
        {
            "id": transaction.get("id"),
            "date": transaction.get("date"),
            "kind": transaction.get("kind"),
            "title": transaction.get("title"),
            "amount_minor": transaction.get("amount_minor"),
            "currency": transaction.get("currency"),
        }
        for transaction, amount in converted_window
        if amount is None
    ]
    july_income = sum(
        amount for transaction, amount in converted_window
        if transaction.get("kind") == "income" and amount is not None
    )
    july_expense = sum(
        amount for transaction, amount in converted_window
        if transaction.get("kind") == "expense" and amount is not None
    )
    july_net = july_income - july_expense
    savings_rate = (july_net / july_income * 100) if july_income else 0.0

    # §1 inflection threshold
    threshold = july_income * 0.05 if july_income else 0
    inflections = []
    for transaction, amount in converted_window:
        is_inflection = amount is not None and (
            (july_income > 0 and abs(amount) >= threshold)
            or (july_income == 0 and amount != 0)
        )
        if is_inflection:
            inflections.append(
                {
                    "date": transaction["date"],
                    "kind": transaction["kind"],
                    "title": transaction["title"],
                    "category": transaction["category"],
                    "amount_minor": amount,
                }
            )

    # §3 Category breakdown
    cat_expense: dict[str, int] = defaultdict(int)
    for transaction, amount in converted_window:
        if transaction.get("kind") == "expense" and amount is not None:
            cat_expense[transaction["category"]] += amount
    total_expense = sum(cat_expense.values())
    prev_cat: dict[str, int] = defaultdict(int)
    if prior_window_txns:
        for transaction in prior_window_txns:
            amount = _to_base_minor(transaction, base, fx)
            if transaction.get("kind") == "expense" and amount is not None:
                prev_cat[transaction["category"]] += amount
    top5 = sorted(cat_expense.items(), key=lambda x: -x[1])[:5]
    cat_rows = []
    for cat, amt in top5:
        share = (amt / total_expense * 100) if total_expense else 0
        prev_amt = prev_cat.get(cat, 0)
        if prev_amt == 0:
            delta_pct = None
            delta_label = "new" if amt > 0 else "no_change"
        else:
            delta_pct = (amt - prev_amt) / prev_amt * 100
            delta_label = "changed"
        cat_rows.append(
            {
                "category": cat,
                "amount_minor": amt,
                "share_pct": share,
                "prev_amount_minor": prev_amt,
                "delta_pct": delta_pct,
                "delta_label": delta_label,
            }
        )

    # §4 Budget progress
    budget_results = []
    for b in budgets:
        budget_currency = str(b.get("currency") or base).upper()
        matching = [
            (transaction, _to_base_minor(transaction, budget_currency, fx))
            for transaction in window_txns
            if transaction.get("kind") == "expense"
            and transaction.get("category") == b["category"]
        ]
        spent = sum(amount for _transaction, amount in matching if amount is not None)
        conversion_complete = all(amount is not None for _transaction, amount in matching)
        native_spending: dict[str, int] = defaultdict(int)
        for transaction, amount in matching:
            if amount is None:
                native_spending[str(transaction.get("currency") or budget_currency).upper()] += int(
                    transaction.get("amount_minor") or 0
                )
        pct = (spent / b["limit_minor"] * 100) if b["limit_minor"] else 0
        if pct > 95:
            light = "red"
        elif pct >= 70:
            light = "amber"
        else:
            light = "green"
        budget_results.append(
            {
                "name": b["name"],
                "category": b["category"],
                "currency": budget_currency,
                "limit_minor": b["limit_minor"],
                "spent_minor": spent,
                "pct": pct,
                "light": light,
                "conversion_complete": conversion_complete,
                "native_spending_minor": dict(sorted(native_spending.items())),
            }
        )

    # §5 Subscription audit
    sub_results = []
    for s in subscriptions:
        expected = _expected_dates_in_window(s, window_start, window_end)
        observed = [t for t in window_txns if t.get("subscription_id") == s["id"]]
        if not expected and not observed:
            status, label = "📅", "not yet due"
        elif not expected and observed:
            status, label = "⚠️", "charged earlier than expected"
        elif expected and not observed:
            status, label = "⚠️", "expected but not observed"
        else:
            match = all(
                o["currency"] == s["currency"] and o["amount_minor"] == s["amount_minor"]
                for o in observed
            )
            if match:
                status, label = "✅", "expected & observed on time"
            else:
                status, label = "❌", "amount differs"
        sub_results.append(
            {
                "name": s["name"],
                "cadence": s["cadence"],
                "next_billing_date": s["next_billing_date"],
                "amount_minor": s["amount_minor"],
                "currency": s["currency"],
                "expected_dates": [d.isoformat() for d in expected],
                "observed": [
                    {"date": o["date"], "amount_minor": o["amount_minor"], "currency": o["currency"]}
                    for o in observed
                ],
                "status": status,
                "label": label,
            }
        )

    # §6a Outliers (need ≥ 2 samples in category)
    cat_amounts: dict[str, list[int]] = defaultdict(list)
    for transaction, amount in converted_window:
        if transaction.get("kind") == "expense" and amount is not None:
            cat_amounts[transaction["category"]].append(amount)
    outliers = []
    for cat, amts in cat_amounts.items():
        if len(amts) >= 2:
            amts_sorted = sorted(amts)
            idx = int(0.95 * (len(amts_sorted) - 1))
            p95 = amts_sorted[idx]
            for t in window_txns:
                if t["kind"] == "expense" and t["category"] == cat:
                    a = _to_base_minor(t, base, fx)
                    if a is not None and a > p95:
                        outliers.append(
                            {
                                "date": t["date"],
                                "title": t["title"],
                                "category": cat,
                                "amount_minor": a,
                            }
                        )

    # §6b Duplicate suspects (7-day, same account, same category, title substring, ≤10% diff)
    dupes = []
    window_exp = [t for t in window_txns if t["kind"] == "expense"]
    for i, t1 in enumerate(window_exp):
        d1 = datetime.strptime(t1["date"], "%Y-%m-%d").date()
        for t2 in window_exp[i + 1 :]:
            d2 = datetime.strptime(t2["date"], "%Y-%m-%d").date()
            if abs((d2 - d1).days) > 7:
                continue
            if t1["account_id"] != t2["account_id"] or t1["category"] != t2["category"]:
                continue
            t1l, t2l = t1["title"].lower(), t2["title"].lower()
            if not (t1l in t2l or t2l in t1l):
                continue
            a1 = _to_base_minor(t1, base, fx)
            a2 = _to_base_minor(t2, base, fx)
            if a1 is not None and a2 is not None and a1 > 0 and abs(a1 - a2) / max(a1, a2) <= 0.10:
                dupes.append(
                    {
                        "t1": {"date": t1["date"], "title": t1["title"], "amount_minor": a1},
                        "t2": {"date": t2["date"], "title": t2["title"], "amount_minor": a2},
                        "category": t1["category"],
                        "account": t1["account_id"],
                    }
                )

    # §6c Account drift cannot be proven from recorded-state snapshots. The
    # transactions do not persist whether balance updates were skipped, and
    # direct account replacements are not replayable events.
    drifts: list[dict[str, Any]] = []
    drift_status = "unavailable"
    drift_unavailable_reason = "balance_effect_provenance_incomplete"

    return {
        "account_snapshot": account_state,
        "net_worth_minor": net_worth,
        "prior_net_worth_minor": prior_net_worth,
        "mom_delta_minor": mom_delta,
        "foreign_balances_minor": foreign_balances,
        "july_income_minor": july_income,
        "july_expense_minor": july_expense,
        "july_net_minor": july_net,
        "july_savings_rate_pct": savings_rate,
        "cashflow_conversion_complete": not unconverted_transactions,
        "unconverted_transactions": unconverted_transactions,
        "inflection_threshold_minor": threshold,
        "inflections": inflections,
        "top5": cat_rows,
        "total_expense_minor": total_expense,
        "budget_results": budget_results,
        "sub_results": sub_results,
        "outliers": outliers,
        "dupes": dupes,
        "drifts": drifts,
        "drift_status": drift_status,
        "drift_unavailable_reason": drift_unavailable_reason,
    }
