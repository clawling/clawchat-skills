#!/usr/bin/env python3
"""Personal account ledger helper for the Hermes personal-account-management skill."""

from __future__ import annotations

import argparse
import calendar
from contextlib import contextmanager
import hashlib
import json
import os
import re
import shutil
import sys
import time
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any

try:
    import fcntl
except ImportError:  # pragma: no cover - non-POSIX fallback
    fcntl = None

try:
    import msvcrt
except ImportError:  # pragma: no cover - non-Windows fallback
    msvcrt = None

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - Python without zoneinfo
    ZoneInfo = None

from balance_history import (
    SNAPSHOT_FIELD,
    STATIC_SCHEMA_VERSION,
    TRANSACTION_SHARD_SCHEMA_VERSION,
    append_historical_revision,
    capture_current_snapshot,
    natural_month,
    resolved_snapshot,
    snapshot_summary,
    validate_balance_snapshots,
    validate_snapshot_accounts,
)

TZ = timezone(timedelta(hours=8))
MAX_SOURCE_TEXT_CHARS = 1200
LARGE_TRANSACTION_BASE_MINOR = 1_000_000  # ¥10,000 by default in base-currency minor units
_LOADED_UPDATED_AT: dict[str, str | None] = {}
_LOADED_STATIC_SHA256: dict[str, str] = {}
_LOADED_TRANSACTION_SHA256: dict[str, dict[str, str]] = {}
_MISSING = object()


class UnsupportedStaticSchema(ValueError):
    pass


# Static top-level fields that live in account-book.json (non-transactional state).
# Transactions are split off into transactions/YYYY-MM.json and merged on read.
STATIC_TOP_LEVEL = (
    "schema_version",
    "profile",
    "accounts",
    "categories",
    "budgets",
    "subscriptions",
    "exchange_rates",
    SNAPSHOT_FIELD,
    "metadata",
)
# `transactions` is intentionally not in STATIC_TOP_LEVEL — it is split per month.

# YYYY-MM file pattern for transaction shards.
_MONTH_FILE_RE = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])\.json$")


def _static_book_path(path: Path) -> Path:
    """The single static book file (accounts/categories/budgets/subscriptions/etc)."""
    return expand_path(path)


def _transactions_dir(path: Path) -> Path:
    """Directory holding per-month transaction shards: transactions/YYYY-MM.json."""
    return expand_path(path).parent / "transactions"


def _month_file_path(static_path: Path, year: int, month: int) -> Path:
    return _transactions_dir(static_path) / f"{year:04d}-{month:02d}.json"


def _list_month_files(static_path: Path) -> list[Path]:
    """List all YYYY-MM.json shard files under transactions/, sorted ascending."""
    d = _transactions_dir(static_path)
    if not d.exists():
        return []
    out: list[tuple[int, int, Path]] = []
    for entry in d.iterdir():
        if not entry.is_file():
            continue
        m = _MONTH_FILE_RE.match(entry.name)
        if not m:
            continue
        out.append((int(m.group(1)), int(m.group(2)), entry))
    out.sort(key=lambda t: (t[0], t[1]))
    return [p for _, _, p in out]


def _tx_date_to_month_key(date_str: str) -> tuple[int, int] | None:
    """Extract (year, month) only from canonical YYYY-MM-DD text."""
    if not isinstance(date_str, str) or re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_str) is None:
        return None
    try:
        parsed = date.fromisoformat(date_str)
    except ValueError:
        return None
    return parsed.year, parsed.month
REQUIRED_TOP_LEVEL = (
    "schema_version",
    "profile",
    "accounts",
    "categories",
    "budgets",
    "transactions",
    "subscriptions",
    "exchange_rates",
    SNAPSHOT_FIELD,
    "metadata",
)
LIST_FIELDS = (
    "accounts",
    "categories",
    "budgets",
    "transactions",
    "subscriptions",
    "exchange_rates",
    SNAPSHOT_FIELD,
)


def now_iso(tzinfo=TZ) -> str:
    return datetime.now(tzinfo).isoformat(timespec="seconds")


def today_iso(tzinfo=TZ) -> str:
    return datetime.now(tzinfo).date().isoformat()


def book_timezone(book: dict[str, Any] | None) -> timezone:
    name = ((book or {}).get("profile", {}) or {}).get("timezone")
    if name and ZoneInfo is not None:
        try:
            return ZoneInfo(str(name))
        except Exception:
            pass
    return TZ


def expand_path(path: Path) -> Path:
    return Path(os.path.expandvars(str(path))).expanduser()


def currency_decimals(currency: str) -> int:
    return 0 if currency.upper() == "JPY" else 2


def parse_date(value: str | None, tzinfo=TZ) -> str:
    if not value or value == "today":
        return today_iso(tzinfo)
    if value == "yesterday":
        return (datetime.now(tzinfo).date() - timedelta(days=1)).isoformat()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) is None:
        raise ValueError("date must use YYYY-MM-DD")
    return date.fromisoformat(value).isoformat()


def parse_amount_minor(value: str | int | float | Decimal, currency: str) -> int:
    text = str(value).replace(",", "").strip()
    try:
        amount = Decimal(text)
    except InvalidOperation as exc:
        raise ValueError(f"invalid amount: {value}") from exc
    decimals = currency_decimals(currency)
    scale = Decimal(10) ** decimals
    return int((amount * scale).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def require_positive_minor(amount_minor: int, *, field: str) -> int:
    if amount_minor <= 0:
        raise ValueError(f"{field} must be greater than zero")
    return amount_minor


def require_nonnegative_minor(amount_minor: int, *, field: str) -> int:
    if amount_minor < 0:
        raise ValueError(f"{field} must be zero or greater")
    return amount_minor


def parse_positive_amount_minor(value: str | int | float | Decimal, currency: str, *, field: str = "amount") -> int:
    return require_positive_minor(parse_amount_minor(value, currency), field=field)


def compact_source_text(text: str) -> str:
    text = str(text or "").strip()
    if len(text) <= MAX_SOURCE_TEXT_CHARS:
        return text
    return text[:MAX_SOURCE_TEXT_CHARS] + "…[truncated]"


def money_label(amount_minor: int | None, currency: str = "CNY", signed: bool = False) -> str:
    if amount_minor is None:
        return "Not estimated"
    decimals = currency_decimals(currency)
    divisor = 10 ** decimals
    amount = Decimal(amount_minor) / Decimal(divisor)
    sign = ""
    if amount < 0:
        sign = "-"
    elif signed:
        sign = "+"
    abs_amount = abs(amount)
    body = f"{abs_amount:,.0f}" if abs_amount == abs_amount.to_integral_value() else f"{abs_amount:,.2f}"
    if currency.upper() == "CNY":
        return f"{sign}¥{body}"
    return f"{sign}{currency.upper()} {body}"


def slugify(text: str) -> str:
    clean = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "-", text).strip("-")
    return clean[:48] or "item"


def default_book() -> dict[str, Any]:
    timestamp = now_iso()
    return {
        "schema_version": STATIC_SCHEMA_VERSION,
        "profile": {"base_currency": "CNY", "timezone": "Asia/Shanghai", "month_start_day": 1},
        "accounts": [],
        "categories": [],
        "budgets": [],
        "transactions": [],
        "subscriptions": [],
        "exchange_rates": [],
        SNAPSHOT_FIELD: [],
        "metadata": {"created_at": timestamp, "updated_at": timestamp},
    }


def load_book(path: Path) -> dict[str, Any]:
    static_path = _static_book_path(path)
    if not static_path.exists():
        raise FileNotFoundError(f"book not found: {static_path}")
    static_bytes = static_path.read_bytes()
    book = json.loads(static_bytes.decode("utf-8"))
    if not isinstance(book, dict):
        raise ValueError(f"book root is not an object: {static_path}")
    if (
        type(book.get("schema_version")) is not int
        or book.get("schema_version") != STATIC_SCHEMA_VERSION
    ):
        raise UnsupportedStaticSchema(
            f"static schema version {STATIC_SCHEMA_VERSION} is required"
        )

    _LOADED_UPDATED_AT[str(static_path)] = (book.get("metadata", {}) or {}).get("updated_at")
    _LOADED_STATIC_SHA256[str(static_path)] = hashlib.sha256(static_bytes).hexdigest()
    transactions: list[dict[str, Any]] = []
    shard_digests: dict[str, str] = {}
    transaction_dir = _transactions_dir(static_path)
    shards = sorted(transaction_dir.glob("*.json")) if transaction_dir.exists() else []
    for shard in shards:
        if _MONTH_FILE_RE.fullmatch(shard.name) is None:
            raise ValueError(f"{shard.name} filename must match YYYY-MM.json with a valid month")
        shard_bytes = shard.read_bytes()
        shard_data = json.loads(shard_bytes.decode("utf-8"))
        if not isinstance(shard_data, dict):
            raise ValueError(f"{shard.name} must be a schema-v2 transaction-shard object")
        if (
            type(shard_data.get("schema_version")) is not int
            or shard_data.get("schema_version") != TRANSACTION_SHARD_SCHEMA_VERSION
        ):
            raise ValueError(
                f"{shard.name}.schema_version must be {TRANSACTION_SHARD_SCHEMA_VERSION}"
            )
        if shard_data.get("month") != shard.stem:
            raise ValueError(f"{shard.name}.month must be {shard.stem}")
        if not isinstance(shard_data.get("metadata"), dict):
            raise ValueError(f"{shard.name}.metadata must be an object")
        rows = shard_data.get("transactions")
        if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
            raise ValueError(f"{shard.name}.transactions must be an array of objects")
        for index, row in enumerate(rows):
            transaction_date = row.get("date")
            transaction_key = _tx_date_to_month_key(transaction_date)
            if transaction_key is None:
                raise ValueError(
                    f"{shard.name}.transactions[{index}].date must use YYYY-MM-DD"
                )
            transaction_month = f"{transaction_key[0]:04d}-{transaction_key[1]:02d}"
            if transaction_month != shard.stem:
                raise ValueError(
                    f"{shard.name}.transactions[{index}].date must be within {shard.stem}"
                )
        _LOADED_UPDATED_AT[str(shard)] = (
            shard_data.get("metadata", {}) or {}
        ).get("updated_at")
        shard_digests[shard.name] = hashlib.sha256(shard_bytes).hexdigest()
        transactions.extend(rows)
    _LOADED_TRANSACTION_SHA256[str(static_path)] = shard_digests
    book["transactions"] = transactions
    return book


def _book_lock_path(path: Path) -> Path:
    return path.with_name(path.name + ".lock")


def _read_disk_updated_at(path: Path) -> str | None:
    if not path.exists():
        return None
    try:
        current = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if isinstance(current, dict):
        return (current.get("metadata", {}) or {}).get("updated_at")
    return None


def _atomic_write_json(target: Path, payload: dict[str, Any]) -> str:
    """Write JSON atomically and return the exact committed-byte digest."""
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    return _atomic_write_bytes(target, text.encode("utf-8"))


def _check_concurrent_modification(static_path: Path) -> None:
    """Raise if exact static or transaction-shard bytes drifted after load."""
    key = str(static_path)
    expected = _LOADED_STATIC_SHA256.get(key, _MISSING)
    if expected is not _MISSING:
        try:
            current = hashlib.sha256(static_path.read_bytes()).hexdigest()
        except OSError as exc:
            raise RuntimeError("book changed on disk since it was loaded; reload and retry") from exc
        if current != expected:
            raise RuntimeError("book changed on disk since it was loaded; reload and retry")

    expected_shards = _LOADED_TRANSACTION_SHA256.get(key, _MISSING)
    if expected_shards is not _MISSING:
        try:
            current_shards = _transaction_shard_digests(static_path)
        except OSError as exc:
            raise RuntimeError(
                "transaction shards changed on disk since the book was loaded; reload and retry"
            ) from exc
        if current_shards != expected_shards:
            raise RuntimeError(
                "transaction shards changed on disk since the book was loaded; reload and retry"
            )


def save_book(
    path: Path,
    book: dict[str, Any],
    *,
    _lock_held: bool = False,
) -> None:
    """Persist shards plus static state, rolling shards back if static commit fails."""
    static_path = _static_book_path(path)
    static_path.parent.mkdir(parents=True, exist_ok=True)
    if not _lock_held:
        with _exclusive_book_lock(static_path):
            save_book(path, book, _lock_held=True)
        return

    _check_concurrent_modification(static_path)
    tzinfo = book_timezone(book)
    timestamp = now_iso(tzinfo)
    static_book = _build_static_payload(book, updated_at=timestamp)
    original_shards = {
        shard: shard.read_bytes() for shard in _list_month_files(static_path)
    }

    txs = book.get("transactions", []) or []
    by_month: dict[tuple[int, int], list[dict[str, Any]]] = {}
    for tx in txs:
        if not isinstance(tx, dict):
            continue
        key = _tx_date_to_month_key(tx.get("date", ""))
        if key is None:
            raise ValueError("transaction date must use YYYY-MM-DD")
        by_month.setdefault(key, []).append(tx)
    for key in by_month:
        by_month[key].sort(key=lambda item: (item.get("date", ""), item.get("id", "")))

    committed_shard_digests: dict[str, str] = {}
    try:
        tx_dir = _transactions_dir(static_path)
        tx_dir.mkdir(parents=True, exist_ok=True)
        written_months: set[tuple[int, int]] = set()
        for (year, month), shard_txs in by_month.items():
            shard_path = _month_file_path(static_path, year, month)
            shard_payload = {
                "schema_version": TRANSACTION_SHARD_SCHEMA_VERSION,
                "month": f"{year:04d}-{month:02d}",
                "metadata": {"updated_at": timestamp},
                "transactions": shard_txs,
            }
            shard_digest = _atomic_write_json(shard_path, shard_payload)
            committed_shard_digests[shard_path.name] = shard_digest
            _LOADED_UPDATED_AT[str(shard_path)] = timestamp
            written_months.add((year, month))

        for stale in _list_month_files(static_path):
            match = _MONTH_FILE_RE.match(stale.name)
            if match:
                key = (int(match.group(1)), int(match.group(2)))
                if key not in written_months:
                    stale.unlink()
                    _LOADED_UPDATED_AT.pop(str(stale), None)

        static_digest = _atomic_write_json(static_path, static_book)
    except Exception:
        _restore_transaction_shards(static_path, original_shards)
        raise

    book["metadata"] = copy_json(static_book["metadata"])
    _LOADED_UPDATED_AT[str(static_path)] = timestamp
    _LOADED_STATIC_SHA256[str(static_path)] = static_digest
    _LOADED_TRANSACTION_SHA256[str(static_path)] = committed_shard_digests


def runtime_dirs(book_path: Path) -> dict[str, Path]:
    root = expand_path(book_path).parent
    return {"root": root, "receipts": root / "receipts"}


def ensure_runtime_dirs(book_path: Path) -> None:
    for path in runtime_dirs(book_path).values():
        path.mkdir(parents=True, exist_ok=True)


def load_template(path: Path | None) -> dict[str, Any]:
    if path is None:
        return default_book()
    expanded = expand_path(path)
    data = json.loads(expanded.read_text(encoding="utf-8"))
    errors = validate_book_data(data)
    if errors:
        raise ValueError("template is not a valid account book: " + "; ".join(errors))
    return data


def validate_book_data(book: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(book, dict):
        return ["book must be a JSON object"]
    for key in REQUIRED_TOP_LEVEL:
        if key not in book:
            errors.append(f"missing top-level field: {key}")
    version = book.get("schema_version")
    if type(version) is not int:
        errors.append("schema_version must be an integer")
    elif version != STATIC_SCHEMA_VERSION:
        errors.append(f"schema_version must be {STATIC_SCHEMA_VERSION}")
    if SNAPSHOT_FIELD in book:
        errors.extend(validate_balance_snapshots(book.get(SNAPSHOT_FIELD)))
    profile = book.get("profile")
    if not isinstance(profile, dict):
        errors.append("profile must be an object")
        profile = {}
    else:
        if not profile.get("base_currency"):
            errors.append("profile.base_currency is required")
        if not profile.get("timezone"):
            errors.append("profile.timezone is required")
        elif ZoneInfo is not None:
            try:
                ZoneInfo(str(profile["timezone"]))
            except Exception:
                errors.append("profile.timezone must be a valid IANA timezone")
        day = profile.get("month_start_day", 1)
        if not isinstance(day, int) or not 1 <= day <= 28:
            errors.append("profile.month_start_day must be an integer from 1 to 28")
    for key in LIST_FIELDS:
        if key in book and not isinstance(book[key], list):
            errors.append(f"{key} must be an array")
    if not isinstance(book.get("metadata"), dict):
        errors.append("metadata must be an object")

    accounts = [a for a in book.get("accounts", []) if isinstance(a, dict)] if isinstance(book.get("accounts"), list) else []
    account_ids = {a.get("id") for a in accounts}
    account_names = {a.get("name") for a in accounts}
    category_rows = [c for c in book.get("categories", []) if isinstance(c, dict) and c.get("active", True)] if isinstance(book.get("categories"), list) else []
    category_names = {c.get("name") for c in category_rows} | {c.get("id") for c in category_rows}
    subscription_ids = {sub.get("id") for sub in book.get("subscriptions", []) if isinstance(sub, dict)} if isinstance(book.get("subscriptions"), list) else set()
    rate_ids = {rate.get("id") for rate in book.get("exchange_rates", []) if isinstance(rate, dict)} if isinstance(book.get("exchange_rates"), list) else set()

    for index, account in enumerate(accounts):
        for key in ("id", "name", "type", "currency", "balance_minor"):
            if key not in account:
                errors.append(f"accounts[{index}] missing {key}")
        if account.get("type") not in {"asset", "liability", "receivable"}:
            errors.append(f"accounts[{index}].type invalid")
        if type(account.get("balance_minor")) is not int:
            errors.append(f"accounts[{index}].balance_minor must be integer minor units")
        elif account["balance_minor"] < 0:
            errors.append(f"accounts[{index}].balance_minor must be zero or greater")

    transactions = book.get("transactions", []) if isinstance(book.get("transactions"), list) else []
    seen_tx_ids: set[str] = set()
    for index, tx in enumerate(transactions):
        if not isinstance(tx, dict):
            errors.append(f"transactions[{index}] must be an object")
            continue
        for key in ("id", "date", "kind", "title", "category", "amount_minor", "currency", "source"):
            if key not in tx:
                errors.append(f"transactions[{index}] missing {key}")
        tx_id = tx.get("id")
        if tx_id in seen_tx_ids:
            errors.append(f"transactions[{index}] duplicate id: {tx_id}")
        if isinstance(tx_id, str):
            seen_tx_ids.add(tx_id)
        if tx.get("kind") not in {"income", "expense", "transfer"}:
            errors.append(f"transactions[{index}].kind invalid")
        if not isinstance(tx.get("amount_minor"), int) or tx.get("amount_minor", 0) <= 0:
            errors.append(f"transactions[{index}].amount_minor must be a positive integer")
        transaction_date = tx.get("date")
        if (
            not isinstance(transaction_date, str)
            or re.fullmatch(r"\d{4}-\d{2}-\d{2}", transaction_date) is None
        ):
            errors.append(f"transactions[{index}].date must be ISO YYYY-MM-DD")
        else:
            try:
                date.fromisoformat(transaction_date)
            except ValueError:
                errors.append(f"transactions[{index}].date must be ISO YYYY-MM-DD")
        account_id = tx.get("account_id")
        if account_id and account_id not in account_ids:
            errors.append(f"transactions[{index}].account_id not found: {account_id}")
        if tx.get("kind") == "transfer":
            if not tx.get("to_account_id"):
                errors.append(f"transactions[{index}] transfer missing to_account_id")
            elif tx.get("to_account_id") not in account_ids:
                errors.append(f"transactions[{index}].to_account_id not found: {tx.get('to_account_id')}")
        if category_names and tx.get("category") not in category_names:
            errors.append(f"transactions[{index}].category not found: {tx.get('category')}")
        if tx.get("subscription_id") and tx.get("subscription_id") not in subscription_ids:
            errors.append(f"transactions[{index}].subscription_id not found: {tx.get('subscription_id')}")
        if tx.get("exchange_rate_id") and tx.get("exchange_rate_id") not in rate_ids:
            errors.append(f"transactions[{index}].exchange_rate_id not found: {tx.get('exchange_rate_id')}")
        if str(tx.get("currency", "")).upper() != str(profile.get("base_currency", "CNY")).upper() and tx.get("base_amount_minor") is None and not tx.get("needs_review"):
            errors.append(f"transactions[{index}] foreign-currency transaction missing base_amount_minor or review flag")

    for index, budget in enumerate(book.get("budgets", []) if isinstance(book.get("budgets"), list) else []):
        if not isinstance(budget, dict):
            continue
        if not isinstance(budget.get("limit_minor"), int) or budget.get("limit_minor", 0) <= 0:
            errors.append(f"budgets[{index}].limit_minor must be a positive integer")
        if category_names and budget.get("category") not in category_names:
            errors.append(f"budgets[{index}].category not found: {budget.get('category')}")

    for index, sub in enumerate(book.get("subscriptions", []) if isinstance(book.get("subscriptions"), list) else []):
        if not isinstance(sub, dict):
            continue
        if not isinstance(sub.get("amount_minor"), int) or sub.get("amount_minor", 0) <= 0:
            errors.append(f"subscriptions[{index}].amount_minor must be a positive integer")
        if sub.get("payment_account_id") and sub.get("payment_account_id") not in account_ids:
            errors.append(f"subscriptions[{index}].payment_account_id not found: {sub.get('payment_account_id')}")
        if sub.get("cadence") == "custom" and not sub.get("next_billing_date"):
            errors.append(f"subscriptions[{index}] custom cadence requires next_billing_date")

    for index, rate in enumerate(book.get("exchange_rates", []) if isinstance(book.get("exchange_rates"), list) else []):
        if not isinstance(rate, dict):
            continue
        try:
            if Decimal(str(rate.get("rate"))) <= 0:
                errors.append(f"exchange_rates[{index}].rate must be positive")
        except Exception:
            errors.append(f"exchange_rates[{index}].rate must be numeric")
    return errors

def print_json(data: Any) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))


def error_result(message: str, *, code: str = "error") -> dict[str, str]:
    return {"status": "error", "code": code, "error": message}


def cmd_init(args: argparse.Namespace) -> int:
    book_path = expand_path(args.book)
    backup_path: Path | None = None
    with _exclusive_book_lock(book_path):
        if book_path.exists() and not args.force:
            print_json(error_result(f"book already exists: {book_path}", code="exists"))
            return 1
        if book_path.exists() and args.force:
            stamp = datetime.now(TZ).strftime("%Y%m%d%H%M%S")
            backup_path = book_path.with_name(f"{book_path.name}.bak-{stamp}")
            suffix = 2
            while backup_path.exists():
                backup_path = book_path.with_name(f"{book_path.name}.bak-{stamp}-{suffix}")
                suffix += 1
            backup_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(book_path, backup_path)
        try:
            book = load_template(args.template)
        except Exception as exc:
            print_json(error_result(str(exc), code="invalid_template"))
            return 1
        timestamp = now_iso(book_timezone(book))
        book["schema_version"] = STATIC_SCHEMA_VERSION
        book.setdefault(SNAPSHOT_FIELD, [])
        book["metadata"] = {
            **book.get("metadata", {}),
            "created_at": timestamp,
            "updated_at": timestamp,
        }
        ensure_runtime_dirs(book_path)
        static_key = str(book_path)
        _LOADED_STATIC_SHA256.pop(static_key, None)
        _LOADED_TRANSACTION_SHA256.pop(static_key, None)
        _LOADED_UPDATED_AT.pop(static_key, None)
        save_book(book_path, book, _lock_held=True)
    payload = {
        "status": "initialized",
        "book": str(book_path),
        "receipts": str(runtime_dirs(book_path)["receipts"]),
    }
    if backup_path is not None:
        payload["backup"] = str(backup_path)
    print_json(payload)
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    try:
        book = _load_book_for_validation(args.book)
    except FileNotFoundError as exc:
        print_json(error_result(str(exc), code="missing_book"))
        return 1
    except json.JSONDecodeError as exc:
        print_json(error_result(f"invalid JSON: {exc}", code="invalid_json"))
        return 1
    except ValueError as exc:
        print_json(error_result(str(exc), code="invalid_book"))
        return 1
    errors = validate_book_data(book)
    errors.extend(validate_transaction_shards(args.book))
    if errors:
        print_json({"status": "invalid", "errors": errors})
        return 1
    payload: dict[str, Any] = {
        "status": "valid",
        "book": str(expand_path(args.book)),
        "schema_version": book.get("schema_version"),
        "transaction_shard_schema_version": TRANSACTION_SHARD_SCHEMA_VERSION,
    }
    print_json(payload)
    return 0


def find_account(book: dict[str, Any], identifier: str | None) -> dict[str, Any] | None:
    if not identifier:
        return None
    for account in book.get("accounts", []):
        if not isinstance(account, dict):
            continue
        if account.get("name") == identifier or account.get("id") == identifier:
            return account
    return None


def resolve_account_reference(book: dict[str, Any], identifier: str | None, *, field: str = "account", required: bool = False) -> tuple[str | None, dict[str, Any] | None]:
    if not identifier:
        if required:
            raise ValueError(f"{field} is required")
        return None, None
    account = find_account(book, identifier)
    if account is None:
        raise ValueError(f"{field} not found: {identifier}")
    return str(account.get("id")), account


def find_account_id(book: dict[str, Any], name: str | None) -> str | None:
    account, _ = resolve_account_reference(book, name) if name else (None, None)
    return account


def category_known(book: dict[str, Any], category: str | None) -> bool:
    categories = [c for c in book.get("categories", []) if isinstance(c, dict) and c.get("active", True)]
    if not category or not categories:
        return True
    return any(c.get("name") == category or c.get("id") == category for c in categories)


def append_review_reason(record: dict[str, Any], reason: str, note: str | None = None) -> None:
    reasons = [r.strip() for r in str(record.get("review_reason", "")).split(",") if r.strip()]
    if reason not in reasons:
        reasons.append(reason)
    record["needs_review"] = True
    record["review_reason"] = ", ".join(reasons)
    review = record.get("review") if isinstance(record.get("review"), dict) else review_state(True, reason)
    review["status"] = "needs_review"
    review["reasons"] = reasons
    review["detected_at"] = review.get("detected_at") or now_iso()
    if note:
        review.setdefault("history", []).append({"at": now_iso(), "action": "detected", "note": note})
    record["review"] = review


def amount_for_account_balance(record: dict[str, Any], account: dict[str, Any]) -> int:
    account_currency = str(account.get("currency", record.get("currency", "CNY"))).upper()
    tx_currency = str(record.get("currency", account_currency)).upper()
    if account_currency == tx_currency:
        return int(record.get("amount_minor", 0))
    if account_currency == str(record.get("base_currency", "")).upper() and record.get("base_amount_minor") is not None:
        return int(record.get("base_amount_minor", 0))
    raise ValueError(f"transaction currency {tx_currency} cannot update account {account.get('id')} balance in {account_currency}")


def make_balance_update(account: dict[str, Any], delta: int) -> dict[str, Any]:
    before = int(account.get("balance_minor", 0))
    after = before + delta
    return {
        "account_id": account.get("id"),
        "account_name": account.get("name", ""),
        "currency": account.get("currency", "CNY"),
        "before_balance_minor": before,
        "delta_minor": delta,
        "after_balance_minor": after,
    }


def build_balance_updates(book: dict[str, Any], record: dict[str, Any], *, no_balance_update: bool = False) -> list[dict[str, Any]]:
    if no_balance_update:
        return []
    kind = record.get("kind")
    updates: list[dict[str, Any]] = []
    if kind in {"income", "expense"}:
        account = find_account(book, record.get("account_id"))
        if account is None:
            return []
        amount = amount_for_account_balance(record, account)
        updates.append(make_balance_update(account, amount if kind == "income" else -amount))
    elif kind == "transfer":
        source = find_account(book, record.get("account_id"))
        target = find_account(book, record.get("to_account_id"))
        if source is None or target is None:
            raise ValueError("transfer requires existing source and destination accounts")
        updates.append(make_balance_update(source, -amount_for_account_balance(record, source)))
        updates.append(make_balance_update(target, amount_for_account_balance(record, target)))
    return updates


def apply_balance_updates(book: dict[str, Any], updates: list[dict[str, Any]]) -> None:
    by_id = {account.get("id"): account for account in book.get("accounts", []) if isinstance(account, dict)}
    for update in updates:
        account = by_id.get(update.get("account_id"))
        if account is None:
            raise ValueError(f"account not found while applying balance update: {update.get('account_id')}")
        account["balance_minor"] = int(update["after_balance_minor"])
        account["updated_at"] = now_iso()


def find_exchange_rate(book: dict[str, Any], rate_id: str | None) -> dict[str, Any] | None:
    if not rate_id:
        return None
    for rate in book.get("exchange_rates", []):
        if rate.get("id") == rate_id:
            return rate
    return None


def resolve_base_amount(
    book: dict[str, Any],
    amount_minor: int,
    currency: str,
    tx_date: str,
    *,
    base_amount: str | None = None,
    exchange_rate_id: str | None = None,
) -> tuple[int | None, str, str | None]:
    base_currency = book.get("profile", {}).get("base_currency", "CNY").upper()
    currency = currency.upper()
    if base_amount is not None:
        return parse_positive_amount_minor(base_amount, base_currency, field="base_amount"), base_currency, exchange_rate_id
    if currency == base_currency:
        return amount_minor, base_currency, None
    rate = find_exchange_rate(book, exchange_rate_id)
    if not rate:
        return None, base_currency, exchange_rate_id
    if rate.get("from") != currency or rate.get("to") != base_currency:
        return None, base_currency, exchange_rate_id
    source_major = Decimal(amount_minor) / Decimal(10 ** currency_decimals(currency))
    converted_major = source_major * Decimal(str(rate.get("rate")))
    return parse_amount_minor(str(converted_major), base_currency), base_currency, exchange_rate_id


def review_state(needs_review: bool, reason: str = "") -> dict[str, Any]:
    if not needs_review:
        return {"status": "clear", "reasons": [], "detected_at": None, "reviewed_at": None, "resolution": "", "history": []}
    timestamp = now_iso()
    return {
        "status": "needs_review",
        "reasons": [reason] if reason else ["manual_review"],
        "detected_at": timestamp,
        "reviewed_at": None,
        "resolution": "",
        "history": [{"at": timestamp, "action": "flagged", "note": reason or "manual review requested"}],
    }


def source_payload(args: argparse.Namespace, default_type: str = "manual") -> dict[str, Any]:
    source_type = getattr(args, "source_type", None) or ("chat" if getattr(args, "source_text", None) else default_type)
    payload = {"type": source_type}
    if getattr(args, "source_text", None):
        payload["source_text"] = compact_source_text(args.source_text)
    return payload


def require_write_confirmation(args: argparse.Namespace, *, record_type: str, record: dict[str, Any]) -> tuple[bool, int | None]:
    token = confirmation_token(record_type, record)
    if getattr(args, "dry_run", False):
        print_json(
            {
                "status": "preview",
                "record_type": record_type,
                "confirmation_token": token,
                "record": record,
            }
        )
        return False, 0
    if not getattr(args, "confirmed", False):
        print_json(error_result("preview the candidate and rerun with --confirmed after user approval", code="confirmation_required"))
        return False, 1
    if getattr(args, "require_confirmation_token", False):
        supplied = str(getattr(args, "confirmation_token", "") or "")
        if supplied != token:
            print_json(
                error_result(
                    "the ledger or candidate changed after preview; preview it again before confirmation",
                    code="preview_changed",
                )
            )
            return False, 1
    return True, None


def upsert_by_id_or_name(items: list[dict[str, Any]], record: dict[str, Any], *, name_key: str = "name") -> str:
    for index, item in enumerate(items):
        if item.get("id") == record.get("id") or (name_key and item.get(name_key) == record.get(name_key)):
            items[index] = {**item, **record}
            return "updated"
    items.append(record)
    return "added"


def add_confirmation_args(parser: argparse.ArgumentParser) -> None:
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--dry-run", action="store_true", help="Print candidate record without writing")
    group.add_argument("--confirmed", action="store_true", help="Write after user confirmed candidate fields")


def transaction_id_exists(book: dict[str, Any], tx_id: str) -> bool:
    return any(tx.get("id") == tx_id for tx in book.get("transactions", []) if isinstance(tx, dict))


def reject_duplicate_transaction_id(book: dict[str, Any], tx_id: str) -> bool:
    if not transaction_id_exists(book, tx_id):
        return False
    print_json(error_result(f"transaction id already exists: {tx_id}", code="duplicate_transaction_id"))
    return True



def cmd_add_transaction(args: argparse.Namespace) -> int:
    try:
        book = load_book(args.book)
        tzinfo = book_timezone(book)
        tx_date = parse_date(args.date, tzinfo)
        currency = args.currency.upper()
        amount_minor = parse_positive_amount_minor(args.amount, currency)
        base_amount_minor, base_currency, exchange_rate_id = resolve_base_amount(
            book, amount_minor, currency, tx_date, base_amount=args.base_amount, exchange_rate_id=args.exchange_rate_id
        )
        account_id, _account = resolve_account_reference(
            book,
            args.account,
            required=(args.kind == "transfer" or (not args.no_balance_update and args.kind in {"income", "expense"})),
        )
        to_account_id = None
        if args.kind == "transfer":
            to_account_id, _ = resolve_account_reference(book, args.to_account, field="to-account", required=True)
            if to_account_id == account_id:
                raise ValueError("transfer source and destination accounts must differ")
    except Exception as exc:
        print_json(error_result(str(exc), code="invalid_transaction"))
        return 1
    tx_id = args.id or f"txn_{tx_date.replace('-', '')}_{slugify(args.title)}"
    if reject_duplicate_transaction_id(book, tx_id):
        return 1
    needs_review = bool(args.needs_review)
    record = {
        "id": tx_id,
        "date": tx_date,
        "kind": args.kind,
        "title": args.title,
        "merchant": args.merchant or "",
        "category": args.category,
        "account_id": account_id,
        "to_account_id": to_account_id,
        "subscription_id": args.subscription_id,
        "amount_minor": amount_minor,
        "currency": currency,
        "base_amount_minor": base_amount_minor,
        "base_currency": base_currency,
        "exchange_rate_id": exchange_rate_id,
        "tags": args.tag or [],
        "notes": args.notes or "",
        "needs_review": needs_review,
        "review_reason": args.review_reason or "",
        "review": review_state(needs_review, args.review_reason or ""),
        "source": source_payload(args),
        "created_at": now_iso(tzinfo),
        "updated_at": now_iso(tzinfo),
    }
    if args.kind != "transfer":
        record.pop("to_account_id", None)
    if currency != base_currency and base_amount_minor is None:
        append_review_reason(record, "missing_base_amount", "Foreign-currency transaction is missing a confirmed base-currency amount or exchange rate")
    if not category_known(book, args.category):
        append_review_reason(record, "unknown_category", f"category not found: {args.category}")
    duplicate_matches = candidate_duplicate_matches(book, record, args.duplicate_window_days)
    if duplicate_matches:
        record["source"]["duplicate_candidates"] = duplicate_matches
        append_review_reason(record, "possible_duplicate", f"Similar transactions: {', '.join(duplicate_matches)}")
    try:
        balance_updates = build_balance_updates(book, record, no_balance_update=args.no_balance_update)
    except Exception as exc:
        print_json(error_result(str(exc), code="invalid_balance_update"))
        return 1
    if balance_updates and reject_balance_write_without_history(book):
        return 1
    candidate = copy_json(book)
    candidate.setdefault("transactions", []).append(record)
    apply_balance_updates(candidate, balance_updates)
    snapshot_effect = None
    if balance_updates:
        snapshot_effect = capture_snapshot_effect(
            candidate,
            source_id=tx_id,
            affected_account_ids=[str(row["account_id"]) for row in balance_updates],
        )
    preview = {
        "transaction": record,
        "balance_updates": balance_updates,
        "balance_snapshot": snapshot_effect,
    }
    should_write, rc = require_write_confirmation(args, record_type="transaction", record=preview)
    if not should_write:
        return int(rc)
    save_book(args.book, candidate)
    print_json(
        {
            "status": "added",
            "record_type": "transaction",
            "id": tx_id,
            "record": record,
            "balance_updates": balance_updates,
            "balance_snapshot": snapshot_effect,
        }
    )
    return 0

def cmd_upsert_account(args: argparse.Namespace) -> int:
    try:
        book = load_book(args.book)
        currency = args.currency.upper()
        balance_minor = require_nonnegative_minor(parse_amount_minor(args.balance, currency), field="balance")
    except Exception as exc:
        print_json(error_result(str(exc), code="invalid_account"))
        return 1
    record = {
        "id": args.id,
        "name": args.name,
        "type": args.type,
        "currency": currency,
        "balance_minor": balance_minor,
        "description": args.description or "",
        "display_group": args.display_group or args.name,
        "active": not args.inactive,
        "updated_at": now_iso(book_timezone(book)),
    }
    if reject_balance_write_without_history(book):
        return 1
    previous_account = next(
        (
            copy_json(account)
            for account in book.get("accounts", [])
            if isinstance(account, dict)
            and (account.get("id") == record["id"] or account.get("name") == record["name"])
        ),
        None,
    )
    candidate = copy_json(book)
    status = upsert_by_id_or_name(candidate.setdefault("accounts", []), record)
    snapshot_effect = capture_snapshot_effect(
        candidate,
        source_id=record["id"],
        affected_account_ids=[record["id"]],
    )
    preview = {
        "operation": status,
        "account": record,
        "balance_change": {
            "before_minor": previous_account.get("balance_minor") if previous_account else None,
            "before_currency": previous_account.get("currency") if previous_account else None,
            "after_minor": record["balance_minor"],
            "after_currency": record["currency"],
        },
        "balance_snapshot": snapshot_effect,
    }
    should_write, rc = require_write_confirmation(args, record_type="account", record=preview)
    if not should_write:
        return int(rc)
    save_static_book(args.book, candidate)
    print_json(
        {
            "status": status,
            "record_type": "account",
            "id": record["id"],
            "record": record,
            "balance_snapshot": snapshot_effect,
        }
    )
    return 0


def cmd_upsert_budget(args: argparse.Namespace) -> int:
    try:
        book = load_book(args.book)
        currency = args.currency.upper()
        limit_minor = parse_positive_amount_minor(args.limit, currency, field="limit")
    except Exception as exc:
        print_json(error_result(str(exc), code="invalid_budget"))
        return 1
    record = {
        "id": args.id,
        "name": args.name,
        "group": args.group,
        "category": args.category,
        "period": args.period,
        "limit_minor": limit_minor,
        "currency": currency,
        "active": not args.inactive,
    }
    should_write, rc = require_write_confirmation(args, record_type="budget", record=record)
    if not should_write:
        return int(rc)
    status = upsert_by_id_or_name(book.setdefault("budgets", []), record)
    save_static_book(args.book, book)
    print_json({"status": status, "record_type": "budget", "id": record["id"], "record": record})
    return 0


def cmd_upsert_category(args: argparse.Namespace) -> int:
    try:
        book = load_book(args.book)
    except Exception as exc:
        print_json(error_result(str(exc), code="invalid_category"))
        return 1
    category_id = args.id or slugify(args.name)
    record = {"id": category_id, "name": args.name, "group": args.group, "kind": args.kind, "description": args.description or "", "active": not args.inactive}
    should_write, rc = require_write_confirmation(args, record_type="category", record=record)
    if not should_write:
        return int(rc)
    status = upsert_by_id_or_name(book.setdefault("categories", []), record)
    save_static_book(args.book, book)
    print_json({"status": status, "record_type": "category", "id": category_id, "record": record})
    return 0



def cmd_add_subscription(args: argparse.Namespace) -> int:
    try:
        book = load_book(args.book)
        tzinfo = book_timezone(book)
        currency = args.currency.upper()
        amount_minor = parse_positive_amount_minor(args.amount, currency)
        next_billing_date = parse_date(args.next_billing_date, tzinfo) if args.next_billing_date else ""
        if args.cadence == "custom" and not next_billing_date:
            raise ValueError("custom cadence requires --next-billing-date")
        base_amount_minor, base_currency, exchange_rate_id = resolve_base_amount(
            book, amount_minor, currency, next_billing_date or today_iso(tzinfo), base_amount=args.base_amount, exchange_rate_id=args.exchange_rate_id
        )
        payment_account_id, _ = resolve_account_reference(book, args.account) if args.account else (None, None)
    except Exception as exc:
        print_json(error_result(str(exc), code="invalid_subscription"))
        return 1
    sub_id = args.id or f"sub_{slugify(args.name)}"
    existing = find_subscription(book, sub_id) or find_subscription(book, args.name)
    record = {
        "id": sub_id,
        "name": args.name,
        "description": args.description or "",
        "category": args.category,
        "amount_minor": amount_minor,
        "currency": currency,
        "base_amount_minor": base_amount_minor,
        "base_currency": base_currency,
        "exchange_rate_id": exchange_rate_id,
        "cadence": args.cadence,
        "next_billing_date": next_billing_date,
        "payment_account_id": payment_account_id,
        "active": not args.inactive,
        "reminder": args.reminder == "on",
        "tags": args.tag or [],
        "last_transaction_id": (existing or {}).get("last_transaction_id"),
        "last_charged_date": (existing or {}).get("last_charged_date"),
        "source": source_payload(args),
    }
    if currency != base_currency and base_amount_minor is None:
        record["needs_review"] = True
        record["review_reason"] = "missing_base_amount"
    should_write, rc = require_write_confirmation(args, record_type="subscription", record=record)
    if not should_write:
        return int(rc)
    status = upsert_by_id_or_name(book.setdefault("subscriptions", []), record)
    save_static_book(args.book, book)
    print_json({"status": status, "record_type": "subscription", "id": sub_id, "record": record})
    return 0

def cmd_add_exchange_rate(args: argparse.Namespace) -> int:
    try:
        book = load_book(args.book)
        rate_value = Decimal(str(args.rate))
        if rate_value <= 0:
            raise ValueError("exchange rate must be greater than zero")
        rate_date = parse_date(args.date)
    except Exception as exc:
        print_json(error_result(str(exc), code="invalid_exchange_rate"))
        return 1
    rate_id = args.id or f"fx_{rate_date.replace('-', '')}_{args.from_currency.lower()}_{args.to_currency.lower()}"
    record = {
        "id": rate_id,
        "date": rate_date,
        "from": args.from_currency.upper(),
        "to": args.to_currency.upper(),
        "rate": float(rate_value),
        "source": args.source,
        "estimate": bool(args.estimate),
        "created_at": now_iso(),
    }
    should_write, rc = require_write_confirmation(args, record_type="exchange_rate", record=record)
    if not should_write:
        return int(rc)
    status = upsert_by_id_or_name(book.setdefault("exchange_rates", []), record, name_key="id")
    save_static_book(args.book, book)
    print_json({"status": status, "record_type": "exchange_rate", "id": rate_id, "record": record})
    return 0


def find_transaction(book: dict[str, Any], tx_id: str) -> dict[str, Any] | None:
    for tx in book.get("transactions", []):
        if tx.get("id") == tx_id:
            return tx
    return None


def find_subscription(book: dict[str, Any], identifier: str) -> dict[str, Any] | None:
    for sub in book.get("subscriptions", []):
        if sub.get("id") == identifier or sub.get("name") == identifier:
            return sub
    return None


def subscription_charge_exists_for_due_date(book: dict[str, Any], subscription_id: str, due_date: str) -> bool:
    for tx in book.get("transactions", []):
        if not isinstance(tx, dict) or tx.get("subscription_id") != subscription_id:
            continue
        source = tx.get("source") if isinstance(tx.get("source"), dict) else {}
        tx_date = tx.get("date") or str(tx.get("datetime") or "")[:10]
        if source.get("expected_billing_date") == due_date or tx_date == due_date:
            return True
    return False


def cmd_list_due_subscriptions(args: argparse.Namespace) -> int:
    try:
        book = load_book(args.book)
        tzinfo = book_timezone(book)
        target_date = parse_date(args.date, tzinfo)
        target = date.fromisoformat(target_date)
    except Exception as exc:
        print_json(error_result(str(exc), code="invalid_due_subscription_query"))
        return 1

    accounts = {
        str(account.get("id")): account
        for account in book.get("accounts", [])
        if isinstance(account, dict) and account.get("id")
    }
    exchange_rates = {
        str(rate.get("id")): rate
        for rate in book.get("exchange_rates", [])
        if isinstance(rate, dict) and rate.get("id")
    }
    due: list[dict[str, Any]] = []
    for sub in book.get("subscriptions", []):
        if not isinstance(sub, dict) or not sub.get("active", True) or not sub.get("reminder", True):
            continue
        due_date = str(sub.get("next_billing_date") or "")
        try:
            due_day = date.fromisoformat(due_date)
        except ValueError:
            continue
        if due_day > target:
            continue
        sub_id = str(sub.get("id") or "")
        if not sub_id or subscription_charge_exists_for_due_date(book, sub_id, due_date):
            continue
        account = accounts.get(str(sub.get("payment_account_id") or ""))
        rate = exchange_rates.get(str(sub.get("exchange_rate_id") or ""))
        due.append({
            "id": sub_id,
            "name": sub.get("name"),
            "description": sub.get("description", ""),
            "category": sub.get("category", "Subscription Services"),
            "amount_minor": sub.get("amount_minor"),
            "currency": sub.get("currency", "CNY"),
            "base_amount_minor": sub.get("base_amount_minor"),
            "base_currency": sub.get("base_currency") or book.get("profile", {}).get("base_currency", "CNY"),
            "exchange_rate_id": sub.get("exchange_rate_id"),
            "exchange_rate": ({
                "date": rate.get("date"),
                "from": rate.get("from"),
                "to": rate.get("to"),
                "rate": rate.get("rate"),
                "source": rate.get("source"),
                "estimate": rate.get("estimate", False),
                "matches_due_date": rate.get("date") == due_date,
            } if rate else None),
            "cadence": sub.get("cadence", "monthly"),
            "due_date": due_date,
            "days_overdue": (target - due_day).days,
            "payment_account": ({
                "id": account.get("id"),
                "name": account.get("name"),
                "type": account.get("type"),
                "currency": account.get("currency"),
                "balance_minor": account.get("balance_minor"),
            } if account else None),
        })
    due.sort(key=lambda item: (str(item.get("due_date") or ""), str(item.get("name") or "")))
    print_json({"status": "ok", "date": target_date, "count": len(due), "due_subscriptions": due})
    return 0


def cmd_set_subscription_status(args: argparse.Namespace) -> int:
    try:
        book = load_book(args.book)
        sub = find_subscription(book, args.subscription)
        if sub is None:
            raise ValueError(f"subscription not found: {args.subscription}")
    except Exception as exc:
        print_json(error_result(str(exc), code="invalid_subscription_status"))
        return 1

    active = bool(args.active)
    preview = {
        "id": sub.get("id"),
        "name": sub.get("name"),
        "active": active,
        "next_billing_date": sub.get("next_billing_date"),
    }
    should_write, rc = require_write_confirmation(args, record_type="subscription_status", record=preview)
    if not should_write:
        return int(rc)
    sub["active"] = active
    sub["updated_at"] = now_iso(book_timezone(book))
    save_static_book(args.book, book)
    print_json({"status": "updated", "record_type": "subscription_status", "record": preview})
    return 0


def normalize_review(tx: dict[str, Any]) -> dict[str, Any]:
    review = tx.get("review")
    if not isinstance(review, dict):
        reasons = [tx.get("review_reason")] if tx.get("review_reason") else []
        review = review_state(bool(tx.get("needs_review")), reasons[0] if reasons else "")
        tx["review"] = review
    review.setdefault("status", "needs_review" if tx.get("needs_review") else "clear")
    review.setdefault("reasons", [])
    review.setdefault("detected_at", None)
    review.setdefault("reviewed_at", None)
    review.setdefault("resolution", "")
    review.setdefault("history", [])
    return review


def apply_review_status(tx: dict[str, Any], status: str, reasons: list[str], note: str, action: str) -> None:
    timestamp = now_iso()
    review = normalize_review(tx)
    if status == "needs_review":
        tx["needs_review"] = True
        tx["review_reason"] = ", ".join(reasons)
        review["status"] = "needs_review"
        review["reasons"] = reasons
        review["detected_at"] = review.get("detected_at") or timestamp
        review["reviewed_at"] = None
        review["resolution"] = ""
    else:
        tx["needs_review"] = False
        tx["review_reason"] = ""
        review["status"] = status
        if status == "clear":
            review["reasons"] = []
        review["reviewed_at"] = timestamp
        review["resolution"] = note
    review.setdefault("history", []).append({"at": timestamp, "action": action, "note": note})
    tx["review"] = review
    tx["updated_at"] = timestamp


def review_summary(tx: dict[str, Any], base_currency: str = "CNY") -> dict[str, Any]:
    review = normalize_review(tx)
    currency = tx.get("base_currency") if tx.get("base_amount_minor") is not None else tx.get("currency", base_currency)
    amount = tx.get("base_amount_minor") if tx.get("base_amount_minor") is not None else tx.get("amount_minor")
    return {
        "id": tx.get("id"),
        "date": tx.get("date"),
        "title": tx.get("title"),
        "merchant": tx.get("merchant", ""),
        "category": tx.get("category"),
        "amount": money_label(int(amount or 0), currency),
        "needs_review": bool(tx.get("needs_review")),
        "review_status": review.get("status"),
        "review_reason": tx.get("review_reason", ""),
        "reasons": review.get("reasons", []),
        "resolution": review.get("resolution", ""),
        "source_type": tx.get("source", {}).get("type"),
    }


def copy_json(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False))


def cmd_list_review(args: argparse.Namespace) -> int:
    try:
        book = load_book(args.book)
    except Exception as exc:
        print_json(error_result(str(exc), code="invalid_book"))
        return 1
    base_currency = book.get("profile", {}).get("base_currency", "CNY")
    rows = []
    for tx in book.get("transactions", []):
        review = normalize_review(tx)
        status = review.get("status")
        if args.status == "all" or status == args.status or (args.status == "needs_review" and tx.get("needs_review")):
            rows.append(review_summary(tx, base_currency))
    print_json({"status": "ok", "count": len(rows), "transactions": rows})
    return 0


def cmd_flag_transaction(args: argparse.Namespace) -> int:
    try:
        book = load_book(args.book)
        tx = find_transaction(book, args.id)
        if tx is None:
            raise ValueError(f"transaction not found: {args.id}")
    except Exception as exc:
        print_json(error_result(str(exc), code="invalid_review_update"))
        return 1
    candidate = copy_json(tx)
    reasons = args.reason or ["manual_review"]
    note = args.note or ", ".join(reasons)
    apply_review_status(candidate, "needs_review", reasons, note, "flagged")
    should_write, rc = require_write_confirmation(args, record_type="review_update", record=candidate)
    if not should_write:
        return int(rc)
    apply_review_status(tx, "needs_review", reasons, note, "flagged")
    save_book(args.book, book)
    print_json({"status": "flagged", "id": args.id, "record": review_summary(tx, book.get("profile", {}).get("base_currency", "CNY"))})
    return 0


def cmd_resolve_review(args: argparse.Namespace) -> int:
    try:
        book = load_book(args.book)
        tx = find_transaction(book, args.id)
        if tx is None:
            raise ValueError(f"transaction not found: {args.id}")
    except Exception as exc:
        print_json(error_result(str(exc), code="invalid_review_update"))
        return 1
    candidate = copy_json(tx)
    apply_review_status(candidate, args.status, [], args.resolution, "resolved")
    should_write, rc = require_write_confirmation(args, record_type="review_update", record=candidate)
    if not should_write:
        return int(rc)
    apply_review_status(tx, args.status, [], args.resolution, "resolved")
    save_book(args.book, book)
    print_json({"status": args.status, "id": args.id, "record": review_summary(tx, book.get("profile", {}).get("base_currency", "CNY"))})
    return 0


def tx_date_value(tx: dict[str, Any]) -> date | None:
    try:
        return date.fromisoformat(str(tx.get("date")))
    except Exception:
        return None


def duplicate_key(tx: dict[str, Any]) -> tuple[Any, ...]:
    merchant_or_title = (tx.get("merchant") or tx.get("title") or "").strip().lower()
    return (tx.get("kind"), tx.get("currency"), tx.get("amount_minor"), tx.get("account_id"), merchant_or_title)


def detect_anomalies(book: dict[str, Any], window_days: int = 3) -> list[dict[str, Any]]:
    base_currency = book.get("profile", {}).get("base_currency", "CNY")
    anomalies: list[dict[str, Any]] = []
    txs = [tx for tx in book.get("transactions", []) if isinstance(tx, dict)]
    dated = [(tx, tx_date_value(tx)) for tx in txs]
    seen_pairs: set[tuple[str, str]] = set()
    for index, (current, current_date) in enumerate(dated):
        if current_date is None:
            anomalies.append({"transaction_id": current.get("id"), "reason": "invalid_date", "note": "Transaction date could not be parsed", "matches": []})
            continue
        for previous, previous_date in dated[:index]:
            if previous_date is None:
                continue
            if duplicate_key(previous) != duplicate_key(current):
                continue
            if abs((current_date - previous_date).days) > window_days:
                continue
            pair = tuple(sorted([str(previous.get("id")), str(current.get("id"))]))
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            anomalies.append({
                "transaction_id": current.get("id"),
                "reason": "duplicate_charge",
                "note": f"Transaction {previous.get('id')} has the same amount and source within a {window_days}-day window",
                "matches": [previous.get("id")],
            })
    for tx in txs:
        currency = str(tx.get("currency", base_currency)).upper()
        if currency != base_currency.upper() and tx.get("base_amount_minor") is None:
            anomalies.append({
                "transaction_id": tx.get("id"),
                "reason": "missing_base_amount",
                "note": "Foreign-currency transaction is missing a confirmed base-currency amount or exchange rate",
                "matches": [],
            })
        if tx.get("needs_review"):
            anomalies.append({
                "transaction_id": tx.get("id"),
                "reason": "existing_review",
                "note": "Transaction is already marked for review",
                "matches": [],
            })
        base_amount = tx.get("base_amount_minor")
        if base_amount is None and currency == base_currency.upper():
            base_amount = tx.get("amount_minor")
        if isinstance(base_amount, int) and abs(base_amount) >= LARGE_TRANSACTION_BASE_MINOR:
            anomalies.append({
                "transaction_id": tx.get("id"),
                "reason": "large_amount",
                "note": "Transaction amount exceeds the default large-transaction review threshold",
                "matches": [],
            })
    return anomalies


def cmd_scan_anomalies(args: argparse.Namespace) -> int:
    try:
        book = load_book(args.book)
    except Exception as exc:
        print_json(error_result(str(exc), code="invalid_book"))
        return 1
    anomalies = detect_anomalies(book, args.window_days)
    preview = {"anomalies": anomalies, "window_days": args.window_days, "will_flag": len(anomalies)}
    should_write, rc = require_write_confirmation(args, record_type="anomaly_scan", record=preview)
    if not should_write:
        return int(rc)
    by_id = {tx.get("id"): tx for tx in book.get("transactions", []) if isinstance(tx, dict)}
    applied = []
    for anomaly in anomalies:
        tx = by_id.get(anomaly.get("transaction_id"))
        if not tx:
            continue
        apply_review_status(tx, "needs_review", [anomaly["reason"]], anomaly["note"], "detected")
        applied.append(tx.get("id"))
    save_book(args.book, book)
    print_json({"status": "flagged", "count": len(applied), "transaction_ids": applied})
    return 0


def add_months(value: date, months: int) -> date:
    target_month = value.month - 1 + months
    year = value.year + target_month // 12
    month = target_month % 12 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)



def advance_billing_date(value: str, cadence: str) -> str:
    try:
        current = date.fromisoformat(value)
    except Exception:
        current = datetime.now(TZ).date()
    if cadence == "weekly":
        return (current + timedelta(days=7)).isoformat()
    if cadence == "monthly":
        return add_months(current, 1).isoformat()
    if cadence == "quarterly":
        return add_months(current, 3).isoformat()
    if cadence == "yearly":
        return add_months(current, 12).isoformat()
    return current.isoformat()


def advance_billing_date_after(value: str, cadence: str, after_value: str) -> str:
    if cadence == "custom":
        return value
    try:
        current = date.fromisoformat(value)
        after = date.fromisoformat(after_value)
    except Exception:
        return advance_billing_date(value, cadence)
    while current <= after:
        current = date.fromisoformat(advance_billing_date(current.isoformat(), cadence))
    return current.isoformat()

def subscription_duplicate(book: dict[str, Any], sub_id: str, charge_date: str, window_days: int = 3) -> dict[str, Any] | None:
    try:
        target = date.fromisoformat(charge_date)
    except Exception:
        return None
    for tx in book.get("transactions", []):
        if tx.get("subscription_id") != sub_id:
            continue
        tx_date = tx_date_value(tx)
        if tx_date and abs((target - tx_date).days) <= window_days:
            return tx
    return None



def cmd_charge_subscription(args: argparse.Namespace) -> int:
    try:
        book = load_book(args.book)
        tzinfo = book_timezone(book)
        sub = find_subscription(book, args.subscription)
        if sub is None:
            raise ValueError(f"subscription not found: {args.subscription}")
        if not sub.get("active", True):
            raise ValueError(f"subscription is inactive: {args.subscription}")
        charge_date = parse_date(args.date, tzinfo)
        currency = (args.currency or sub.get("currency", "CNY")).upper()
        amount_minor = parse_positive_amount_minor(args.amount, currency) if args.amount else require_positive_minor(int(sub.get("amount_minor", 0)), field="subscription amount")
        base_amount_minor, base_currency, exchange_rate_id = resolve_base_amount(
            book, amount_minor, currency, charge_date, base_amount=args.base_amount, exchange_rate_id=args.exchange_rate_id or sub.get("exchange_rate_id")
        )
        account_id, _ = resolve_account_reference(book, args.account or sub.get("payment_account_id"), field="account", required=not args.no_balance_update)
    except Exception as exc:
        print_json(error_result(str(exc), code="invalid_subscription_charge"))
        return 1
    sub_id = str(sub.get("id"))
    expected_date = sub.get("next_billing_date") or ""
    expected_currency = str(sub.get("currency", currency)).upper()
    expected_amount_minor = int(sub.get("amount_minor", amount_minor))
    review_reasons: list[str] = []
    review_notes: list[str] = []
    if expected_date and charge_date < expected_date:
        review_reasons.append("early_subscription_charge")
        review_notes.append(f"Charge date {charge_date} is earlier than the expected date {expected_date}")
    if currency != expected_currency or amount_minor != expected_amount_minor:
        review_reasons.append("subscription_amount_changed")
        review_notes.append("Charge amount or currency does not match the subscription definition")
    duplicate = subscription_duplicate(book, sub_id, charge_date)
    if duplicate:
        review_reasons.append("duplicate_subscription_charge")
        review_notes.append(f"A subscription charge already exists in the same billing cycle: {duplicate.get('id')}")
    if currency != base_currency and base_amount_minor is None:
        review_reasons.append("missing_base_amount")
        review_notes.append("Foreign-currency subscription charge is missing a confirmed base-currency amount or exchange rate")
    if sub.get("cadence") == "custom" and not args.next_billing_date:
        print_json(error_result("custom subscription charge requires --next-billing-date", code="next_billing_date_required"))
        return 1
    tx_id = args.id or f"txn_{charge_date.replace('-', '')}_sub_{slugify(str(sub.get('name', sub_id)))}"
    if reject_duplicate_transaction_id(book, tx_id):
        return 1
    needs_review = bool(review_reasons)
    note = "; ".join(review_notes)
    tx_record = {
        "id": tx_id,
        "date": charge_date,
        "kind": "expense",
        "title": args.title or str(sub.get("name", "Subscription Charge")),
        "merchant": str(sub.get("name", "")),
        "category": sub.get("category", "Subscription Services"),
        "account_id": account_id,
        "subscription_id": sub_id,
        "amount_minor": amount_minor,
        "currency": currency,
        "base_amount_minor": base_amount_minor,
        "base_currency": base_currency,
        "exchange_rate_id": exchange_rate_id,
        "tags": sub.get("tags", []),
        "notes": args.notes or note,
        "needs_review": needs_review,
        "review_reason": ", ".join(review_reasons),
        "review": review_state(needs_review, ", ".join(review_reasons)),
        "source": {
            "type": "subscription",
            "subscription_id": sub_id,
            "source_text": compact_source_text(args.source_text or f"Subscription charge for {sub.get('name', sub_id)}"),
            "expected_billing_date": expected_date,
            "actual_billing_date": charge_date,
            "expected_amount_minor": expected_amount_minor,
            "expected_currency": expected_currency,
        },
        "created_at": now_iso(tzinfo),
        "updated_at": now_iso(tzinfo),
    }
    next_billing_date = parse_date(args.next_billing_date, tzinfo) if args.next_billing_date else advance_billing_date_after(expected_date or charge_date, sub.get("cadence", "monthly"), charge_date)
    subscription_update = {"id": sub_id, "last_transaction_id": tx_id, "last_charged_date": charge_date, "next_billing_date": next_billing_date}
    try:
        balance_updates = build_balance_updates(book, tx_record, no_balance_update=args.no_balance_update)
    except Exception as exc:
        print_json(error_result(str(exc), code="invalid_balance_update"))
        return 1
    if balance_updates and reject_balance_write_without_history(book):
        return 1
    candidate = copy_json(book)
    candidate.setdefault("transactions", []).append(tx_record)
    apply_balance_updates(candidate, balance_updates)
    candidate_sub = find_subscription(candidate, sub_id)
    if candidate_sub is None:
        print_json(error_result("subscription disappeared from candidate", code="invalid_subscription_charge"))
        return 1
    candidate_sub.update(subscription_update)
    snapshot_effect = None
    if balance_updates:
        snapshot_effect = capture_snapshot_effect(
            candidate,
            source_id=tx_id,
            affected_account_ids=[str(row["account_id"]) for row in balance_updates],
        )
    preview = {
        "transaction": tx_record,
        "subscription_update": subscription_update,
        "balance_updates": balance_updates,
        "balance_snapshot": snapshot_effect,
    }
    should_write, rc = require_write_confirmation(args, record_type="subscription_charge", record=preview)
    if not should_write:
        return int(rc)
    save_book(args.book, candidate)
    print_json({"status": "charged", "transaction_id": tx_id, "subscription_id": sub_id, "record": preview})
    return 0

def unwrap_ocr_value(value: Any) -> Any:
    if isinstance(value, dict):
        for key in ("value", "text", "amount", "normalized", "raw"):
            if value.get(key) not in (None, ""):
                return value[key]
    return value


def first_present(data: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        if key in data:
            value = unwrap_ocr_value(data[key])
            if value not in (None, ""):
                return value
    return None


def merged_ocr_fields(data: dict[str, Any]) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    if isinstance(data, dict):
        fields.update(data)
        for key in ("fields", "extracted", "result", "receipt", "document"):
            nested = data.get(key)
            if isinstance(nested, dict):
                fields.update(nested)
    return fields


def load_ocr_json(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    expanded = expand_path(path)
    data = json.loads(expanded.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("OCR JSON must be an object")
    return data


def read_text_file(path: Path | None) -> str:
    if path is None:
        return ""
    return expand_path(path).read_text(encoding="utf-8").strip()


def ocr_source_text(args: argparse.Namespace, ocr_data: dict[str, Any], fields: dict[str, Any]) -> str:
    if args.source_text:
        return args.source_text
    text = read_text_file(args.ocr_text_file)
    if text:
        return text
    value = first_present(fields, ("source_text", "raw_text", "text", "content", "markdown", "full_text"))
    if value:
        return str(value)
    pages = ocr_data.get("pages")
    if isinstance(pages, list):
        page_text = "\n".join(str(page.get("text", "")) for page in pages if isinstance(page, dict) and page.get("text"))
        if page_text.strip():
            return page_text.strip()
    return ""


def coerce_confidence(value: Any) -> float | None:
    if value in (None, ""):
        return None
    if isinstance(value, str):
        text = value.strip().rstrip("%")
        try:
            number = float(text)
        except ValueError:
            return None
        return number / 100 if number > 1 else number
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number / 100 if number > 1 else number


def parse_line_items_json(value: str | None) -> list[Any]:
    if not value:
        return []
    possible_path = expand_path(Path(value))
    if possible_path.exists():
        raw = json.loads(possible_path.read_text(encoding="utf-8"))
    else:
        raw = json.loads(value)
    if not isinstance(raw, list):
        raise ValueError("line items JSON must be an array")
    return raw


def normalize_receipt_line_items(raw_items: Any, default_currency: str, default_category: str) -> list[dict[str, Any]]:
    if not isinstance(raw_items, list):
        return []
    rows: list[dict[str, Any]] = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        currency = str(first_present(item, ("currency",)) or default_currency).upper()
        amount_minor = item.get("amount_minor")
        if amount_minor is None:
            amount_value = first_present(item, ("amount", "total", "price", "line_total"))
            if amount_value not in (None, ""):
                try:
                    amount_minor = parse_positive_amount_minor(amount_value, currency)
                except ValueError:
                    amount_minor = None
        row = {
            "description": str(first_present(item, ("description", "name", "title", "item")) or ""),
            "quantity": first_present(item, ("quantity", "qty")) or 1,
            "amount_minor": amount_minor,
            "currency": currency,
            "category": first_present(item, ("category",)) or default_category,
        }
        confidence = coerce_confidence(first_present(item, ("confidence", "ocr_confidence")))
        if confidence is not None:
            row["confidence"] = confidence
        rows.append(row)
    return rows



def receipt_destination(book_path: Path, receipt_file: Path | None, tx_date: str) -> tuple[Path | None, str]:
    if receipt_file is None:
        return None, ""
    source = expand_path(receipt_file)
    if not source.exists():
        raise FileNotFoundError(f"receipt file not found: {source}")
    suffix = source.suffix or ".receipt"
    base = f"{tx_date}-{slugify(source.stem)}"
    destination = runtime_dirs(book_path)["receipts"] / f"{base}{suffix.lower()}"
    index = 2
    while destination.exists():
        try:
            if source.resolve() == destination.resolve():
                break
        except FileNotFoundError:
            pass
        destination = runtime_dirs(book_path)["receipts"] / f"{base}-{index}{suffix.lower()}"
        index += 1
    return destination, f"receipts/{destination.name}"

def copy_receipt_file(source: Path | None, destination: Path | None) -> bool:
    """Atomically reserve and copy receipt evidence; return ownership."""
    if source is None or destination is None:
        return False
    src = expand_path(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        if src.resolve() == destination.resolve():
            return False
    except FileNotFoundError:
        pass

    fd = os.open(str(destination), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.close(fd)
    try:
        shutil.copy2(src, destination)
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    return True


def candidate_duplicate_matches(book: dict[str, Any], candidate: dict[str, Any], window_days: int) -> list[str]:
    candidate_date = tx_date_value(candidate)
    if candidate_date is None:
        return []
    matches: list[str] = []
    candidate_key = duplicate_key(candidate)
    for tx in book.get("transactions", []):
        if duplicate_key(tx) != candidate_key:
            continue
        tx_date = tx_date_value(tx)
        if tx_date and abs((candidate_date - tx_date).days) <= window_days:
            matches.append(str(tx.get("id")))
    return matches


def receipt_source_payload(
    args: argparse.Namespace,
    *,
    relative_file: str,
    source_text: str,
    merchant: str,
    invoice_number: str,
    payment_method: str,
    confidence: float | None,
    line_items: list[dict[str, Any]],
    extracted_fields: dict[str, Any],
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "type": "receipt",
        "file": relative_file,
        "source_text": source_text,
        "merchant": merchant,
        "invoice_number": invoice_number,
        "payment_method": payment_method,
        "ocr_engine": args.ocr_engine,
        "ocr_confidence": confidence,
        "line_items": line_items,
    }
    if args.receipt_file:
        payload["original_file"] = str(expand_path(args.receipt_file))
    if args.ocr_json:
        payload["ocr_json_file"] = str(expand_path(args.ocr_json))
    compact = {key: value for key, value in extracted_fields.items() if key in {"date", "transaction_date", "issued_date", "merchant", "vendor", "seller", "total", "total_amount", "amount", "currency"}}
    if compact:
        payload["extracted_fields"] = compact
    return payload



def cmd_import_receipt(args: argparse.Namespace) -> int:
    try:
        book = load_book(args.book)
        tzinfo = book_timezone(book)
        ocr_data = load_ocr_json(args.ocr_json)
        fields = merged_ocr_fields(ocr_data)
        source_text = compact_source_text(ocr_source_text(args, ocr_data, fields))
        date_value = args.date or first_present(fields, ("date", "transaction_date", "issued_date", "paid_at")) or "today"
        tx_date = parse_date(str(date_value), tzinfo)
        extracted_currency = first_present(fields, ("currency", "total_currency"))
        currency = str(args.currency or extracted_currency or "CNY").upper()
        explicit_amount = args.amount
        extracted_amount = first_present(fields, ("total", "total_amount", "amount", "paid_amount", "grand_total"))
        amount_value = explicit_amount if explicit_amount not in (None, "") else extracted_amount
        if amount_value in (None, ""):
            raise ValueError("receipt amount is required; pass --amount or provide total in --ocr-json")
        amount_minor = parse_positive_amount_minor(amount_value, currency)
        base_amount_minor, base_currency, exchange_rate_id = resolve_base_amount(
            book, amount_minor, currency, tx_date, base_amount=args.base_amount, exchange_rate_id=args.exchange_rate_id
        )
        merchant = str(args.merchant or first_present(fields, ("merchant", "vendor", "seller", "payee")) or "")
        invoice_number = str(args.invoice_number or first_present(fields, ("invoice_number", "invoice_no", "receipt_number", "document_number")) or "")
        payment_method = str(args.payment_method or first_present(fields, ("payment_method", "payment", "account")) or "")
        raw_line_items = parse_line_items_json(args.line_items_json) or first_present(fields, ("line_items", "items")) or []
        line_items = normalize_receipt_line_items(raw_line_items, currency, args.category)
        confidence = coerce_confidence(args.ocr_confidence) if args.ocr_confidence is not None else coerce_confidence(first_present(fields, ("ocr_confidence", "confidence", "score")))
        account_id, _ = resolve_account_reference(book, args.account, required=not args.no_balance_update)
        receipt_dest, relative_file = receipt_destination(args.book, args.receipt_file, tx_date)
    except Exception as exc:
        print_json(error_result(str(exc), code="invalid_receipt"))
        return 1

    review_reasons: list[str] = []
    review_notes: list[str] = []
    if confidence is not None and confidence < args.confidence_threshold:
        review_reasons.append("low_ocr_confidence")
        review_notes.append(f"OCR confidence {confidence:.2f} below threshold {args.confidence_threshold:.2f}")
    if explicit_amount not in (None, "") and extracted_amount not in (None, ""):
        try:
            extracted_minor = parse_amount_minor(extracted_amount, currency)
            if extracted_minor != amount_minor:
                review_reasons.append("amount_conflict")
                review_notes.append("Explicit amount does not match OCR amount")
        except ValueError:
            review_reasons.append("amount_conflict")
            review_notes.append("OCR amount could not be parsed")
    if not args.currency and not extracted_currency:
        review_reasons.append("currency_defaulted")
        review_notes.append("No currency was recognized; defaulting to CNY")
    if currency != base_currency and base_amount_minor is None:
        review_reasons.append("missing_base_amount")
        review_notes.append("Foreign-currency receipt is missing a confirmed base-currency amount or exchange rate")
    if not args.date and not first_present(fields, ("date", "transaction_date", "issued_date", "paid_at")):
        review_reasons.append("missing_receipt_date")
        review_notes.append("No receipt date was recognized; defaulting to today")
    if not merchant:
        review_reasons.append("missing_merchant")
        review_notes.append("No merchant was recognized")
    if not category_known(book, args.category):
        review_reasons.append("unknown_category")
        review_notes.append(f"category not found: {args.category}")
    if args.needs_review:
        review_reasons.append("manual_review")
    for reason in args.review_reason or []:
        if reason not in review_reasons:
            review_reasons.append(reason)
    tx_id = args.id or f"txn_{tx_date.replace('-', '')}_receipt_{slugify(merchant or args.title or args.category)}"
    if reject_duplicate_transaction_id(book, tx_id):
        return 1
    source = receipt_source_payload(
        args,
        relative_file=relative_file,
        source_text=source_text,
        merchant=merchant,
        invoice_number=invoice_number,
        payment_method=payment_method,
        confidence=confidence,
        line_items=line_items,
        extracted_fields=fields,
    )
    needs_review = bool(review_reasons)
    review = review_state(needs_review, ", ".join(review_reasons))
    if needs_review:
        review["reasons"] = list(dict.fromkeys(review_reasons))
        if review_notes:
            review.setdefault("history", []).append({"at": now_iso(tzinfo), "action": "detected", "note": "; ".join(review_notes)})
    record = {
        "id": tx_id,
        "date": tx_date,
        "kind": "expense",
        "title": args.title or merchant or "Receipt",
        "merchant": merchant,
        "category": args.category,
        "account_id": account_id,
        "subscription_id": None,
        "amount_minor": amount_minor,
        "currency": currency,
        "base_amount_minor": base_amount_minor,
        "base_currency": base_currency,
        "exchange_rate_id": exchange_rate_id,
        "tags": args.tag or [],
        "notes": args.notes or "; ".join(review_notes),
        "needs_review": needs_review,
        "review_reason": ", ".join(review_reasons),
        "review": review,
        "source": source,
        "created_at": now_iso(tzinfo),
        "updated_at": now_iso(tzinfo),
    }
    duplicate_matches = candidate_duplicate_matches(book, record, args.duplicate_window_days)
    if duplicate_matches:
        append_review_reason(record, "possible_duplicate_receipt", f"Receipt resembles existing transactions: {', '.join(duplicate_matches)}")
        record["source"]["duplicate_candidates"] = duplicate_matches
    try:
        balance_updates = build_balance_updates(book, record, no_balance_update=args.no_balance_update)
    except Exception as exc:
        print_json(error_result(str(exc), code="invalid_balance_update"))
        return 1
    if balance_updates and reject_balance_write_without_history(book):
        return 1
    candidate = copy_json(book)
    candidate.setdefault("transactions", []).append(record)
    apply_balance_updates(candidate, balance_updates)
    snapshot_effect = None
    if balance_updates:
        snapshot_effect = capture_snapshot_effect(
            candidate,
            source_id=tx_id,
            affected_account_ids=[str(row["account_id"]) for row in balance_updates],
        )
    preview = {
        "transaction": record,
        "balance_updates": balance_updates,
        "balance_snapshot": snapshot_effect,
    }
    should_write, rc = require_write_confirmation(args, record_type="receipt_transaction", record=preview)
    if not should_write:
        return int(rc)
    static_path = _static_book_path(args.book)
    with _exclusive_book_lock(static_path):
        try:
            _check_concurrent_modification(static_path)
        except Exception as exc:
            print_json(error_result(str(exc), code="receipt_commit_failed"))
            return 1

        locked_dest, locked_relative_file = receipt_destination(
            args.book, args.receipt_file, tx_date
        )
        if locked_dest != receipt_dest or locked_relative_file != relative_file:
            print_json(
                error_result(
                    "receipt evidence destination changed after preview; preview again",
                    code="preview_changed",
                )
            )
            return 1
        try:
            receipt_copied = copy_receipt_file(args.receipt_file, receipt_dest)
        except FileExistsError:
            print_json(
                error_result(
                    "receipt evidence destination changed after preview; preview again",
                    code="preview_changed",
                )
            )
            return 1
        except Exception as exc:
            print_json(error_result(str(exc), code="receipt_copy_failed"))
            return 1

        try:
            save_book(args.book, candidate, _lock_held=True)
        except Exception as exc:
            if receipt_copied and receipt_dest is not None:
                receipt_dest.unlink(missing_ok=True)
            print_json(error_result(str(exc), code="receipt_commit_failed"))
            return 1
    print_json(
        {
            "status": "imported",
            "record_type": "transaction",
            "id": tx_id,
            "record": record,
            "balance_updates": balance_updates,
            "balance_snapshot": snapshot_effect,
        }
    )
    return 0


def _fallback_lock_is_stale(lock_dir: Path) -> bool:
    """Return whether a directory-lock owner is absent or no longer alive."""
    owner_path = lock_dir / "owner"
    try:
        owner = owner_path.read_text(encoding="ascii").strip()
    except FileNotFoundError:
        try:
            return time.time() - lock_dir.stat().st_mtime >= 1.0
        except OSError:
            return False
    except OSError:
        return False
    try:
        owner_pid = int(owner.split(":", 1)[0])
    except (TypeError, ValueError):
        try:
            return time.time() - lock_dir.stat().st_mtime >= 1.0
        except OSError:
            return False
    try:
        os.kill(owner_pid, 0)
    except ProcessLookupError:
        return True
    except PermissionError:
        return False
    except OSError:
        return False
    return False


@contextmanager
def _exclusive_book_lock(path: Path):
    lock_path = _book_lock_path(path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fallback_dir: Path | None = None
    fallback_owner: str | None = None
    with lock_path.open("a+b") as lock_file:
        if fcntl is not None:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        elif msvcrt is not None:
            lock_file.seek(0, os.SEEK_END)
            if lock_file.tell() == 0:
                lock_file.write(b"\0")
                lock_file.flush()
            lock_file.seek(0)
            msvcrt.locking(lock_file.fileno(), msvcrt.LK_LOCK, 1)
        else:
            fallback_dir = lock_path.with_name(lock_path.name + ".exclusive")
            deadline = time.monotonic() + 30
            while True:
                try:
                    fallback_dir.mkdir()
                    fallback_owner = f"{os.getpid()}:{time.time_ns()}"
                    try:
                        (fallback_dir / "owner").write_text(
                            fallback_owner, encoding="ascii"
                        )
                    except Exception:
                        shutil.rmtree(fallback_dir, ignore_errors=True)
                        raise
                    break
                except FileExistsError:
                    if _fallback_lock_is_stale(fallback_dir):
                        try:
                            shutil.rmtree(fallback_dir)
                        except FileNotFoundError:
                            pass
                        except OSError:
                            time.sleep(0.05)
                        continue
                    if time.monotonic() >= deadline:
                        raise TimeoutError(f"timed out acquiring ledger lock: {fallback_dir}")
                    time.sleep(0.05)
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
            elif msvcrt is not None:
                lock_file.seek(0)
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
            elif fallback_dir is not None and fallback_owner is not None:
                try:
                    current_owner = (fallback_dir / "owner").read_text(
                        encoding="ascii"
                    ).strip()
                except OSError:
                    current_owner = None
                if current_owner == fallback_owner:
                    shutil.rmtree(fallback_dir, ignore_errors=True)

def _atomic_write_bytes(target: Path, payload: bytes) -> str:
    digest = hashlib.sha256(payload).hexdigest()
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    with tmp.open("wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, target)
    try:
        dir_fd = os.open(str(target.parent), os.O_RDONLY)
    except OSError:
        return digest
    try:
        try:
            os.fsync(dir_fd)
        except OSError:
            # The rename already committed. A directory-fsync failure must not
            # be reported as an uncommitted write or trigger shard rollback.
            pass
    finally:
        try:
            os.close(dir_fd)
        except OSError:
            pass
    return digest

def _build_static_payload(book: dict[str, Any], *, updated_at: str | None = None) -> dict[str, Any]:
    static_book = {key: copy_json(book[key]) for key in STATIC_TOP_LEVEL if key in book}
    version = static_book.get("schema_version", STATIC_SCHEMA_VERSION)
    if type(version) is not int or version != STATIC_SCHEMA_VERSION:
        raise UnsupportedStaticSchema(
            f"static schema version {STATIC_SCHEMA_VERSION} is required"
        )
    static_book["schema_version"] = STATIC_SCHEMA_VERSION
    static_book.setdefault(SNAPSHOT_FIELD, [])
    if "profile" not in static_book:
        static_book["profile"] = {
            "base_currency": "CNY",
            "timezone": "Asia/Shanghai",
            "month_start_day": 1,
        }
    timestamp = updated_at or now_iso(book_timezone(book))
    metadata = copy_json(static_book.get("metadata", {})) if isinstance(static_book.get("metadata"), dict) else {}
    metadata.setdefault("created_at", timestamp)
    metadata["updated_at"] = timestamp
    static_book["metadata"] = metadata
    return static_book

def _save_static_book_locked(static_path: Path, book: dict[str, Any]) -> None:
    _check_concurrent_modification(static_path)
    shard_digests = _transaction_shard_digests(static_path)
    static_book = _build_static_payload(book)
    static_digest = _atomic_write_json(static_path, static_book)
    book["metadata"] = copy_json(static_book["metadata"])
    _LOADED_UPDATED_AT[str(static_path)] = static_book["metadata"]["updated_at"]
    _LOADED_STATIC_SHA256[str(static_path)] = static_digest
    _LOADED_TRANSACTION_SHA256[str(static_path)] = shard_digests

def save_static_book(path: Path, book: dict[str, Any]) -> None:
    """Persist only static state without touching transaction shard bytes."""
    static_path = _static_book_path(path)
    static_path.parent.mkdir(parents=True, exist_ok=True)
    with _exclusive_book_lock(static_path):
        _save_static_book_locked(static_path, book)

def _restore_transaction_shards(static_path: Path, originals: dict[Path, bytes]) -> None:
    for current in _list_month_files(static_path):
        if current not in originals:
            current.unlink()
            _LOADED_UPDATED_AT.pop(str(current), None)
    for shard_path, payload in originals.items():
        _atomic_write_bytes(shard_path, payload)
        try:
            shard_data = json.loads(payload.decode("utf-8"))
            updated_at = (shard_data.get("metadata", {}) or {}).get("updated_at")
        except Exception:
            updated_at = None
        _LOADED_UPDATED_AT[str(shard_path)] = updated_at

def validate_transaction_shards(path: Path) -> list[str]:
    errors: list[str] = []
    transaction_dir = _transactions_dir(_static_book_path(path))
    if not transaction_dir.exists():
        return errors
    for shard in sorted(transaction_dir.glob("*.json")):
        match = _MONTH_FILE_RE.fullmatch(shard.name)
        if match is None:
            errors.append(f"{shard.name} filename must match YYYY-MM.json with a valid month")
            continue
        try:
            payload = json.loads(shard.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            errors.append(f"{shard.name} could not be read: {exc}")
            continue
        if not isinstance(payload, dict):
            errors.append(f"{shard.name} must be an object")
            continue
        version = payload.get("schema_version")
        if type(version) is not int or version != TRANSACTION_SHARD_SCHEMA_VERSION:
            errors.append(
                f"{shard.name}.schema_version must be {TRANSACTION_SHARD_SCHEMA_VERSION}"
            )
        expected_month = shard.stem
        if payload.get("month") != expected_month:
            errors.append(f"{shard.name}.month must be {expected_month}")
        if not isinstance(payload.get("metadata"), dict):
            errors.append(f"{shard.name}.metadata must be an object")
        transactions = payload.get("transactions")
        if not isinstance(transactions, list):
            errors.append(f"{shard.name}.transactions must be an array")
        elif not all(isinstance(row, dict) for row in transactions):
            errors.append(f"{shard.name}.transactions must contain only objects")
        else:
            for index, row in enumerate(transactions):
                transaction_date = row.get("date")
                try:
                    transaction_month = date.fromisoformat(transaction_date).strftime("%Y-%m")
                except (TypeError, ValueError):
                    continue  # validate_book_data reports the malformed transaction date.
                if transaction_month != expected_month:
                    errors.append(
                        f"{shard.name}.transactions[{index}].date must be within {expected_month}"
                    )
    return errors

def _load_book_for_validation(path: Path) -> dict[str, Any]:
    static_path = _static_book_path(path)
    if not static_path.exists():
        raise FileNotFoundError(f"book not found: {static_path}")
    book = json.loads(static_path.read_text(encoding="utf-8"))
    if not isinstance(book, dict):
        raise ValueError("book root must be an object")
    transactions: list[dict[str, Any]] = []
    for shard in _list_month_files(static_path):
        try:
            payload = json.loads(shard.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        rows = payload.get("transactions") if isinstance(payload, dict) else None
        if isinstance(rows, list):
            transactions.extend(row for row in rows if isinstance(row, dict))
    book["transactions"] = transactions
    return book

def _stable_confirmation_value(value: Any, path: tuple[str, ...] = ()) -> Any:
    if isinstance(value, dict):
        stable: dict[str, Any] = {}
        for key, item in sorted(value.items()):
            # The outer candidate snapshot timestamp is regenerated on the
            # confirmed invocation; persisted account timestamps stay bound.
            if path and path[-1] == "snapshot" and key in {"created_at", "updated_at"}:
                continue
            stable[key] = _stable_confirmation_value(item, (*path, key))
        return stable
    if isinstance(value, list):
        return [
            _stable_confirmation_value(item, (*path, str(index)))
            for index, item in enumerate(value)
        ]
    return value

def confirmation_token(record_type: str, record: dict[str, Any]) -> str:
    canonical = json.dumps(
        {"record_type": record_type, "record": _stable_confirmation_value(record)},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()

def reject_balance_write_without_history(book: dict[str, Any]) -> bool:
    if (
        type(book.get("schema_version")) is int
        and book.get("schema_version") == STATIC_SCHEMA_VERSION
        and isinstance(book.get(SNAPSHOT_FIELD), list)
    ):
        return False
    print_json(
        error_result(
            f"static schema version {STATIC_SCHEMA_VERSION} with {SNAPSHOT_FIELD} is required",
            code="unsupported_static_schema",
        )
    )
    return True

def capture_snapshot_effect(
    candidate: dict[str, Any],
    *,
    source_id: str,
    affected_account_ids: list[str],
) -> dict[str, Any]:
    capture = capture_current_snapshot(
        candidate,
        source_type="automatic",
        source_id=source_id,
    )
    snapshot = capture["snapshot"]
    return {
        "mode": capture["mode"],
        "month": snapshot["month"],
        "revision": snapshot["revision"],
        "affected_account_ids": list(dict.fromkeys(affected_account_ids)),
        "summary": snapshot_summary(snapshot),
    }

def add_bound_confirmation_args(parser: argparse.ArgumentParser) -> None:
    add_confirmation_args(parser)
    parser.add_argument(
        "--confirmation-token",
        help="Opaque token returned by the exact dry-run candidate",
    )
    parser.set_defaults(require_confirmation_token=True)

def _transaction_shard_digests(static_path: Path) -> dict[str, str]:
    transaction_dir = _transactions_dir(static_path)
    if not transaction_dir.exists():
        return {}
    return {
        shard.name: hashlib.sha256(shard.read_bytes()).hexdigest()
        for shard in sorted(transaction_dir.glob("*.json"))
        if shard.is_file()
    }

def _ledger_confirmation_state(
    static_path: Path,
    *,
    shard_digests: dict[str, str] | None = None,
) -> dict[str, Any]:
    digests = shard_digests if shard_digests is not None else _transaction_shard_digests(static_path)
    try:
        static_payload = json.loads(static_path.read_text(encoding="utf-8"))
        updated_at = (static_payload.get("metadata", {}) or {}).get("updated_at")
    except Exception:
        updated_at = None
    return {
        "updated_at": updated_at,
        "static_sha256": hashlib.sha256(static_path.read_bytes()).hexdigest(),
        "transaction_shards_sha256": hashlib.sha256(
            json.dumps(sorted(digests.items()), separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
    }

def _load_revision_state(path: Path) -> dict[str, Any]:
    expanded = expand_path(path)
    payload = json.loads(expanded.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("accounts JSON must be an object with profile context and accounts")
    accounts = payload.get("accounts")
    errors = validate_snapshot_accounts(accounts, path="accounts")
    if errors:
        raise ValueError("invalid accounts file: " + "; ".join(errors))
    base_currency = payload.get("base_currency")
    timezone_name = payload.get("timezone")
    if not isinstance(base_currency, str) or not base_currency:
        raise ValueError("accounts JSON base_currency is required")
    if not isinstance(timezone_name, str) or not timezone_name:
        raise ValueError("accounts JSON timezone is required")
    return {
        "accounts": copy_json(accounts),
        "base_currency": base_currency.upper(),
        "timezone": timezone_name,
    }

def _account_for_patch(accounts: list[dict[str, Any]], reference: str) -> dict[str, Any]:
    id_matches = [account for account in accounts if account.get("id") == reference]
    if id_matches:
        return id_matches[0]
    name_matches = [account for account in accounts if account.get("name") == reference]
    if len(name_matches) == 1:
        return name_matches[0]
    if len(name_matches) > 1:
        raise ValueError(f"account reference is ambiguous: {reference}")
    raise ValueError(f"account not found in historical state: {reference}")

def _apply_balance_patches(
    accounts: list[dict[str, Any]], values: list[str] | None
) -> list[dict[str, Any]]:
    result = copy_json(accounts)
    seen: set[str] = set()
    for raw in values or []:
        reference, separator, amount = raw.partition("=")
        reference = reference.strip()
        if not separator or not reference or not amount.strip():
            raise ValueError("account balance patch must use ACCOUNT=AMOUNT")
        account = _account_for_patch(result, reference)
        account_id = str(account.get("id"))
        if account_id in seen:
            raise ValueError(f"duplicate account balance patch: {reference}")
        seen.add(account_id)
        currency = str(account.get("currency") or "CNY").upper()
        account["balance_minor"] = require_nonnegative_minor(
            parse_amount_minor(amount, currency),
            field=f"balance for {reference}",
        )
    return result

def cmd_revise_balance_snapshot(args: argparse.Namespace) -> int:
    try:
        book = load_book(args.book)
        if (
            type(book.get("schema_version")) is not int
            or book.get("schema_version") != STATIC_SCHEMA_VERSION
        ):
            raise UnsupportedStaticSchema(
                f"static schema version {STATIC_SCHEMA_VERSION} is required"
            )
        errors = validate_book_data(book) + validate_transaction_shards(args.book)
        if errors:
            raise ValueError("ledger must be valid before revision: " + "; ".join(errors))
        current_month = natural_month(book.get("profile"))
        if args.month >= current_month:
            raise ValueError("only a completed natural month can be revised")

        base = resolved_snapshot(book, args.month)
        if args.accounts_json:
            supplied_state = _load_revision_state(args.accounts_json)
            accounts = supplied_state["accounts"]
            source_month = None
            base_currency = supplied_state["base_currency"]
            timezone_name = supplied_state["timezone"]
        elif base.get("status") == "available":
            accounts = copy_json(base["accounts"])
            source_month = str(base["source_month"])
            base_currency = str(base.get("base_currency") or "CNY")
            timezone_name = str(base.get("timezone") or "Asia/Shanghai")
        else:
            raise ValueError(
                "a complete --accounts-json state is required when no prior snapshot is available"
            )
        if not args.account_balance and not args.accounts_json:
            raise ValueError("provide --account-balance or --accounts-json")
        accounts = _apply_balance_patches(accounts, args.account_balance)

        candidate = copy_json(book)
        snapshot = append_historical_revision(
            candidate,
            month=args.month,
            accounts=accounts,
            reason=args.reason,
            source_month=source_month,
            base_currency=base_currency,
            timezone_name=timezone_name,
        )
        preview = {
            "selected_month": args.month,
            "source_month": source_month,
            "previous_revision": base.get("revision") if base.get("source_month") == args.month else None,
            "ledger_state": _ledger_confirmation_state(_static_book_path(args.book)),
            "snapshot": snapshot,
            "summary": snapshot_summary(snapshot),
        }
    except Exception as exc:
        print_json(error_result(str(exc), code="invalid_balance_snapshot_revision"))
        return 1

    should_write, rc = require_write_confirmation(
        args,
        record_type="balance_snapshot_revision",
        record=preview,
    )
    if not should_write:
        return int(rc)
    static_path = _static_book_path(args.book)
    try:
        with _exclusive_book_lock(static_path):
            if _ledger_confirmation_state(static_path) != preview["ledger_state"]:
                print_json(
                    error_result(
                        "the ledger changed after preview; preview it again before confirmation",
                        code="preview_changed",
                    )
                )
                return 1
            _save_static_book_locked(static_path, candidate)
    except Exception as exc:
        print_json(error_result(str(exc), code="balance_snapshot_revision_failed"))
        return 1
    print_json(
        {
            "status": "revised",
            "record_type": "balance_snapshot",
            "month": args.month,
            "revision": snapshot["revision"],
            "snapshot": snapshot,
        }
    )
    return 0

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="Create account-book.json and runtime directories")
    init.add_argument("--book", type=Path, required=True)
    init.add_argument("--template", type=Path)
    init.add_argument("--force", action="store_true")
    init.set_defaults(func=cmd_init)

    validate = sub.add_parser("validate", help="Validate account-book.json")
    validate.add_argument("--book", type=Path, required=True)
    validate.set_defaults(func=cmd_validate)

    revise_snapshot = sub.add_parser(
        "revise-balance-snapshot",
        help="Preview or append a confirmed revision for a completed month",
    )
    revise_snapshot.add_argument("--book", type=Path, required=True)
    revise_snapshot.add_argument("--month", required=True, help="Completed natural month as YYYY-MM")
    revise_snapshot.add_argument(
        "--account-balance",
        action="append",
        help="Patch an existing historical account as ACCOUNT=AMOUNT; repeat as needed",
    )
    revise_snapshot.add_argument(
        "--accounts-json",
        type=Path,
        help="Complete account-state array, required when no earlier snapshot exists",
    )
    revise_snapshot.add_argument("--reason", required=True)
    add_bound_confirmation_args(revise_snapshot)
    revise_snapshot.set_defaults(func=cmd_revise_balance_snapshot)

    tx = sub.add_parser("add-transaction", help="Preview or write a confirmed transaction")
    tx.add_argument("--book", type=Path, required=True)
    tx.add_argument("--id")
    tx.add_argument("--date", default="today")
    tx.add_argument("--kind", choices=["income", "expense", "transfer"], required=True)
    tx.add_argument("--amount", required=True)
    tx.add_argument("--currency", default="CNY")
    tx.add_argument("--base-amount")
    tx.add_argument("--exchange-rate-id")
    tx.add_argument("--title", required=True)
    tx.add_argument("--merchant")
    tx.add_argument("--category", required=True)
    tx.add_argument("--account")
    tx.add_argument("--to-account", help="Destination account for kind=transfer")
    tx.add_argument("--subscription-id")
    tx.add_argument("--tag", action="append")
    tx.add_argument("--notes")
    tx.add_argument("--needs-review", action="store_true")
    tx.add_argument("--review-reason")
    tx.add_argument("--source-type", choices=["manual", "chat", "receipt", "subscription", "import"])
    tx.add_argument("--source-text")
    tx.add_argument("--duplicate-window-days", type=int, default=3)
    tx.add_argument("--no-balance-update", action="store_true", help="Record transaction without updating account balances")
    add_confirmation_args(tx)
    tx.set_defaults(func=cmd_add_transaction)

    account = sub.add_parser("upsert-account", help="Preview or write an account/balance")
    account.add_argument("--book", type=Path, required=True)
    account.add_argument("--id", required=True)
    account.add_argument("--name", required=True)
    account.add_argument("--type", choices=["asset", "liability", "receivable"], required=True)
    account.add_argument("--currency", default="CNY")
    account.add_argument("--balance", required=True)
    account.add_argument("--description")
    account.add_argument("--display-group")
    account.add_argument("--inactive", action="store_true")
    add_confirmation_args(account)
    account.set_defaults(func=cmd_upsert_account)

    budget = sub.add_parser("upsert-budget", help="Preview or write a budget")
    budget.add_argument("--book", type=Path, required=True)
    budget.add_argument("--id", required=True)
    budget.add_argument("--name", required=True)
    budget.add_argument("--group", default="daily")
    budget.add_argument("--category", required=True)
    budget.add_argument("--period", choices=["monthly"], default="monthly")
    budget.add_argument("--limit", required=True)
    budget.add_argument("--currency", default="CNY")
    budget.add_argument("--inactive", action="store_true")
    add_confirmation_args(budget)
    budget.set_defaults(func=cmd_upsert_budget)

    category = sub.add_parser("upsert-category", aliases=["add-category"], help="Preview or write a category")
    category.add_argument("--book", type=Path, required=True)
    category.add_argument("--id")
    category.add_argument("--name", required=True)
    category.add_argument("--group", default="life")
    category.add_argument("--kind", choices=["income", "expense", "transfer", "mixed"], default="expense")
    category.add_argument("--description")
    category.add_argument("--inactive", action="store_true")
    add_confirmation_args(category)
    category.set_defaults(func=cmd_upsert_category)

    subp = sub.add_parser("add-subscription", help="Preview or write a subscription")
    subp.add_argument("--book", type=Path, required=True)
    subp.add_argument("--id")
    subp.add_argument("--name", required=True)
    subp.add_argument("--description")
    subp.add_argument("--amount", required=True)
    subp.add_argument("--currency", default="CNY")
    subp.add_argument("--base-amount")
    subp.add_argument("--exchange-rate-id")
    subp.add_argument("--cadence", choices=["weekly", "monthly", "quarterly", "yearly", "custom"], default="monthly")
    subp.add_argument("--next-billing-date")
    subp.add_argument("--category", default="Subscription Services")
    subp.add_argument("--account")
    subp.add_argument("--reminder", choices=["on", "off"], default="on")
    subp.add_argument("--inactive", action="store_true")
    subp.add_argument("--tag", action="append")
    subp.add_argument("--source-type", choices=["manual", "chat", "receipt", "subscription", "import"])
    subp.add_argument("--source-text")
    add_confirmation_args(subp)
    subp.set_defaults(func=cmd_add_subscription)

    fx = sub.add_parser("add-exchange-rate", help="Preview or write an exchange rate")
    fx.add_argument("--book", type=Path, required=True)
    fx.add_argument("--id")
    fx.add_argument("--date", default="today")
    fx.add_argument("--from", dest="from_currency", required=True)
    fx.add_argument("--to", dest="to_currency", required=True)
    fx.add_argument("--rate", required=True)
    fx.add_argument("--source", default="user-provided")
    fx.add_argument("--estimate", action="store_true")
    add_confirmation_args(fx)
    fx.set_defaults(func=cmd_add_exchange_rate)

    review = sub.add_parser("list-review", help="List transactions by persisted review status")
    review.add_argument("--book", type=Path, required=True)
    review.add_argument("--status", choices=["needs_review", "resolved", "clear", "all"], default="needs_review")
    review.set_defaults(func=cmd_list_review)

    flag = sub.add_parser("flag-transaction", help="Preview or persist a review flag on an existing transaction")
    flag.add_argument("--book", type=Path, required=True)
    flag.add_argument("--id", required=True)
    flag.add_argument("--reason", action="append", required=True)
    flag.add_argument("--note")
    add_confirmation_args(flag)
    flag.set_defaults(func=cmd_flag_transaction)

    resolve = sub.add_parser("resolve-review", help="Preview or persist a review resolution")
    resolve.add_argument("--book", type=Path, required=True)
    resolve.add_argument("--id", required=True)
    resolve.add_argument("--resolution", required=True)
    resolve.add_argument("--status", choices=["resolved", "clear"], default="resolved")
    add_confirmation_args(resolve)
    resolve.set_defaults(func=cmd_resolve_review)

    scan = sub.add_parser("scan-anomalies", help="Preview or persist anomaly review flags")
    scan.add_argument("--book", type=Path, required=True)
    scan.add_argument("--window-days", type=int, default=3)
    add_confirmation_args(scan)
    scan.set_defaults(func=cmd_scan_anomalies)

    due_subscriptions = sub.add_parser("list-due-subscriptions", help="List active subscriptions due on or before a date")
    due_subscriptions.add_argument("--book", type=Path, required=True)
    due_subscriptions.add_argument("--date", default="today")
    due_subscriptions.set_defaults(func=cmd_list_due_subscriptions)

    subscription_status = sub.add_parser("set-subscription-status", help="Preview or update whether a subscription is active")
    subscription_status.add_argument("--book", type=Path, required=True)
    subscription_status.add_argument("--subscription", required=True)
    subscription_status_group = subscription_status.add_mutually_exclusive_group(required=True)
    subscription_status_group.add_argument("--active", dest="active", action="store_true")
    subscription_status_group.add_argument("--inactive", dest="active", action="store_false")
    add_confirmation_args(subscription_status)
    subscription_status.set_defaults(func=cmd_set_subscription_status)

    charge = sub.add_parser("charge-subscription", aliases=["record-subscription-charge"], help="Preview or write a confirmed subscription charge transaction")
    charge.add_argument("--book", type=Path, required=True)
    charge.add_argument("--subscription", required=True)
    charge.add_argument("--id")
    charge.add_argument("--date", default="today")
    charge.add_argument("--amount")
    charge.add_argument("--currency")
    charge.add_argument("--base-amount")
    charge.add_argument("--exchange-rate-id")
    charge.add_argument("--account")
    charge.add_argument("--title")
    charge.add_argument("--notes")
    charge.add_argument("--source-text")
    charge.add_argument("--next-billing-date")
    charge.add_argument("--no-balance-update", action="store_true", help="Record charge without updating account balance")
    add_confirmation_args(charge)
    charge.set_defaults(func=cmd_charge_subscription)

    receipt = sub.add_parser("import-receipt", aliases=["receipt-import"], help="Preview or write a confirmed receipt-derived transaction")
    receipt.add_argument("--book", type=Path, required=True)
    receipt.add_argument("--id")
    receipt.add_argument("--receipt-file", type=Path)
    receipt.add_argument("--ocr-json", type=Path)
    receipt.add_argument("--ocr-text-file", type=Path)
    receipt.add_argument("--source-text")
    receipt.add_argument("--date")
    receipt.add_argument("--amount")
    receipt.add_argument("--currency")
    receipt.add_argument("--base-amount")
    receipt.add_argument("--exchange-rate-id")
    receipt.add_argument("--merchant")
    receipt.add_argument("--title")
    receipt.add_argument("--category", required=True)
    receipt.add_argument("--account")
    receipt.add_argument("--payment-method")
    receipt.add_argument("--invoice-number")
    receipt.add_argument("--ocr-engine", default="ocr-and-documents")
    receipt.add_argument("--ocr-confidence", type=float)
    receipt.add_argument("--confidence-threshold", type=float, default=0.85)
    receipt.add_argument("--line-items-json")
    receipt.add_argument("--tag", action="append")
    receipt.add_argument("--notes")
    receipt.add_argument("--needs-review", action="store_true")
    receipt.add_argument("--review-reason", action="append")
    receipt.add_argument("--duplicate-window-days", type=int, default=3)
    receipt.add_argument("--no-balance-update", action="store_true", help="Record receipt without updating account balance")
    add_confirmation_args(receipt)
    receipt.set_defaults(func=cmd_import_receipt)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    book_arg = getattr(args, "book", None)
    if not (args.func is cmd_init and args.force) and book_arg is not None:
        static_path = expand_path(book_arg)
        if static_path.exists():
            try:
                static_payload = json.loads(static_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                static_payload = None
            if (
                isinstance(static_payload, dict)
                and (
                    type(static_payload.get("schema_version")) is not int
                    or static_payload.get("schema_version") != STATIC_SCHEMA_VERSION
                )
            ):
                print_json(
                    error_result(
                        f"static schema version {STATIC_SCHEMA_VERSION} is required",
                        code="unsupported_static_schema",
                    )
                )
                return 1
    try:
        return int(args.func(args))
    except UnsupportedStaticSchema as exc:
        print_json(error_result(str(exc), code="unsupported_static_schema"))
        return 1
    except (OSError, RuntimeError, ValueError) as exc:
        print_json(error_result(str(exc), code="operation_failed"))
        return 1


if __name__ == "__main__":
    sys.exit(main())
