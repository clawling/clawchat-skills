"""Pure balance-history rules shared by the ledger CLI, analysis, and dashboard."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import re
from typing import Any

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - Python without zoneinfo
    ZoneInfo = None

STATIC_SCHEMA_VERSION = 3
TRANSACTION_SHARD_SCHEMA_VERSION = 2
SNAPSHOT_FIELD = "balance_snapshots"
SNAPSHOT_TYPES = {"automatic", "confirmed_revision"}
ACCOUNT_TYPES = {"asset", "liability", "receivable"}
MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
FALLBACK_TIMEZONE = timezone(timedelta(hours=8))


def _timezone(profile: dict[str, Any] | None):
    name = str((profile or {}).get("timezone") or "Asia/Shanghai")
    if ZoneInfo is not None:
        try:
            return ZoneInfo(name)
        except Exception:
            pass
    return FALLBACK_TIMEZONE


def _require_timezone_name(value: str) -> str:
    name = str(value or "")
    if not name:
        raise ValueError("timezone must be a non-empty IANA name")
    if ZoneInfo is not None:
        try:
            ZoneInfo(name)
        except Exception as exc:
            raise ValueError(f"invalid timezone: {name}") from exc
    return name


def _now(profile: dict[str, Any] | None, value: datetime | None = None) -> datetime:
    tzinfo = _timezone(profile)
    if value is None:
        return datetime.now(tzinfo)
    if value.tzinfo is None:
        return value.replace(tzinfo=tzinfo)
    return value.astimezone(tzinfo)


def natural_month(profile: dict[str, Any] | None, value: datetime | None = None) -> str:
    """Return the calendar YYYY-MM in the profile timezone."""
    return _now(profile, value).strftime("%Y-%m")


def parse_month(value: str) -> str:
    text = str(value or "")
    if not MONTH_RE.fullmatch(text):
        raise ValueError("month must match YYYY-MM")
    return text


def copy_accounts(accounts: Any) -> list[dict[str, Any]]:
    if not isinstance(accounts, list):
        raise ValueError("accounts must be an array")
    return deepcopy(accounts)


def capture_account_context(accounts: Any, *, recorded_at: str) -> list[dict[str, Any]]:
    result = copy_accounts(accounts)
    for account in result:
        if not isinstance(account, dict):
            continue
        account.setdefault("description", "")
        account.setdefault("display_group", str(account.get("name") or "Account"))
        account.setdefault("active", True)
        if not account.get("updated_at"):
            account["updated_at"] = recorded_at
    return result


def validate_snapshot_accounts(accounts: Any, *, path: str = "accounts") -> list[str]:
    errors: list[str] = []
    if not isinstance(accounts, list):
        return [f"{path} must be an array"]
    seen_ids: set[str] = set()
    for index, account in enumerate(accounts):
        item_path = f"{path}[{index}]"
        if not isinstance(account, dict):
            errors.append(f"{item_path} must be an object")
            continue
        for key in (
            "id",
            "name",
            "type",
            "currency",
            "balance_minor",
            "description",
            "display_group",
            "active",
            "updated_at",
        ):
            if key not in account:
                errors.append(f"{item_path} missing {key}")
        account_id = account.get("id")
        if not isinstance(account_id, str) or not account_id:
            errors.append(f"{item_path}.id must be a non-empty string")
        elif account_id in seen_ids:
            errors.append(f"{item_path} duplicate id: {account_id}")
        else:
            seen_ids.add(account_id)
        if not isinstance(account.get("name"), str) or not account.get("name"):
            errors.append(f"{item_path}.name must be a non-empty string")
        if account.get("type") not in ACCOUNT_TYPES:
            errors.append(f"{item_path}.type invalid")
        if not isinstance(account.get("currency"), str) or not account.get("currency"):
            errors.append(f"{item_path}.currency must be a non-empty string")
        if type(account.get("balance_minor")) is not int:
            errors.append(f"{item_path}.balance_minor must be integer minor units")
        elif account["balance_minor"] < 0:
            errors.append(f"{item_path}.balance_minor must be zero or greater")
        if not isinstance(account.get("description"), str):
            errors.append(f"{item_path}.description must be a string")
        if not isinstance(account.get("display_group"), str) or not account.get("display_group"):
            errors.append(f"{item_path}.display_group must be a non-empty string")
        if not isinstance(account.get("active"), bool):
            errors.append(f"{item_path}.active must be boolean")
        try:
            datetime.fromisoformat(str(account.get("updated_at")))
        except Exception:
            errors.append(f"{item_path}.updated_at must be an ISO timestamp")
    return errors


def _snapshot_id(month: str, revision: int) -> str:
    return f"balance_snapshot_{month.replace('-', '')}_r{revision}"


def _profile_context(book: dict[str, Any]) -> tuple[str, str]:
    profile = book.get("profile") if isinstance(book.get("profile"), dict) else {}
    base_currency = str(profile.get("base_currency") or "CNY").upper()
    timezone_name = _require_timezone_name(
        str(profile.get("timezone") or "Asia/Shanghai")
    )
    return base_currency, timezone_name


def _source(source_type: str, source_id: str | None = None) -> dict[str, str]:
    value = {"type": source_type}
    if source_id:
        value["record_id"] = str(source_id)
    return value


def _require_static_schema(book: dict[str, Any]) -> None:
    if (
        type(book.get("schema_version")) is not int
        or book.get("schema_version") != STATIC_SCHEMA_VERSION
    ):
        raise ValueError(f"static schema version {STATIC_SCHEMA_VERSION} is required")


def capture_current_snapshot(
    book: dict[str, Any],
    *,
    recorded_at: datetime | None = None,
    source_type: str = "automatic",
    source_id: str | None = None,
) -> dict[str, Any]:
    """Create or replace the latest revision for the open recorded month."""
    _require_static_schema(book)
    if source_type not in SNAPSHOT_TYPES:
        raise ValueError(f"invalid snapshot source type: {source_type}")
    profile = book.get("profile") if isinstance(book.get("profile"), dict) else {}
    timestamp = _now(profile, recorded_at).isoformat(timespec="seconds")
    month = natural_month(profile, recorded_at)
    base_currency, timezone_name = _profile_context(book)
    accounts = capture_account_context(book.get("accounts", []), recorded_at=timestamp)
    account_errors = validate_snapshot_accounts(accounts)
    if account_errors:
        raise ValueError("invalid account state: " + "; ".join(account_errors))

    snapshots = book.setdefault(SNAPSHOT_FIELD, [])
    if not isinstance(snapshots, list):
        raise ValueError(f"{SNAPSHOT_FIELD} must be an array")
    matching = [row for row in snapshots if isinstance(row, dict) and row.get("month") == month]
    if matching:
        snapshot = max(matching, key=lambda row: int(row.get("revision", 0)))
        snapshot.update(
            {
                "updated_at": timestamp,
                "capture_type": source_type,
                "base_currency": base_currency,
                "timezone": timezone_name,
                "accounts": accounts,
                "source": _source(source_type, source_id),
            }
        )
        mode = "updated"
    else:
        snapshot = {
            "id": _snapshot_id(month, 1),
            "month": month,
            "revision": 1,
            "created_at": timestamp,
            "updated_at": timestamp,
            "capture_type": source_type,
            "reason": "",
            "base_currency": base_currency,
            "timezone": timezone_name,
            "accounts": accounts,
            "source": _source(source_type, source_id),
        }
        snapshots.append(snapshot)
        mode = "created"
    return {"mode": mode, "snapshot": deepcopy(snapshot)}


def append_historical_revision(
    book: dict[str, Any],
    *,
    month: str,
    accounts: list[dict[str, Any]],
    reason: str,
    recorded_at: datetime | None = None,
    source_month: str | None = None,
    base_currency: str | None = None,
    timezone_name: str | None = None,
) -> dict[str, Any]:
    """Append an immutable confirmed revision for a frozen natural month."""
    _require_static_schema(book)
    selected_month = parse_month(month)
    profile = book.get("profile") if isinstance(book.get("profile"), dict) else {}
    current = natural_month(profile, recorded_at)
    if selected_month >= current:
        raise ValueError("historical revisions require a month before the current natural month")
    if not str(reason or "").strip():
        raise ValueError("revision reason is required")
    account_state = copy_accounts(accounts)
    account_errors = validate_snapshot_accounts(account_state)
    if account_errors:
        raise ValueError("invalid revised account state: " + "; ".join(account_errors))

    snapshots = book.setdefault(SNAPSHOT_FIELD, [])
    if not isinstance(snapshots, list):
        raise ValueError(f"{SNAPSHOT_FIELD} must be an array")
    exact = [row for row in snapshots if isinstance(row, dict) and row.get("month") == selected_month]
    revision = max((int(row.get("revision", 0)) for row in exact), default=0) + 1
    timestamp = _now(profile, recorded_at).isoformat(timespec="seconds")
    profile_base_currency, profile_timezone = _profile_context(book)
    recorded_timezone = _require_timezone_name(
        str(timezone_name or profile_timezone)
    )
    snapshot = {
        "id": _snapshot_id(selected_month, revision),
        "month": selected_month,
        "revision": revision,
        "created_at": timestamp,
        "updated_at": timestamp,
        "capture_type": "confirmed_revision",
        "reason": str(reason).strip(),
        "base_currency": str(base_currency or profile_base_currency).upper(),
        "timezone": recorded_timezone,
        "accounts": account_state,
        "source": {
            "type": "confirmed_revision",
            **({"source_snapshot_month": source_month} if source_month else {}),
        },
    }
    snapshots.append(snapshot)
    return deepcopy(snapshot)


def validate_balance_snapshots(value: Any, *, path: str = SNAPSHOT_FIELD) -> list[str]:
    errors: list[str] = []
    if not isinstance(value, list):
        return [f"{path} must be an array"]
    seen_ids: set[str] = set()
    revisions_by_month: dict[str, set[int]] = {}
    for index, snapshot in enumerate(value):
        item_path = f"{path}[{index}]"
        if not isinstance(snapshot, dict):
            errors.append(f"{item_path} must be an object")
            continue
        for key in (
            "id",
            "month",
            "revision",
            "created_at",
            "updated_at",
            "capture_type",
            "base_currency",
            "timezone",
            "accounts",
            "source",
        ):
            if key not in snapshot:
                errors.append(f"{item_path} missing {key}")
        snapshot_id = snapshot.get("id")
        if not isinstance(snapshot_id, str) or not snapshot_id:
            errors.append(f"{item_path}.id must be a non-empty string")
        elif snapshot_id in seen_ids:
            errors.append(f"{item_path} duplicate id: {snapshot_id}")
        else:
            seen_ids.add(snapshot_id)
        month = snapshot.get("month")
        if not isinstance(month, str) or not MONTH_RE.fullmatch(month):
            errors.append(f"{item_path}.month must match YYYY-MM")
        revision = snapshot.get("revision")
        if type(revision) is not int or revision < 1:
            errors.append(f"{item_path}.revision must be a positive integer")
        elif isinstance(month, str) and MONTH_RE.fullmatch(month):
            month_revisions = revisions_by_month.setdefault(month, set())
            if revision in month_revisions:
                errors.append(f"{item_path} duplicate revision {revision} for {month}")
            month_revisions.add(revision)
        if snapshot.get("capture_type") not in SNAPSHOT_TYPES:
            errors.append(f"{item_path}.capture_type invalid")
        for field in ("created_at", "updated_at"):
            try:
                datetime.fromisoformat(str(snapshot.get(field)))
            except Exception:
                errors.append(f"{item_path}.{field} must be an ISO timestamp")
        if not isinstance(snapshot.get("base_currency"), str) or not snapshot.get("base_currency"):
            errors.append(f"{item_path}.base_currency must be a non-empty string")
        if not isinstance(snapshot.get("timezone"), str) or not snapshot.get("timezone"):
            errors.append(f"{item_path}.timezone must be a non-empty string")
        else:
            try:
                _require_timezone_name(snapshot["timezone"])
            except ValueError:
                errors.append(f"{item_path}.timezone must be a valid IANA timezone")
        if not isinstance(snapshot.get("source"), dict):
            errors.append(f"{item_path}.source must be an object")
        errors.extend(validate_snapshot_accounts(snapshot.get("accounts"), path=f"{item_path}.accounts"))
    for month, revisions in revisions_by_month.items():
        expected = set(range(1, max(revisions, default=0) + 1))
        if revisions != expected:
            errors.append(f"{path} revisions for {month} must be contiguous from 1")
    return errors


def _snapshot_row_is_resolvable(row: Any) -> bool:
    if not isinstance(row, dict):
        return False
    if not isinstance(row.get("id"), str) or not row.get("id"):
        return False
    month = row.get("month")
    revision = row.get("revision")
    if not isinstance(month, str) or not MONTH_RE.fullmatch(month):
        return False
    if type(revision) is not int or revision < 1:
        return False
    if row.get("capture_type") not in SNAPSHOT_TYPES:
        return False
    if not isinstance(row.get("source"), dict):
        return False
    if validate_snapshot_accounts(row.get("accounts"), path="accounts"):
        return False
    if not isinstance(row.get("base_currency"), str) or not row.get("base_currency"):
        return False
    if not isinstance(row.get("timezone"), str) or not row.get("timezone"):
        return False
    try:
        _require_timezone_name(row["timezone"])
    except ValueError:
        return False
    try:
        datetime.fromisoformat(str(row.get("created_at")))
        datetime.fromisoformat(str(row.get("updated_at")))
    except Exception:
        return False
    return True


def _resolvable_snapshot_rows(book: dict[str, Any]) -> list[dict[str, Any]]:
    snapshots = book.get(SNAPSHOT_FIELD, [])
    if not isinstance(snapshots, list):
        return []
    shaped = [row for row in snapshots if _snapshot_row_is_resolvable(row)]
    id_counts: dict[str, int] = {}
    by_month: dict[str, list[dict[str, Any]]] = {}
    for row in shaped:
        snapshot_id = str(row["id"])
        id_counts[snapshot_id] = id_counts.get(snapshot_id, 0) + 1
        by_month.setdefault(str(row["month"]), []).append(row)

    resolvable: list[dict[str, Any]] = []
    for rows in by_month.values():
        unique_rows = [row for row in rows if id_counts[str(row["id"])] == 1]
        revisions = [int(row["revision"]) for row in unique_rows]
        expected = list(range(1, max(revisions, default=0) + 1))
        if not revisions or sorted(revisions) != expected:
            continue
        resolvable.extend(unique_rows)
    return resolvable


def _resolved_snapshot_from_rows(rows: list[dict[str, Any]], month: str) -> dict[str, Any]:
    selected_month = parse_month(month)
    latest_by_month: dict[str, dict[str, Any]] = {}
    for row in rows:
        row_month = str(row["month"])
        revision = int(row["revision"])
        current = latest_by_month.get(row_month)
        if current is None or revision > int(current.get("revision", 0)):
            latest_by_month[row_month] = row
    eligible = [value for key, value in latest_by_month.items() if key <= selected_month]
    if not eligible:
        return {
            "status": "unavailable",
            "selected_month": selected_month,
            "source_month": None,
            "revision": None,
            "created_at": None,
            "updated_at": None,
            "capture_type": None,
            "reason": "",
            "carried_forward": False,
            "restated": False,
            "accounts": [],
        }
    snapshot = max(eligible, key=lambda row: str(row["month"]))
    source_month = str(snapshot["month"])
    return {
        "status": "available",
        "selected_month": selected_month,
        "source_month": source_month,
        "revision": int(snapshot["revision"]),
        "created_at": snapshot.get("created_at"),
        "updated_at": snapshot.get("updated_at"),
        "capture_type": snapshot.get("capture_type"),
        "reason": snapshot.get("reason", ""),
        "carried_forward": source_month != selected_month,
        "restated": snapshot.get("capture_type") == "confirmed_revision" or int(snapshot["revision"]) > 1,
        "base_currency": snapshot.get("base_currency"),
        "timezone": snapshot.get("timezone"),
        "accounts": copy_accounts(snapshot.get("accounts", [])),
    }


def resolved_snapshot(book: dict[str, Any], month: str) -> dict[str, Any]:
    """Resolve the latest trusted state at or before a selected month."""
    _require_static_schema(book)
    return _resolved_snapshot_from_rows(_resolvable_snapshot_rows(book), month)


def resolved_account_state(book: dict[str, Any], month: str) -> dict[str, Any]:
    """Resolve a schema-v3 account state for the selected natural month."""
    _require_static_schema(book)
    selected_month = parse_month(month)
    profile = book.get("profile") if isinstance(book.get("profile"), dict) else {}
    rows = _resolvable_snapshot_rows(book)
    months = sorted({str(row["month"]) for row in rows})
    result = _resolved_snapshot_from_rows(rows, selected_month)
    result.update(
        {
            "history_enabled": True,
            "tracking_started_month": months[0] if months else None,
            "base_currency": str(
                result.get("base_currency") or profile.get("base_currency") or "CNY"
            ).upper(),
            "timezone": str(
                result.get("timezone") or profile.get("timezone") or "Asia/Shanghai"
            ),
        }
    )
    return result


def snapshot_months(book: dict[str, Any]) -> list[str]:
    _require_static_schema(book)
    return sorted({str(row["month"]) for row in _resolvable_snapshot_rows(book)})


def snapshot_summary(snapshot: dict[str, Any]) -> dict[str, Any]:
    accounts = snapshot.get("accounts", []) if isinstance(snapshot.get("accounts"), list) else []
    base_currency = str(snapshot.get("base_currency") or "CNY").upper()
    base_net_worth_minor = 0
    foreign_balances: dict[str, int] = {}
    for account in accounts:
        if not isinstance(account, dict) or account.get("active", True) is False:
            continue
        balance = account.get("balance_minor")
        if not isinstance(balance, int):
            continue
        signed = -abs(balance) if account.get("type") == "liability" else balance
        currency = str(account.get("currency") or base_currency).upper()
        if currency == base_currency:
            base_net_worth_minor += signed
        else:
            foreign_balances[currency] = foreign_balances.get(currency, 0) + signed
    return {
        "month": snapshot.get("month") or snapshot.get("source_month"),
        "revision": snapshot.get("revision"),
        "account_count": len(accounts),
        "base_currency": base_currency,
        "base_net_worth_minor": base_net_worth_minor,
        "foreign_balances_minor": foreign_balances,
    }
