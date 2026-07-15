#!/usr/bin/env python3
"""
Personal-account ledger dashboard server.

Purpose
-------
- Serve the committed Svelte entry at `liveware/dist/index.html` and only
  strictly contained generated files beneath `liveware/dist/assets/`.
- Expose raw schema-v3 `GET /api/book` and a bounded
  `GET /api/book?month=YYYY-MM` projection containing one resolved account
  snapshot plus that month's transactions.

Design choices
--------------
- Pure stdlib (no extra packages).
- Bind 127.0.0.1 only by default — public exposure is delegated to a tunnel
  (cloudflared, ngrok, liveware, frp, ...) and is out of scope for this file.
- `--book PATH` selects the ledger; falls back to common defaults but does
  NOT read env (see SKILL.md: the CLI subcommands take `--book` explicitly
  because account_book.py does not parse env either).
- Node is build-time only. Runtime reads committed `dist/` bytes and never
  installs dependencies or invokes a frontend build.

Usage
-----
    python serve.py --host 127.0.0.1 --port 8765 \\
                    --book /path/to/account-book.json

Open http://127.0.0.1:8765/ to view the dashboard.
"""
from __future__ import annotations

import argparse
import json
import mimetypes
import os
import re
import sys
import time
import uuid
from datetime import date
from pathlib import Path
from urllib import error as urlerror
from urllib import request as urlrequest

# Where this file lives — `liveware/serve.py` is the convention.
SKILL_DIR = Path(__file__).resolve().parent
DIST_DIR = SKILL_DIR / "dist"
ASSETS_DIR = DIST_DIR / "assets"
SCRIPTS_DIR = SKILL_DIR.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from balance_history import (  # noqa: E402 - path is anchored above
    STATIC_SCHEMA_VERSION,
    TRANSACTION_SHARD_SCHEMA_VERSION,
    natural_month,
    parse_month,
    resolved_account_state,
    snapshot_months,
)

# Common ledger locations. Order: explicit --book > $HOME/personal-account-management > cwd.
class UnsupportedStaticSchema(ValueError):
    pass


class InvalidStaticLedger(ValueError):
    pass


DEFAULT_BOOK_CANDIDATES = (
    "$HOME/personal-account-management/account-book.json",
    "account-book.json",
)


def _expand(p: str) -> Path:
    return Path(os.path.expandvars(p)).expanduser()


def resolve_book_path(explicit: str | None) -> Path:
    """Pick a ledger path. Prefers an explicit --book arg, otherwise scans
    the conventional locations and returns the first one that exists. Falls
    back to the first configured candidate even if it does not yet exist, so
    the server can boot and the front-end can show an empty book without a
    404 on /api/book."""
    if explicit:
        p = _expand(explicit)
        return p
    for raw in DEFAULT_BOOK_CANDIDATES:
        p = _expand(raw)
        if p.exists():
            return p
    # No existing book — return the first configured candidate
    # default), so the operator can `init` it.
    return _expand(DEFAULT_BOOK_CANDIDATES[0])


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="serve.py",
        description=(
            "Serve the personal-account ledger dashboard. "
            "Binds 127.0.0.1 by default; expose via tunnel for public access."
        ),
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Network interface to bind (default: 127.0.0.1; do NOT expose on 0.0.0.0 without a tunnel)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8765,
        help="TCP port to listen on (default: 8765; liveware-app convention)",
    )
    parser.add_argument(
        "--book",
        help=(
            "Path to account-book.json. If omitted, scans common locations "
            "and falls back to $HOME/personal-account-management/account-book.json."
        ),
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Re-read the ledger on every /api/book request (debug)",
    )
    return parser.parse_args(argv)


class Handler:
    """Minimal http.server handler. No third-party deps."""

    INDEX_FILE = DIST_DIR / "index.html"
    ASSETS_ROOT = ASSETS_DIR
    JSON_HEADERS = {
        "Cache-Control": "no-store",
        "Content-Type": "application/json; charset=utf-8",
    }
    HTML_HEADERS = {
        "Cache-Control": "no-store",
        "Content-Type": "text/html; charset=utf-8",
    }

    def __init__(self, book_path: Path, *, reload: bool = False) -> None:
        self.book_path = book_path
        self.reload = reload
        # Track in-flight /api/analyze requests so the dashboard can disable
        # the button and so a stray second POST gets a clean 409 instead of
        # silently queueing on the single-threaded server. `started_at` is
        # also surfaced in /api/analyze/status so the front-end can show
        # "analysis in progress since X".
        # With ThreadingHTTPServer, /api/analyze can be entered by multiple
        # threads in parallel, so the busy flag must be guarded by a lock
        # to keep it single-flight.
        import threading
        self._analyze_lock: threading.Lock = threading.Lock()
        self._analyze_busy: bool = False
        self._analyze_started_at: float = 0.0
        self._analyze_window: str = ""
        self._analyze_state: str = "idle"
        self._analyze_run_id: str = ""
        self._analyze_finished_at: float = 0.0
        self._analyze_report_url: str = ""
        self._analyze_error: dict[str, str] | None = None
        self._analyze_upstream_status: int | None = None
        self._analyze_stale_after_s: int = 30 * 60
        # Eagerly prime the static reader. Missing data stays an in-memory empty
        # projection; unsupported persisted schemas are reported by API routes.
        try:
            self._read_static()
        except (UnsupportedStaticSchema, InvalidStaticLedger) as exc:
            self._log(str(exc))

    # -- Multi-file book layout ---------------------------------------------
    # The ledger is split across:
    #   - <book_path>             : static portion (accounts, snapshots,
    #                               categories, budgets, subscriptions,
    #                               exchange_rates, profile, metadata)
    #   - <parent>/transactions/  : per-month shards (transactions/YYYY-MM.json)
    # The serve layer stitches them back together for the front-end.

    def _transactions_dir(self) -> Path:
        return self.book_path.parent / "transactions"

    def _month_file_re(self) -> re.Pattern:
        # Lazy compile to keep the import block tidy.
        if not hasattr(self, "_month_re"):
            self._month_re = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])\.json$")
        return self._month_re

    def _list_month_files(self) -> list[Path]:
        d = self._transactions_dir()
        if not d.exists():
            return []
        rx = self._month_file_re()
        out: list[tuple[int, int, Path]] = []
        for entry in d.iterdir():
            if not entry.is_file():
                continue
            m = rx.match(entry.name)
            if not m:
                continue
            out.append((int(m.group(1)), int(m.group(2)), entry))
        out.sort(key=lambda t: (t[0], t[1]))
        return [p for _, _, p in out]

    def _read_transaction_shard(self, path: Path, expected_month: str) -> list[dict] | None:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            self._log(f"shard read error: {path}: {exc}")
            return None
        if not isinstance(data, dict):
            return None
        version = data.get("schema_version")
        if (
            type(version) is not int
            or version != TRANSACTION_SHARD_SCHEMA_VERSION
            or data.get("month") != expected_month
            or not isinstance(data.get("metadata"), dict)
        ):
            return None
        transactions = data.get("transactions")
        if not isinstance(transactions, list) or not all(isinstance(row, dict) for row in transactions):
            return None
        for row in transactions:
            transaction_date = row.get("date")
            if (
                not isinstance(transaction_date, str)
                or re.fullmatch(r"\d{4}-\d{2}-\d{2}", transaction_date) is None
            ):
                return None
            try:
                transaction_month = date.fromisoformat(transaction_date).strftime("%Y-%m")
            except ValueError:
                return None
            if transaction_month != expected_month:
                return None
        return transactions

    def _list_transaction_months(self) -> list[str]:
        # Month discovery is filename-only so this endpoint remains bounded;
        # transaction payload validity is enforced when a shard is read.
        return [entry.stem for entry in self._list_month_files()]

    def _list_months(self, book: dict | None = None) -> list[str]:
        """Return transaction, snapshot, and current natural months."""
        static_book = book if isinstance(book, dict) else self._read_static()
        months = set(self._list_transaction_months())
        months.update(snapshot_months(static_book))
        profile = static_book.get("profile") if isinstance(static_book.get("profile"), dict) else {}
        months.add(natural_month(profile))
        return sorted(months)

    def _read_month_transactions(self, year: int, month: int) -> list[dict]:
        expected_month = f"{year:04d}-{month:02d}"
        path = self._transactions_dir() / f"{expected_month}.json"
        if not path.exists():
            return []
        return self._read_transaction_shard(path, expected_month) or []

    def _empty_book(self) -> dict:
        return {
            "schema_version": STATIC_SCHEMA_VERSION,
            "profile": {"base_currency": "CNY", "timezone": "Asia/Shanghai"},
            "accounts": [],
            "categories": [],
            "budgets": [],
            "transactions": [],
            "subscriptions": [],
            "exchange_rates": [],
            "balance_snapshots": [],
            "metadata": {},
        }

    # -- File readers ----------------------------------------------------------
    def _read_static(self) -> dict:
        """Read just the static book file. Returns empty skeleton if missing."""
        if not self.book_path.exists():
            return self._empty_book()
        try:
            data = json.loads(self.book_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            self._log(f"static book read error: {exc}")
            raise InvalidStaticLedger("the existing static ledger could not be read") from exc
        if not isinstance(data, dict):
            raise InvalidStaticLedger("the existing static ledger root must be an object")
        if (
            type(data.get("schema_version")) is not int
            or data.get("schema_version") != STATIC_SCHEMA_VERSION
        ):
            raise UnsupportedStaticSchema(
                f"static schema version {STATIC_SCHEMA_VERSION} is required"
            )
        return data

    def _read_book(self, month: str | None = None) -> bytes:
        """Read book + transactions, optionally filtered to a single month.

        `month` is "YYYY-MM" (e.g. "2026-07") or None for all months.
        Returns the JSON-serialized merged book.
        """
        book = self._read_static()
        if month is None:
            txs: list[dict] = []
            for shard in self._list_month_files():
                txs.extend(self._read_month_transactions_from_path(shard))
            book["transactions"] = txs
            return json.dumps(book, ensure_ascii=False).encode("utf-8")

        selected_month = parse_month(month)
        year, selected_number = (int(part) for part in selected_month.split("-", 1))
        txs = self._read_month_transactions(year, selected_number)
        account_snapshot = resolved_account_state(book, selected_month)
        book.pop("balance_snapshots", None)
        book["dashboard_month"] = selected_month
        book["current_month"] = natural_month(book.get("profile"))
        book["account_snapshot"] = account_snapshot
        # Never leak present accounts into a historical month projection.
        # Keep `accounts` aligned with the resolved state while clients consume
        # the richer account_snapshot metadata.
        book["accounts"] = account_snapshot["accounts"]
        book["transactions"] = txs
        return json.dumps(book, ensure_ascii=False).encode("utf-8")

    def _read_month_transactions_from_path(self, path: Path) -> list[dict]:
        return self._read_transaction_shard(path, path.stem) or []

    # -- Logging ---------------------------------------------------------------
    @staticmethod
    def _log(msg: str) -> None:
        """Operator-facing stderr log; safe to call in handler methods."""
        print(f"[serve.py] {msg}", file=sys.stderr, flush=True)

    def _analysis_status_locked(self, now: float | None = None) -> dict:
        timestamp = time.time() if now is None else now
        if self._analyze_started_at:
            end = timestamp if self._analyze_busy else (self._analyze_finished_at or timestamp)
            elapsed = max(0.0, end - self._analyze_started_at)
        else:
            elapsed = 0.0
        return {
            "state": self._analyze_state,
            "run_id": self._analyze_run_id,
            "busy": bool(self._analyze_busy),
            "started_at": self._analyze_started_at,
            "finished_at": self._analyze_finished_at,
            "elapsed_s": round(elapsed, 1),
            "window": self._analyze_window,
            "report_url": self._analyze_report_url or None,
            "error": self._analyze_error,
            "upstream_status": self._analyze_upstream_status,
        }

    def _finish_analysis_locked(
        self,
        *,
        run_id: str,
        state: str,
        finished_at: float,
        report_url: str = "",
        error: dict[str, str] | None = None,
        upstream_status: int | None = None,
    ) -> None:
        if self._analyze_run_id != run_id or self._analyze_state != "running":
            return
        self._analyze_busy = False
        self._analyze_state = state
        self._analyze_finished_at = finished_at
        self._analyze_report_url = report_url
        self._analyze_error = error
        self._analyze_upstream_status = upstream_status

    def _expire_stale_analysis_locked(self, now: float) -> None:
        if not self._analyze_busy or not self._analyze_started_at:
            return
        if now - self._analyze_started_at <= self._analyze_stale_after_s:
            return
        self._log(
            f"/api/analyze: marking stale run failed (run_id={self._analyze_run_id}, "
            f"started_at={self._analyze_started_at})"
        )
        self._finish_analysis_locked(
            run_id=self._analyze_run_id,
            state="failed",
            finished_at=now,
            error={
                "code": "analysis_timeout",
                "message": "The analysis exceeded the server time limit. Start it again.",
            },
        )

    def _claim_analysis_locked(self, *, window: str, now: float) -> tuple[str | None, dict]:
        self._expire_stale_analysis_locked(now)
        if self._analyze_busy:
            return None, self._analysis_status_locked(now)
        run_id = uuid.uuid4().hex
        self._analyze_busy = True
        self._analyze_started_at = now
        self._analyze_window = window
        self._analyze_state = "running"
        self._analyze_run_id = run_id
        self._analyze_finished_at = 0.0
        self._analyze_report_url = ""
        self._analyze_error = None
        self._analyze_upstream_status = None
        return run_id, self._analysis_status_locked(now)

    @staticmethod
    def _private_analysis_filename(output_filename: str, run_id: str) -> str:
        return f".{Path(output_filename).stem}.{run_id}.pending.html"

    @staticmethod
    def _error_report_filename(output_filename: str) -> str:
        return output_filename.removesuffix(".html") + ".err.html"

    @staticmethod
    def _remove_if_present(path: Path) -> None:
        try:
            path.unlink()
        except FileNotFoundError:
            pass

    def _publish_analysis_file(self, source: Path, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        backup: Path | None = None
        if destination.exists():
            stamp = time.strftime("%Y-%m-%dT%H-%M-%S", time.gmtime())
            backup = destination.with_name(
                f"{destination.stem}.{stamp}.bak{destination.suffix}"
            )
            index = 2
            while backup.exists():
                backup = destination.with_name(
                    f"{destination.stem}.{stamp}-{index}.bak{destination.suffix}"
                )
                index += 1
            os.replace(destination, backup)
        try:
            os.replace(source, destination)
        except Exception:
            if backup is not None and backup.exists() and not destination.exists():
                os.replace(backup, destination)
            raise

    def _analysis_file_outcome_locked(
        self,
        *,
        run_id: str,
        private_output_filename: str,
        output_filename: str,
        upstream_status: int,
    ) -> tuple[str, str, dict[str, str] | None]:
        reports_dir = self.book_path.parent / "reports"
        private_report = reports_dir / private_output_filename
        private_error = reports_dir / self._error_report_filename(private_output_filename)
        if self._analyze_run_id != run_id or self._analyze_state != "running":
            self._remove_if_present(private_report)
            self._remove_if_present(private_error)
            return "superseded", "", {
                "code": "run_superseded",
                "message": "A newer analysis run owns the report outcome.",
            }

        if private_error.is_file():
            final_error = reports_dir / self._error_report_filename(output_filename)
            self._publish_analysis_file(private_error, final_error)
            self._remove_if_present(private_report)
            return (
                "failed",
                f"/reports/{final_error.name}",
                {"code": "report_failed", "message": "The analysis produced an error report."},
            )
        if upstream_status >= 400:
            self._remove_if_present(private_report)
            return (
                "failed",
                "",
                {"code": "upstream_failed", "message": "The analysis service did not complete the report."},
            )
        if private_report.is_file():
            final_report = reports_dir / output_filename
            self._publish_analysis_file(private_report, final_report)
            return "succeeded", f"/reports/{final_report.name}", None
        return (
            "failed",
            "",
            {"code": "report_missing", "message": "The analysis finished without a report file."},
        )

    def _render_analyze_prompt(self, *, window: str, delivery: str, output_filename: str) -> str:
        """Read the canonical skill prompt template and substitute the
        caller-supplied variables. Returns the rendered system
        prompt to forward to the Hermes API server. Raises FileNotFoundError
        if the prompt template is missing — the caller surfaces a 503.

        The public report base URL is read from the Liveware state file
        next to the account book.

        The notification recipient is NOT injected — the agent figures
        it out at runtime from its own session context (ClawChat Sender
        Metadata) and the standard `send_message` tool target resolver.
        This keeps the prompt deployment-agnostic; the same template
        works for any ClawChat deployment the agent is running in.
        """
        template_path = SKILL_DIR.parent / "prompts" / "finance-analysis" / "SKILL_PROMPT.md"
        template = template_path.read_text(encoding="utf-8")
        # Extract the fenced ```text block under "## System prompt for the agent"
        # to keep the rendered prompt equal to the spec even if the doc gains
        # surrounding prose.
        m = re.search(r"## System prompt for the agent\s*```text\s*(.*?)```", template, re.DOTALL)
        if not m:
            raise RuntimeError("SKILL_PROMPT.md missing '## System prompt for the agent' fenced block")
        prompt_body = m.group(1).strip()

        book_dir = self.book_path.parent
        report_path = book_dir / "reports" / output_filename

        state_file = book_dir / "liveware-dashboard.state.json"
        liveware_url = ""
        if state_file.exists():
            try:
                state = json.loads(state_file.read_text(encoding="utf-8"))
                if isinstance(state, dict):
                    liveware_url = str(state.get("public_url") or "").rstrip("/")
            except (OSError, json.JSONDecodeError):
                liveware_url = ""
        if not liveware_url:
            raise RuntimeError("Liveware public URL is missing; run start_liveware.sh first")

        substitutions = {
            "{STATIC_BOOK_PATH}": str(self.book_path),
            "{TRANSACTIONS_DIR}": str(book_dir / "transactions"),
            "{REPORTS_DIR}": str(book_dir / "reports"),
            "{REPORT_PATH}": str(report_path),
            "{WINDOW}": window,
            "{DELIVERY}": delivery,
            "{OUTPUT_FILENAME}": output_filename,
            "{LIVEWARE_URL}": liveware_url,
        }
        rendered = prompt_body
        for needle, replacement in substitutions.items():
            rendered = rendered.replace(needle, replacement)
        return rendered

    def _call_hermes_api(self, system_prompt: str, *, timeout: int | None = None) -> tuple[int, bytes, dict]:
        """POST the rendered system prompt to the local Hermes API server
        (gateway adapter on port 8642). Returns (status_code, body_bytes,
        headers_dict). The caller is responsible for surfacing the agent
        output to the dashboard — this method only forwards the brief and
        returns whatever the agent produced (the agent writes the report
        HTML to disk in REPORTS_DIR; serve.py gets back the absolute path
        in `assistant.content`).
        """
        api_url = "http://127.0.0.1:8642/v1/chat/completions"
        api_key = ""
        hermes_home = Path(os.environ.get("HERMES_HOME", str(Path.home())))
        env_file = hermes_home / ".env"
        if env_file.exists():
            for line in env_file.read_text(encoding="utf-8").splitlines():
                if line.startswith("API_SERVER_KEY="):
                    api_key = line.split("=", 1)[1].strip()
                    break
        if not api_key:
            raise RuntimeError("API_SERVER_KEY is missing from the active Hermes .env file")

        body = json.dumps(
            {
                "model": "hermes-agent",
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": "Run the analysis specified above."},
                ],
                "temperature": 0.2,
            }
        ).encode("utf-8")

        req = urlrequest.Request(
            api_url,
            data=body,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                # Pin each analysis to a brand-new Hermes session so the
                # gateway does not derive a stable session_id from our
                # (constant) system prompt and concatenate every prior
                # turn's messages into the next request.  Without this
                # header, prompt_tokens grows by 100K+ per call because
                # the agent keeps re-reading the previous report /
                # transactions across turns.
                "X-Hermes-Session-Id": f"finance-analysis-{uuid.uuid4().hex}",
            },
            method="POST",
        )
        read_to = timeout if timeout is not None else 600
        try:
            with urlrequest.urlopen(req, timeout=read_to) as resp:
                return resp.status, resp.read(), dict(resp.headers)
        except urlerror.HTTPError as e:
            return e.code, e.read() if e.fp else b"", dict(e.headers) if e.headers else {}
        except (urlerror.URLError, TimeoutError, ConnectionError) as e:
            return 503, str(e).encode("utf-8"), {"Content-Type": "text/plain; charset=utf-8"}

    # -- Routing ---------------------------------------------------------------
    def _read_asset(self, request_path: str) -> tuple[int, dict, bytes]:
        relative = request_path.removeprefix("/assets/")
        parts = relative.split("/")
        if (
            not relative
            or "%" in relative
            or "\\" in relative
            or ":" in relative
            or any(part in {"", ".", ".."} for part in parts)
        ):
            return 404, {"Content-Type": "text/plain; charset=utf-8"}, b"Not Found"

        assets_root = self.ASSETS_ROOT.resolve()
        requested = assets_root.joinpath(*parts)
        try:
            target = requested.resolve()
            target.relative_to(assets_root)
        except (OSError, ValueError):
            return 404, {"Content-Type": "text/plain; charset=utf-8"}, b"Not Found"
        if requested.is_symlink() or not target.is_file():
            return 404, {"Content-Type": "text/plain; charset=utf-8"}, b"Not Found"

        body = target.read_bytes()
        suffix = target.suffix.lower()
        if suffix == ".js":
            content_type = "text/javascript; charset=utf-8"
        elif suffix == ".css":
            content_type = "text/css; charset=utf-8"
        else:
            content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        return 200, {
            "Cache-Control": "public, max-age=31536000, immutable",
            "Content-Length": str(len(body)),
            "Content-Type": content_type,
            "X-Content-Type-Options": "nosniff",
        }, body

    def route(self, method: str, path: str, *, headers=None, rfile=None) -> tuple[int, dict, bytes]:
        # Allow POST for /api/analyze; everything else stays GET/HEAD.
        if path == "/api/analyze":
            if method != "POST":
                return 405, {"Content-Type": "text/plain; charset=utf-8", "Allow": "POST"}, b"Method Not Allowed"
        elif method not in ("GET", "HEAD"):
            return 405, {"Content-Type": "text/plain; charset=utf-8", "Allow": "GET, HEAD"}, b"Method Not Allowed"

        # Parse query string. We support `?month=YYYY-MM` on /api/book.
        raw_path = path
        if "?" in path:
            path, _, query = path.partition("?")
        else:
            query = ""
        month_param: str | None = None
        month_invalid = False
        if query:
            for part in query.split("&"):
                if not part:
                    continue
                if "=" in part:
                    k, _, v = part.partition("=")
                else:
                    k, v = part, ""
                if k == "month":
                    try:
                        month_param = parse_month(v.strip())
                    except ValueError:
                        month_invalid = True

        if path in ("/", "/index.html"):
            if not self.INDEX_FILE.exists():
                return 500, {"Content-Type": "text/plain; charset=utf-8"}, f"missing {self.INDEX_FILE}".encode("utf-8")
            body = self.INDEX_FILE.read_bytes()
            headers = dict(self.HTML_HEADERS)
            headers["Content-Length"] = str(len(body))
            return 200, headers, body

        if path.startswith("/assets/"):
            return self._read_asset(path)

        if path in {"/api/book", "/api/months", "/api/analyze"}:
            try:
                self._read_static()
            except UnsupportedStaticSchema as exc:
                payload = json.dumps(
                    {"error": "unsupported_static_schema", "message": str(exc)},
                    ensure_ascii=False,
                ).encode("utf-8")
                out = dict(self.JSON_HEADERS)
                out["Content-Length"] = str(len(payload))
                return 409, out, payload
            except InvalidStaticLedger as exc:
                payload = json.dumps(
                    {"error": "invalid_static_ledger", "message": str(exc)},
                    ensure_ascii=False,
                ).encode("utf-8")
                out = dict(self.JSON_HEADERS)
                out["Content-Length"] = str(len(payload))
                return 422, out, payload

        if path == "/api/book":
            if month_invalid:
                payload = json.dumps(
                    {"error": "invalid_month", "message": "month query param must match YYYY-MM"},
                    ensure_ascii=False,
                ).encode("utf-8")
                headers = dict(self.JSON_HEADERS)
                headers["Content-Length"] = str(len(payload))
                return 400, headers, payload
            body = self._read_book(month=month_param)
            headers = dict(self.JSON_HEADERS)
            headers["Content-Length"] = str(len(body))
            return 200, headers, body

        if path == "/api/months":
            book = self._read_static()
            current_month = natural_month(book.get("profile"))
            payload = json.dumps(
                {"months": self._list_months(book), "current_month": current_month},
                ensure_ascii=False,
            ).encode("utf-8")
            headers = dict(self.JSON_HEADERS)
            headers["Content-Length"] = str(len(payload))
            return 200, headers, payload

        if path == "/api/analyze/status":
            with self._analyze_lock:
                now = time.time()
                self._expire_stale_analysis_locked(now)
                status_payload = self._analysis_status_locked(now)
            payload = json.dumps(status_payload, ensure_ascii=False).encode("utf-8")
            out = dict(self.JSON_HEADERS)
            out["Content-Length"] = str(len(payload))
            return 200, out, payload

        if path == "/api/analyze":
            # POST only. Reads {window, delivery, output_filename} from JSON
            # body, renders the skill prompt template, forwards it to the
            # Hermes API server, and returns whatever the agent produced.
            if method != "POST":
                # GET /api/analyze/status-style probes get the busy snapshot
                # below; the only GET-shape on this path that we allow is
                # /api/analyze/status (handled before this block).
                return 405, {"Content-Type": "text/plain; charset=utf-8", "Allow": "POST"}, b"Method Not Allowed"
            if headers is None or rfile is None:
                payload = json.dumps(
                    {"error": "internal_routing_error", "message": "POST handler did not pass request context"},
                    ensure_ascii=False,
                ).encode("utf-8")
                headers_out = {"Content-Type": "application/json; charset=utf-8", "Content-Length": str(len(payload))}
                return 500, headers_out, payload
            # Reject if another analysis is already running. The dashboard
            # disables its button while busy, but this guard catches:
            #   - a stray curl / external caller
            #   - a page reloaded mid-task (button re-enabled in the new tab)
            # Stale-busy recovery: a 30-min-old lock is treated as crashed
            # and cleared. The agent is expected to finish well under 30
            # minutes; if it didn't, the previous owner probably closed the
            # tab and never came back.
            # The check+set is guarded by a lock so two concurrent threads
            # can't both pass through into the long upstream call. The
            # actual claim happens after we've parsed and validated the
            # JSON body — there's no point locking for a malformed
            # request.
            try:
                content_length = int(headers.get("Content-Length", "0") or "0")
            except ValueError:
                content_length = 0
            if content_length <= 0:
                payload = json.dumps(
                    {"error": "missing_body", "message": "POST /api/analyze requires a JSON body"},
                    ensure_ascii=False,
                ).encode("utf-8")
                headers_out = {"Content-Type": "application/json; charset=utf-8", "Content-Length": str(len(payload))}
                return 400, headers_out, payload
            raw_body = rfile.read(content_length)
            try:
                req_body = json.loads(raw_body.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as e:
                payload = json.dumps(
                    {"error": "invalid_json", "message": str(e)},
                    ensure_ascii=False,
                ).encode("utf-8")
                out = {"Content-Type": "application/json; charset=utf-8", "Content-Length": str(len(payload))}
                return 400, out, payload

            if not isinstance(req_body, dict):
                payload = json.dumps(
                    {"error": "invalid_shape", "message": "JSON body must be an object"},
                    ensure_ascii=False,
                ).encode("utf-8")
                out = {"Content-Type": "application/json; charset=utf-8", "Content-Length": str(len(payload))}
                return 400, out, payload

            window = req_body.get("window")
            delivery = req_body.get("delivery", "dashboard only")
            output_filename = req_body.get("output_filename", "analysis-current.html")
            if not isinstance(window, str) or not window.strip():
                payload = json.dumps(
                    {"error": "missing_window", "message": "body.window is required (e.g. 'single month: 2026-07')"},
                    ensure_ascii=False,
                ).encode("utf-8")
                out = {"Content-Type": "application/json; charset=utf-8", "Content-Length": str(len(payload))}
                return 400, out, payload
            if not isinstance(output_filename, str) or "/" in output_filename or "\\" in output_filename or not output_filename.endswith(".html"):
                payload = json.dumps(
                    {
                        "error": "invalid_output_filename",
                        "message": "output_filename must be a flat filename ending in .html (no path separators)",
                    },
                    ensure_ascii=False,
                ).encode("utf-8")
                out = {"Content-Type": "application/json; charset=utf-8", "Content-Length": str(len(payload))}
                return 400, out, payload

            with self._analyze_lock:
                run_id, current_status = self._claim_analysis_locked(
                    window=window.strip(),
                    now=time.time(),
                )
            if run_id is None:
                payload = json.dumps(
                    {
                        "error": "busy",
                        "message": "An analysis is already in progress.",
                        "started_at": current_status["started_at"],
                        "window": current_status["window"],
                        "analysis": current_status,
                    },
                    ensure_ascii=False,
                ).encode("utf-8")
                out = dict(self.JSON_HEADERS)
                out["Content-Length"] = str(len(payload))
                return 409, out, payload

            private_output_filename = self._private_analysis_filename(output_filename, run_id)
            try:
                system_prompt = self._render_analyze_prompt(
                    window=window.strip(),
                    delivery=str(delivery),
                    output_filename=private_output_filename,
                )
            except FileNotFoundError as exc:
                self._log(f"/api/analyze: template missing: {exc}")
                error = {"code": "template_missing", "message": "finance-analysis template not bundled"}
                with self._analyze_lock:
                    self._finish_analysis_locked(
                        run_id=run_id,
                        state="failed",
                        finished_at=time.time(),
                        error=error,
                    )
                    final_status = self._analysis_status_locked()
                payload = json.dumps({"error": error["code"], "message": error["message"], "analysis": final_status}, ensure_ascii=False).encode("utf-8")
                out = dict(self.JSON_HEADERS)
                out["Content-Length"] = str(len(payload))
                return 503, out, payload
            except Exception as exc:
                self._log(f"/api/analyze: prompt render error: {exc}")
                error = {"code": "prompt_render_failed", "message": str(exc)}
                with self._analyze_lock:
                    self._finish_analysis_locked(
                        run_id=run_id,
                        state="failed",
                        finished_at=time.time(),
                        error=error,
                    )
                    final_status = self._analysis_status_locked()
                payload = json.dumps({"error": error["code"], "message": error["message"], "analysis": final_status}, ensure_ascii=False).encode("utf-8")
                out = dict(self.JSON_HEADERS)
                out["Content-Length"] = str(len(payload))
                return 500, out, payload

            try:
                upstream_status, upstream_body, _upstream_headers = self._call_hermes_api(system_prompt)
            except Exception as exc:
                self._log(f"/api/analyze: upstream exception: {exc}")
                upstream_status = 503
                upstream_body = str(exc).encode("utf-8")
            self._log(
                f"/api/analyze: upstream status={upstream_status}, body bytes={len(upstream_body)}, window={window!r}"
            )

            try:
                upstream_json = json.loads(upstream_body.decode("utf-8")) if upstream_body else {}
            except (UnicodeDecodeError, json.JSONDecodeError):
                upstream_json = {"raw": upstream_body.decode("utf-8", errors="replace")}
            assistant_content = ""
            try:
                choices = upstream_json.get("choices") or []
                if choices:
                    assistant_content = (choices[0].get("message") or {}).get("content") or ""
            except (AttributeError, IndexError):
                pass

            with self._analyze_lock:
                try:
                    state, report_url, analysis_error = self._analysis_file_outcome_locked(
                        run_id=run_id,
                        private_output_filename=private_output_filename,
                        output_filename=output_filename,
                        upstream_status=upstream_status,
                    )
                except Exception as exc:
                    self._log(f"/api/analyze: report publish failed: {exc}")
                    state, report_url, analysis_error = (
                        "failed",
                        "",
                        {"code": "report_publish_failed", "message": "The report file could not be published."},
                    )
                if state != "superseded":
                    self._finish_analysis_locked(
                        run_id=run_id,
                        state=state,
                        finished_at=time.time(),
                        report_url=report_url,
                        error=analysis_error,
                        upstream_status=upstream_status,
                    )
                final_status = self._analysis_status_locked()

            response = {
                "upstream_status": upstream_status,
                "report_path_hint": str(self.book_path.parent / "reports" / output_filename),
                "report_url": final_status["report_url"],
                "agent_message": assistant_content,
                "analysis": final_status,
                "raw": upstream_json,
            }
            payload = json.dumps(response, ensure_ascii=False).encode("utf-8")
            out = dict(self.JSON_HEADERS)
            out["Content-Length"] = str(len(payload))
            return (200 if final_status["state"] == "succeeded" else 502), out, payload

        if path == "/healthz":
            payload = json.dumps(
                {"ok": True, "book": str(self.book_path), "book_exists": self.book_path.exists()},
                ensure_ascii=False,
            ).encode("utf-8")
            headers = {"Content-Type": "application/json; charset=utf-8", "Content-Length": str(len(payload))}
            return 200, headers, payload

        # -- Reports viewer ----------------------------------------------------
        # GET /reports/                  -> HTML index of all analysis-*.html
        # GET /reports/<filename>.html   -> serve the report file
        # The reports directory lives next to the ledger. Filenames are
        # constrained by SKILL_PROMPT.md (analysis-YYYY-MM.html), so we
        # enforce a strict allowlist before touching the filesystem.
        if path == "/reports/" or path.startswith("/reports"):
            reports_dir = (self.book_path.parent / "reports").resolve()
            reports_dir.mkdir(parents=True, exist_ok=True)

            # Directory: render a small listing of available reports.
            if path == "/reports/" or path == "/reports":
                entries: list[dict] = []
                rx = re.compile(r"^analysis-(\d{4})-(\d{2})\.html$")
                for f in reports_dir.iterdir():
                    if not f.is_file():
                        continue
                    m = rx.match(f.name)
                    if not m:
                        continue
                    entries.append(
                        {
                            "name": f.name,
                            "year": int(m.group(1)),
                            "month": int(m.group(2)),
                            "size": f.stat().st_size,
                            "mtime": f.stat().st_mtime,
                        }
                    )
                entries.sort(key=lambda e: (e["year"], e["month"]), reverse=True)

                rows = "\n".join(
                    f'<li><a href="/reports/{e["name"]}">{e["name"]}</a>'
                    f' <span class="meta">— {e["size"]:,} bytes — {e["year"]}-{e["month"]:02d}</span></li>'
                    for e in entries
                )
                if not rows:
                    rows = '<li class="empty">No analysis reports yet. Open the dashboard and click "Analysis" to generate the first one.</li>'

                html = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Analysis Reports</title>
<style>
  body {{ font: 15px/1.6 -apple-system, system-ui, sans-serif;
          color: oklch(21% 0.024 235); background: oklch(98% 0.006 220);
          max-width: 720px; margin: 40px auto; padding: 0 20px; }}
  h1 {{ font-size: 28px; margin: 0 0 8px; }}
  p.lead {{ color: oklch(52% 0.018 235); margin: 0 0 20px; }}
  ul {{ list-style: none; padding: 0; }}
  li {{ padding: 12px 16px; margin-bottom: 8px;
        background: white; border: 1px solid oklch(90% 0.007 235);
        border-radius: 10px; }}
  li.empty {{ color: oklch(52% 0.018 235); font-style: italic; }}
  a {{ color: oklch(58% 0.12 170); text-decoration: none; font-weight: 600;
       font-family: ui-monospace, Menlo, monospace; }}
  a:hover {{ text-decoration: underline; }}
  .meta {{ color: oklch(52% 0.018 235); font-size: 13px; }}
  .back {{ display: inline-block; margin-top: 16px; color: oklch(52% 0.018 235);
           text-decoration: none; font-size: 13px; }}
</style>
</head>
<body>
  <h1>Analysis Reports</h1>
  <p class="lead">{len(entries)} reports, sorted by month descending.</p>
  <ul>
    {rows}
  </ul>
  <a class="back" href="/">← Back to dashboard</a>
</body>
</html>
"""
                body = html.encode("utf-8")
                headers_out = {
                    "Content-Type": "text/html; charset=utf-8",
                    "Content-Length": str(len(body)),
                }
                return 200, headers_out, body

            # File: serve an individual report.
            # Strip the "/reports/" prefix; remaining segment is the filename.
            tail = path[len("/reports/"):] if path.startswith("/reports/") else ""
            if not tail or not re.fullmatch(
                r"analysis-\d{4}-(0[1-9]|1[0-2])(?:\.err)?\.html",
                tail,
            ):
                return 404, {"Content-Type": "text/plain; charset=utf-8"}, b"Not Found"

            target = (reports_dir / tail).resolve()
            # Defense-in-depth: reject anything that escapes reports_dir
            # (resolve() can still follow a symlink, so check the parent).
            try:
                target.relative_to(reports_dir)
            except ValueError:
                return 404, {"Content-Type": "text/plain; charset=utf-8"}, b"Not Found"
            if not target.is_file():
                return 404, {"Content-Type": "text/plain; charset=utf-8"}, b"Report not found"

            body = target.read_bytes()
            headers_out = {
                "Content-Type": "text/html; charset=utf-8",
                "Content-Length": str(len(body)),
            }
            return 200, headers_out, body

        # Tell noisy probes the server is alive even on unknown paths.
        _ = raw_path
        return 404, {"Content-Type": "text/plain; charset=utf-8"}, b"Not Found"


def make_handler(book_path: Path, reload: bool):
    """Return an http.server.BaseHTTPRequestHandler subclass bound to the
    given ledger path. Defined inside this module function so the closure
    carries the book_path/reload state."""
    from http.server import BaseHTTPRequestHandler

    handler = Handler(book_path, reload=reload)

    class DashboardHandler(BaseHTTPRequestHandler):
        # Silence the default per-request stderr access log.
        def log_message(self, format: str, *args) -> None:  # noqa: A002 (stdlib name)
            return

        def do_GET(self) -> None:
            status, headers, body = handler.route("GET", self.path)
            self._write(status, headers, body)

        def do_HEAD(self) -> None:
            status, headers, body = handler.route("HEAD", self.path)
            self._write(status, headers, b"")

        def do_POST(self) -> None:
            status, headers, body = handler.route(
                "POST", self.path, headers=self.headers, rfile=self.rfile
            )
            self._write(status, headers, body)

        def _write(self, status: int, headers: dict, body: bytes) -> None:
            try:
                self.send_response(status)
                for k, v in headers.items():
                    if k.lower() == "content-length" and status in (200, 304):
                        self.send_header(k, v)
                # Avoid duplicating Content-Length when status is 304
                if "Content-Length" not in {k for k in headers}:
                    self.send_header("Content-Length", str(len(body)))
                for k, v in headers.items():
                    if k.lower() == "content-length":
                        continue
                    self.send_header(k, v)
                self.end_headers()
                if self.command != "HEAD" and body:
                    self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                # Client disconnected before we finished writing — not an error
                # on our side, just a cancelled request.
                pass

    return DashboardHandler


def main(argv: list[str] | None = None) -> int:
    from http.server import HTTPServer, ThreadingHTTPServer

    args = parse_args(argv)
    book_path = resolve_book_path(args.book)
    print(
        f"[serve.py] book     = {book_path} ({'exists' if book_path.exists() else 'missing — /api/book will return empty ledger'})",
        flush=True,
    )
    print(f"[serve.py] serving  = {Handler.INDEX_FILE}", flush=True)
    print(f"[serve.py] binding  = http://{args.host}:{args.port}/  (127.0.0.1-only; tunnel externally)", flush=True)
    print(f"[serve.py] mode     = ThreadingHTTPServer (concurrent requests; busy state still serializes /api/analyze)", flush=True)

    handler_cls = make_handler(book_path, reload=args.reload)
    # ThreadingHTTPServer = HTTPServer + per-request thread. This is required
    # because /api/analyze blocks the request thread for up to `timeout` seconds
    # while waiting for the upstream agent. Without threading, a slow or hung
    # upstream would freeze every other endpoint (including /api/analyze/status
    # and the dashboard's GET /api/book), making the page appear dead to the
    # user. The analyze endpoint is still effectively single-flight via the
    # _analyze_busy lock on the shared instance state.
    server = ThreadingHTTPServer((args.host, args.port), handler_cls)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[serve.py] shutting down", flush=True)
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
