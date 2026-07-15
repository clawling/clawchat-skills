#!/usr/bin/env python3
"""OfficeCLI live preview directory for Liveware.

Lists Office files, creates new files, starts officecli watch processes on
demand, and proxies each preview under /preview/<doc-id>/.
"""

from __future__ import annotations

import hashlib
import html
import http.client
import json
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import shutil
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


DOC_EXTS = {".docx", ".pptx", ".xlsx"}


def default_live_home() -> Path:
    hermes_home = os.environ.get("HERMES_HOME") or str(Path.home() / ".hermes")
    return Path(hermes_home) / "workspace" / "office-live"


OFFICE_LIVE_HOME = Path(os.environ.get("OFFICE_LIVE_HOME", str(default_live_home()))).expanduser()
DEFAULT_ROOTS = [str(OFFICE_LIVE_HOME / "documents")]
DEFAULT_STATE_DIR = str(OFFICE_LIVE_HOME / ".state")
DEFAULT_ARCHIVE_DIR = str(OFFICE_LIVE_HOME / "archive")


def office_bin() -> str:
    configured = os.environ.get("OFFICE_BIN")
    if configured:
        return configured
    found = shutil.which("officecli")
    if found:
        return found
    candidates = [
        Path("~/.local/bin/officecli").expanduser(),
        Path("~/home/.local/bin/officecli").expanduser(),
    ]
    for candidate in candidates:
        if candidate.exists() and os.access(candidate, os.X_OK):
            return str(candidate)
    return str(candidates[0])


OFFICE_BIN = office_bin()
PORT_BASE = int(os.environ.get("OFFICE_PREVIEW_PORT_BASE", "26400"))
PORT_SPAN = int(os.environ.get("OFFICE_PREVIEW_PORT_SPAN", "200"))
WEB_DIR = Path(__file__).resolve().parent.parent / "assets" / "web"
STATIC_TYPES = {
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".html": "text/html; charset=utf-8",
    ".svg": "image/svg+xml",
}
EXCLUDED_DIRS = {
    ".cache",
    ".clawling",
    ".git",
    ".local",
    ".npm",
    ".officecli",
    ".ssh",
    "audio_cache",
    "clawchat-skills",
    "cron",
    "hooks",
    "image_cache",
    "logs",
    "lost+found",
    "memories",
    "pairing",
    "plugins",
    "sessions",
    "skills",
    "skins",
}


def state_dir() -> Path:
    path = Path(os.environ.get("OFFICE_LIVE_STATE_DIR", DEFAULT_STATE_DIR))
    path.mkdir(parents=True, exist_ok=True)
    return path


def state_path() -> Path:
    return state_dir() / "state.json"


def share_requests_path() -> Path:
    return state_dir() / "share-requests.jsonl"


def liveware_app_state_path() -> Path:
    return Path.home() / ".clawling" / "apps" / "clawchat-officecli.json"


def load_state() -> dict:
    try:
        return json.loads(state_path().read_text())
    except Exception:
        return {"watches": {}, "docs": {}}


def save_state(state: dict) -> None:
    tmp = state_path().with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2, sort_keys=True))
    tmp.replace(state_path())


def append_share_request(record: dict) -> None:
    path = share_requests_path()
    line = json.dumps(record, ensure_ascii=False, sort_keys=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def dotenv_value(path: Path, key: str) -> str:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return ""
    prefix = f"{key}="
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or not stripped.startswith(prefix):
            continue
        value = stripped[len(prefix):].strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        return value
    return ""


def hermes_api_key() -> str:
    for key in ("OFFICE_HERMES_API_KEY", "API_SERVER_KEY"):
        value = os.environ.get(key, "").strip()
        if value:
            return value
    hermes_home_str = os.environ.get("HERMES_HOME") or str(Path.home() / ".hermes")
    hermes_home = Path(hermes_home_str)
    for env_path in (hermes_home / ".env", hermes_home / "home" / ".env"):
        value = dotenv_value(env_path, "API_SERVER_KEY")
        if value:
            return value
    return ""


def hermes_api_url() -> str:
    configured = os.environ.get("OFFICE_HERMES_API_URL") or os.environ.get("API_SERVER_URL")
    if configured:
        return configured.rstrip("/")
    host = os.environ.get("API_SERVER_HOST", "127.0.0.1")
    port = os.environ.get("API_SERVER_PORT", "8642")
    if host in {"0.0.0.0", "::"}:
        host = "127.0.0.1"
    return f"http://{host}:{port}"


def share_prompt(record: dict) -> str:
    return (
        "A user clicked Send in the Office Liveware browser directory.\n\n"
        "Use the send_message tool to send the Office file below to ClawChat. "
        "Call send_message with target exactly \"clawchat\" and pass the "
        "message content verbatim, including the MEDIA directive. Do not use "
        "hermes send, curl, Liveware, "
        "OfficeCLI watch APIs, or the directory server for delivery. Do not "
        "edit Office files for this request.\n\n"
        f"File: {record['file']}\n"
        f"Local file path: {record['path']}\n"
        f"Preview URL: {record['previewUrl']}\n\n"
        "Message to send:\n"
        "---\n"
        f"{record['message']}\n"
        "---\n\n"
        "After the send_message call is complete, reply only with [SENT]. "
        "If delivery fails, reply only with [FAILED] and a short reason."
    )


def submit_share_prompt(record: dict) -> dict:
    api_key = hermes_api_key()
    if not api_key:
        raise RuntimeError("API_SERVER_KEY is not available in the environment or HERMES_HOME/.env")

    payload = {
        "model": "hermes-agent",
        "session_id": f"office-liveware-send-{record['id']}",
        "instructions": (
            "You are receiving an internal Office Liveware request. "
            "Use tools when needed. Keep the final response short."
        ),
        "input": share_prompt(record),
    }
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        f"{hermes_api_url()}/v1/runs",
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Idempotency-Key": record["id"],
            "X-Hermes-Session-Key": "office-liveware-send",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            response_body = response.read().decode("utf-8", errors="replace")
            return {"status": response.status, "body": response_body}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:1000]
        raise RuntimeError(f"Hermes API returned {exc.code}: {detail}") from exc


def get_share_run_status(run_id: str) -> dict:
    api_key = hermes_api_key()
    if not api_key:
        raise RuntimeError("API_SERVER_KEY is not available in the environment or HERMES_HOME/.env")
    request = urllib.request.Request(
        f"{hermes_api_url()}/v1/runs/{urllib.parse.quote(run_id)}",
        headers={"Authorization": f"Bearer {api_key}"},
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        return json.loads(response.read().decode("utf-8", errors="replace"))


def monitor_share_run(record: dict, run_id: str) -> None:
    deadline = time.time() + int(os.environ.get("OFFICE_HERMES_RUN_POLL_TIMEOUT", "900"))
    last_status = ""
    while time.time() < deadline:
        try:
            payload = get_share_run_status(run_id)
            status = str(payload.get("status") or "")
            last_status = status or last_status
            if status in {"completed", "failed", "cancelled"}:
                output = str(payload.get("output") or payload.get("error") or "")
                record_status = f"hermes_rest_{status}"
                if output.strip().startswith("[FAILED]"):
                    record_status = "hermes_rest_failed"
                append_share_request(
                    {
                        **record,
                        "status": record_status,
                        "runId": run_id,
                        "completedAt": int(time.time()),
                        "agentResponse": output[:1000],
                    }
                )
                return
        except Exception as exc:
            last_status = f"poll_error: {exc}"
        time.sleep(3)
    append_share_request(
        {
            **record,
            "status": "hermes_rest_poll_timeout",
            "runId": run_id,
            "completedAt": int(time.time()),
            "error": last_status or "timeout",
        }
    )


def start_share_run_monitor(record: dict, run_id: str) -> None:
    thread = threading.Thread(
        target=monitor_share_run,
        args=(record, run_id),
        name=f"office-liveware-run-{record.get('id', 'unknown')}",
        daemon=True,
    )
    thread.start()


def archive_dir() -> Path:
    path = Path(os.environ.get("OFFICE_ARCHIVE_DIR", DEFAULT_ARCHIVE_DIR)).expanduser().resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path


def configured_roots() -> list[Path]:
    raw = os.environ.get("OFFICE_DOC_ROOTS")
    roots = [root for root in raw.split(":") if root.strip()] if raw else DEFAULT_ROOTS
    if not roots:
        roots = DEFAULT_ROOTS
    result: list[Path] = []
    for index, root in enumerate(roots):
        path = Path(root).expanduser().resolve()
        if index == 0:
            path.mkdir(parents=True, exist_ok=True)
        if path.is_dir() and path not in result:
            result.append(path)
    return result


def config_payload() -> dict:
    return {
        "liveHome": str(OFFICE_LIVE_HOME.resolve()),
        "docRoots": [str(root) for root in configured_roots()],
        "stateDir": str(state_dir().resolve()),
        "officeBin": OFFICE_BIN,
        "version": Handler.server_version if "Handler" in globals() else "OfficeLiveDirectory/1.0",
    }


def doc_id(path: Path) -> str:
    return hashlib.sha1(str(path.resolve()).encode("utf-8")).hexdigest()[:16]


def is_under(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def safe_doc_path(raw: str) -> Path:
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        candidate = configured_roots()[0] / candidate
    candidate = candidate.resolve()
    if candidate.suffix.lower() not in DOC_EXTS:
        raise ValueError("Only .docx, .pptx, and .xlsx files are supported.")
    if not any(is_under(candidate, root) for root in configured_roots()):
        raise ValueError("Document path must stay inside OFFICE_DOC_ROOTS.")
    return candidate


def iter_docs() -> list[Path]:
    seen: set[Path] = set()
    docs: list[Path] = []
    for root in configured_roots():
        for current, dirs, files in os.walk(root):
            dirs[:] = [
                d
                for d in dirs
                if d not in EXCLUDED_DIRS and not d.startswith(".") and not d.endswith(".tmp")
            ]
            for name in files:
                path = Path(current) / name
                if path.suffix.lower() in DOC_EXTS:
                    resolved = path.resolve()
                    if resolved not in seen:
                        seen.add(resolved)
                        docs.append(resolved)
    return sorted(docs, key=lambda p: (p.parent.as_posix(), p.name.lower()))


def docs_by_id() -> dict[str, Path]:
    docs = {doc_id(path): path for path in iter_docs()}
    state = load_state()
    for key, raw_path in state.get("docs", {}).items():
        try:
            path = Path(raw_path).resolve()
        except Exception:
            continue
        if (
            path.exists()
            and path.suffix.lower() in DOC_EXTS
            and any(is_under(path, root) for root in configured_roots())
        ):
            docs.setdefault(key, path)
    return docs


def remember_doc(path: Path) -> None:
    state = load_state()
    state.setdefault("docs", {})[doc_id(path)] = str(path.resolve())
    save_state(state)


def forget_doc(path: Path) -> None:
    state = load_state()
    key = str(path.resolve())
    doc_key = doc_id(path)
    watches = state.get("watches", {})
    entry = watches.pop(key, None)
    if entry and entry.get("pid"):
        try:
            os.kill(int(entry["pid"]), 15)
        except Exception:
            pass
    docs = state.get("docs", {})
    docs.pop(doc_key, None)
    for remembered_key, remembered_path in list(docs.items()):
        if Path(remembered_path).resolve() == path.resolve():
            docs.pop(remembered_key, None)
    save_state(state)


def port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.25)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def pick_port(state: dict) -> int:
    used = {
        int(entry.get("port"))
        for entry in state.get("watches", {}).values()
        if entry.get("port")
    }
    for port in range(PORT_BASE, PORT_BASE + PORT_SPAN):
        if port not in used and not port_open(port):
            return port
    raise RuntimeError("No free preview ports available.")


def office_env() -> dict[str, str]:
    env = os.environ.copy()
    env["DOTNET_SYSTEM_GLOBALIZATION_INVARIANT"] = "1"
    return env


def ensure_doc(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        subprocess.run(
            [OFFICE_BIN, "create", str(path)],
            env=office_env(),
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )


def public_directory_url() -> str:
    try:
        state = json.loads(liveware_app_state_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    if not isinstance(state, dict) or state.get("registered") is not True:
        return ""
    public_url = state.get("public_url")
    return public_url if isinstance(public_url, str) else ""


def unique_archive_path(path: Path) -> Path:
    stamp = time.strftime("deleted-%Y%m%d-%H%M%S")
    destination_dir = archive_dir() / stamp
    destination_dir.mkdir(parents=True, exist_ok=True)
    destination = destination_dir / path.name
    counter = 1
    while destination.exists():
        destination = destination_dir / f"{path.stem}-{counter}{path.suffix}"
        counter += 1
    return destination


def ensure_watch(path: Path) -> int:
    ensure_doc(path)
    state = load_state()
    key = str(path)
    entry = state.get("watches", {}).get(key)
    if entry:
        port = int(entry.get("port", 0))
        pid = int(entry.get("pid", 0))
        if port and pid and pid_alive(pid) and port_open(port):
            return port

    port = pick_port(state)
    subprocess.run(
        [OFFICE_BIN, "unwatch", str(path)],
        env=office_env(),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    log = (state_dir() / f"{doc_id(path)}.log").open("ab")
    proc = subprocess.Popen(
        [OFFICE_BIN, "watch", str(path), "--port", str(port)],
        env=office_env(),
        stdout=log,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    deadline = time.time() + 8
    while time.time() < deadline:
        if port_open(port):
            state.setdefault("watches", {})[key] = {
                "id": doc_id(path),
                "path": str(path),
                "port": port,
                "pid": proc.pid,
                "started_at": int(time.time()),
            }
            save_state(state)
            return port
        time.sleep(0.25)
    raise RuntimeError(f"officecli watch did not start for {path}")


def rewrite_preview_bytes(body: bytes, content_type: str, prefix: str) -> bytes:
    if not (
        "text/html" in content_type
        or "javascript" in content_type
        or "text/css" in content_type
    ):
        return body
    text = body.decode("utf-8", errors="replace")
    replacements = {
        "EventSource('/": "EventSource('",
        'EventSource("/': 'EventSource("',
        "fetch('/": "fetch('",
        'fetch("/': 'fetch("',
        "url('/": "url('",
        'url("/': 'url("',
        "href='/": "href='",
        'href="/': 'href="',
        "src='/": "src='",
        'src="/': 'src="',
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    if "text/html" in content_type and "<head>" in text:
        text = text.replace("<head>", f'<head><base href="{prefix}">{poll_fallback_script()}', 1)
    return text.encode("utf-8")


def poll_fallback_script() -> str:
    return r"""<script id="office-live-poll-fallback">
(function(){
  var baseline = null;
  var busy = false;
  function fingerprint(html) {
    return String(html)
      .replace(/<script id="office-live-poll-fallback">[\s\S]*?<\/script>/, '')
      .replace(/\s+/g, ' ')
      .trim();
  }
  async function poll() {
    if (busy || document.hidden) return;
    busy = true;
    try {
      var url = location.pathname + '?__office_poll=' + Date.now();
      var res = await fetch(url, { cache: 'no-store' });
      if (!res.ok) return;
      var fp = fingerprint(await res.text());
      if (baseline === null) {
        baseline = fp;
      } else if (fp !== baseline) {
        location.reload();
      }
    } catch (e) {
    } finally {
      busy = false;
    }
  }
  setTimeout(poll, 1200);
  setInterval(poll, 3000);
})();
</script>"""


class Handler(BaseHTTPRequestHandler):
    server_version = "OfficeLiveDirectory/1.0"

    def log_message(self, fmt: str, *args: object) -> None:
        sys.stderr.write("%s - - [%s] %s\n" % (self.address_string(), self.log_date_time_string(), fmt % args))

    def send_text(self, status: int, body: str, content_type: str = "text/html; charset=utf-8") -> None:
        encoded = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def send_json(self, status: int, payload: dict) -> None:
        encoded = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def send_bytes(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def redirect(self, location: str) -> None:
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", location)
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/" or parsed.path == "/index.html":
            self.render_index()
            return
        if parsed.path == "/api/files":
            self.send_json(200, self.files_payload(urllib.parse.parse_qs(parsed.query)))
            return
        if parsed.path == "/api/share-requests":
            self.send_json(200, self.share_requests_payload(urllib.parse.parse_qs(parsed.query)))
            return
        if parsed.path == "/api/config":
            self.send_json(200, config_payload())
            return
        if parsed.path.startswith("/api/") and self.proxy_preview_api_from_referer(parsed):
            return
        if parsed.path.startswith("/assets/"):
            self.serve_static(parsed.path)
            return
        if parsed.path == "/create":
            self.create_doc(urllib.parse.parse_qs(parsed.query))
            return
        if parsed.path.startswith("/preview/"):
            self.proxy_preview(parsed)
            return
        if parsed.path == "/healthz":
            self.send_text(200, "ok\n", "text/plain; charset=utf-8")
            return
        self.send_error(404)

    def do_POST(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path.startswith("/preview/"):
            self.proxy_preview(parsed, self.read_body())
            return
        if parsed.path.startswith("/api/") and self.proxy_preview_api_from_referer(parsed, self.read_body()):
            return
        if parsed.path.startswith("/api/files/") and parsed.path.endswith("/send"):
            self.send_doc_to_clawchat(parsed)
            return
        if parsed.path.startswith("/api/files/") and parsed.path.endswith("/delete"):
            self.delete_doc(parsed, "/delete")
            return
        if parsed.path == "/api/files":
            data = self.read_body().decode("utf-8", errors="replace")
            try:
                path = self.create_doc_from_params(urllib.parse.parse_qs(data))
            except Exception as exc:
                self.send_json(400, {"error": str(exc)})
                return
            self.send_json(201, {"doc": self.file_record(path), "previewUrl": f"/preview/{doc_id(path)}/"})
            return
        if parsed.path == "/create":
            data = self.read_body().decode("utf-8", errors="replace")
            self.create_doc(urllib.parse.parse_qs(data))
            return
        self.send_error(404)

    def do_PUT(self) -> None:
        self.proxy_or_404()

    def do_PATCH(self) -> None:
        self.proxy_or_404()

    def do_DELETE(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path.startswith("/api/files/"):
            self.delete_doc(parsed)
            return
        self.proxy_or_404()

    def do_OPTIONS(self) -> None:
        self.proxy_or_404()

    def read_body(self) -> bytes:
        if self.headers.get("Transfer-Encoding", "").lower() == "chunked":
            chunks: list[bytes] = []
            while True:
                line = self.rfile.readline().strip()
                if not line:
                    continue
                size = int(line.split(b";", 1)[0], 16)
                if size == 0:
                    while True:
                        trailer = self.rfile.readline()
                        if trailer in (b"\r\n", b"\n", b""):
                            break
                    break
                chunks.append(self.rfile.read(size))
                self.rfile.read(2)
            return b"".join(chunks)
        length = int(self.headers.get("Content-Length", "0") or "0")
        return self.rfile.read(length) if length else b""

    def proxy_or_404(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path.startswith("/preview/"):
            self.proxy_preview(parsed, self.read_body())
            return
        if parsed.path.startswith("/api/") and self.proxy_preview_api_from_referer(parsed, self.read_body()):
            return
        self.send_error(404)

    def render_index(self) -> None:
        index = WEB_DIR / "index.html"
        try:
            body = index.read_bytes()
        except OSError:
            self.send_error(500, "Missing web/index.html")
            return
        self.send_bytes(200, body, "text/html; charset=utf-8")

    def serve_static(self, request_path: str) -> None:
        relative = request_path.removeprefix("/assets/").lstrip("/")
        if not relative or "/" in relative or "\\" in relative:
            self.send_error(404)
            return
        path = (WEB_DIR / "assets" / relative).resolve()
        if not is_under(path, WEB_DIR / "assets") or not path.is_file():
            self.send_error(404)
            return
        content_type = STATIC_TYPES.get(path.suffix.lower(), "application/octet-stream")
        self.send_bytes(200, path.read_bytes(), content_type)

    def send_preview_error(self, title: str, detail: str, status: int = 200) -> None:
        template = WEB_DIR / "preview-error.html"
        try:
            body = template.read_text(encoding="utf-8")
        except OSError:
            self.send_text(status, f"{title}\n{detail}\n", "text/plain; charset=utf-8")
            return
        body = (
            body.replace("{{TITLE}}", html.escape(title))
            .replace("{{DETAIL}}", html.escape(detail))
        )
        self.send_text(status, body)

    def render_preview_wrapper(self, doc_key: str, path: Path, parsed: urllib.parse.ParseResult) -> None:
        params = urllib.parse.parse_qs(parsed.query)
        lang = "zh" if params.get("lang", [""])[0] == "zh" else "en"
        copy = {
            "en": {
                "back": "Back",
                "title": "Office Preview",
                "loading": "Loading preview",
            },
            "zh": {
                "back": "返回",
                "title": "Office 预览",
                "loading": "正在加载预览",
            },
        }[lang]
        query = "?lang=zh" if lang == "zh" else ""
        iframe_src = f"/preview/{doc_key}/_watch/{query}"
        back_href = f"/{query}"
        body = f"""<!doctype html>
<html lang="{html.escape(lang)}">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(path.name)} - {html.escape(copy["title"])}</title>
  <style>
    :root {{
      color-scheme: light;
      --border: #d9e1ea;
      --text: #172033;
      --muted: #64748b;
      --bg: #f6f8fb;
      --panel: #ffffff;
      --primary: #245fce;
    }}
    * {{ box-sizing: border-box; }}
    html, body {{ height: 100%; }}
    body {{
      margin: 0;
      overflow: hidden;
      background: var(--bg);
      color: var(--text);
      font-family: Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    .shell {{
      display: grid;
      grid-template-rows: 48px minmax(0, 1fr);
      height: 100vh;
    }}
    .bar {{
      display: grid;
      grid-template-columns: auto minmax(0, 1fr);
      align-items: center;
      gap: 12px;
      border-bottom: 1px solid var(--border);
      background: rgba(255, 255, 255, .96);
      padding: 0 14px;
    }}
    .back {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-width: 68px;
      height: 32px;
      border: 1px solid var(--border);
      border-radius: 6px;
      background: var(--panel);
      color: var(--text);
      font-size: 13px;
      font-weight: 600;
      text-decoration: none;
    }}
    .back:hover {{
      border-color: #b8c5d6;
      color: var(--primary);
    }}
    .name {{
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      font-size: 14px;
      font-weight: 650;
    }}
    iframe {{
      width: 100%;
      height: 100%;
      border: 0;
      background: #fff;
    }}
  </style>
</head>
<body>
  <main class="shell">
    <header class="bar">
      <a class="back" href="{html.escape(back_href)}">{html.escape(copy["back"])}</a>
      <div class="name" title="{html.escape(path.name)}">{html.escape(path.name)}</div>
    </header>
    <iframe src="{html.escape(iframe_src)}" title="{html.escape(path.name)}">{html.escape(copy["loading"])}</iframe>
  </main>
</body>
</html>"""
        self.send_text(200, body)

    def file_record(self, path: Path) -> dict:
        roots = configured_roots()
        root_label = next((root for root in roots if is_under(path, root)), roots[0])
        rel = path.relative_to(root_label)
        stat = path.stat()
        location = str(rel.parent) if str(rel.parent) != "." else ""
        return {
            "id": doc_id(path),
            "name": path.name,
            "extension": path.suffix.lower(),
            "type": path.suffix[1:].upper(),
            "location": location,
            "modified": int(stat.st_mtime),
            "modifiedLabel": time.strftime("%m-%d %H:%M", time.localtime(stat.st_mtime)),
            "previewUrl": f"/preview/{doc_id(path)}/",
        }

    def files_payload(self, query: dict[str, list[str]] | None = None) -> dict:
        docs = iter_docs()
        page_size = 25
        page = 1
        search = ""
        if query:
            try:
                page = max(1, int(query.get("page", ["1"])[0]))
            except (TypeError, ValueError):
                page = 1
            try:
                page_size = int(query.get("pageSize", ["25"])[0])
            except (TypeError, ValueError):
                page_size = 25
            search = query.get("q", [""])[0].strip().lower()
        page_size = min(100, max(1, page_size))
        counts = {".pptx": 0, ".docx": 0, ".xlsx": 0}
        newest = None
        records = []
        doc_count = len(docs)
        for path in docs:
            stat = path.stat()
            counts[path.suffix.lower()] = counts.get(path.suffix.lower(), 0) + 1
            newest = stat.st_mtime if newest is None else max(newest, stat.st_mtime)
            record = self.file_record(path)
            haystack = f"{record['name']} {record['extension']} {record['location']}".lower()
            if not search or search in haystack:
                records.append(record)
        total = len(records)
        total_pages = max(1, (total + page_size - 1) // page_size)
        page = min(page, total_pages)
        start = (page - 1) * page_size
        end = start + page_size
        return {
            "files": records[start:end],
            "pagination": {
                "page": page,
                "pageSize": page_size,
                "total": total,
                "totalPages": total_pages,
                "hasPrevious": page > 1,
                "hasNext": page < total_pages,
                "query": search,
            },
            "stats": {
                "total": doc_count,
                "pptx": counts.get(".pptx", 0),
                "docx": counts.get(".docx", 0),
                "xlsx": counts.get(".xlsx", 0),
                "latest": time.strftime("%Y-%m-%d %H:%M", time.localtime(newest)) if newest else "No files",
            },
        }

    def share_requests_payload(self, query: dict[str, list[str]] | None = None) -> dict:
        limit = 20
        if query:
            try:
                limit = int(query.get("limit", ["20"])[0])
            except (TypeError, ValueError):
                limit = 20
        limit = min(100, max(1, limit))
        requests: list[dict] = []
        path = share_requests_path()
        if path.exists():
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except OSError:
                lines = []
            for line in lines[-limit:]:
                try:
                    requests.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return {"requests": requests, "total": len(requests)}

    def doc_from_api_path(self, parsed: urllib.parse.ParseResult, suffix: str = "") -> tuple[str, Path]:
        prefix = "/api/files/"
        raw = parsed.path.removeprefix(prefix)
        if suffix and raw.endswith(suffix):
            raw = raw[: -len(suffix)]
        doc_key = raw.strip("/")
        if not doc_key:
            raise ValueError("Missing document id")
        path = docs_by_id().get(doc_key)
        if not path:
            raise FileNotFoundError("File is no longer available in the managed document root.")
        return doc_key, path

    def delete_doc(self, parsed: urllib.parse.ParseResult, suffix: str = "") -> None:
        try:
            _, path = self.doc_from_api_path(parsed, suffix)
            destination = unique_archive_path(path)
            forget_doc(path)
            shutil.move(str(path), str(destination))
        except FileNotFoundError as exc:
            self.send_json(404, {"error": str(exc)})
            return
        except Exception as exc:
            self.send_json(500, {"error": str(exc)})
            return
        self.send_json(200, {"deleted": True, "archived": str(destination)})

    def send_doc_to_clawchat(self, parsed: urllib.parse.ParseResult) -> None:
        try:
            doc_key, path = self.doc_from_api_path(parsed, "/send")
        except FileNotFoundError as exc:
            self.send_json(404, {"error": str(exc)})
            return
        except Exception as exc:
            self.send_json(400, {"error": str(exc)})
            return

        base_url = public_directory_url()
        preview_url = f"{base_url}/preview/{doc_key}/" if base_url else f"/preview/{doc_key}/"
        message = (
            f"Office file attached: {path.name}\n"
            f"MEDIA:{path}"
        )
        request_id = hashlib.sha1(f"{time.time()}:{doc_key}:{path}".encode("utf-8")).hexdigest()[:16]
        record = {
            "id": request_id,
            "createdAt": int(time.time()),
            "docId": doc_key,
            "file": path.name,
            "path": str(path),
            "target": "clawchat",
            "previewUrl": preview_url,
            "message": message,
            "status": "submitted_to_hermes",
        }
        try:
            append_share_request(record)
        except Exception as exc:
            self.send_json(500, {"error": f"Could not queue share request: {exc}"})
            return
        try:
            hermes_result = submit_share_prompt(record)
            response_body = hermes_result.get("body", "")
            try:
                response_json = json.loads(response_body)
                run_id = str(response_json.get("run_id") or "")
            except Exception:
                response_json = {}
                run_id = ""
            if not run_id:
                raise RuntimeError(f"Hermes REST did not return run_id: {response_body[:500]}")
            append_share_request(
                {
                    **record,
                    "status": "submitted_to_hermes_rest",
                    "runId": run_id,
                    "submittedAt": int(time.time()),
                }
            )
            start_share_run_monitor(record, run_id)
        except Exception as exc:
            append_share_request(
                {
                    **record,
                    "status": "hermes_rest_failed",
                    "completedAt": int(time.time()),
                    "error": str(exc),
                }
            )
            self.send_json(502, {"error": f"Could not submit to Hermes REST API: {exc}"})
            return

        self.log_message("submitted ClawChat share request %s to Hermes REST for %s", request_id, path.name)
        self.send_json(
            200,
            {
                "sent": False,
                "submittedToHermes": True,
                "submittedVia": "hermes_api_server",
                "runId": run_id,
                "requestId": request_id,
                "target": "clawchat",
                "message": message,
                "previewUrl": preview_url,
            },
        )

    def create_doc(self, params: dict[str, list[str]]) -> None:
        try:
            path = self.create_doc_from_params(params)
        except Exception as exc:
            self.send_error(500, str(exc))
            return
        self.redirect(f"/preview/{doc_id(path)}/")

    def create_doc_from_params(self, params: dict[str, list[str]]) -> Path:
        name = (params.get("name", [""])[0] or "").strip()
        ext = (params.get("ext", [".pptx"])[0] or ".pptx").strip().lower()
        if ext not in DOC_EXTS:
            raise ValueError("Unsupported extension")
        if not name:
            name = time.strftime("untitled-%Y%m%d-%H%M%S")
        clean = "".join(ch for ch in name if ch.isalnum() or ch in ("-", "_", ".", " ")).strip()
        if not clean:
            clean = time.strftime("untitled-%Y%m%d-%H%M%S")
        if Path(clean).suffix.lower() not in DOC_EXTS:
            clean += ext
        path = safe_doc_path(str(configured_roots()[0] / clean))
        ensure_doc(path)
        remember_doc(path)
        return path

    def proxy_preview(self, parsed: urllib.parse.ParseResult, body: bytes = b"") -> None:
        parts = parsed.path.split("/", 3)
        if len(parts) < 3:
            self.send_error(404)
            return
        doc_key = parts[2]
        docs = docs_by_id()
        path = docs.get(doc_key)
        if not path:
            self.send_preview_error(
                "Preview unavailable",
                "This file is no longer available in the managed document root.",
            )
            return
        try:
            port = ensure_watch(path)
        except Exception as exc:
            sys.stderr.write(f"Preview failed for {path}: {exc}\n")
            self.send_preview_error(
                "Preview failed to start",
                "Hermes could not start the Office preview for this file. Ask Hermes to restart the preview or check the document.",
            )
            return

        if len(parts) == 3 or not parts[3]:
            self.render_preview_wrapper(doc_key, path, parsed)
            return
        if parts[3] != "_watch" and not parts[3].startswith("_watch/"):
            self.redirect(f"/preview/{doc_key}/_watch/{parts[3]}")
            return

        upstream_path = "/"
        upstream_tail = parts[3].removeprefix("_watch").lstrip("/")
        if upstream_tail:
            upstream_path += upstream_tail
        if parsed.query:
            upstream_path += "?" + parsed.query

        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
        allowed_request_headers = {
            "accept",
            "cache-control",
            "content-type",
            "pragma",
            "user-agent",
        }
        headers = {k: v for k, v in self.headers.items() if k.lower() in allowed_request_headers}
        try:
            conn.request(self.command, upstream_path, body=body, headers=headers)
            res = conn.getresponse()
            content_type = res.getheader("Content-Type", "")
            self.send_response(res.status, res.reason)
            skip = {"connection", "transfer-encoding", "content-length", "content-encoding"}
            for header, value in res.getheaders():
                lower = header.lower()
                if lower in skip:
                    continue
                if lower == "location" and value.startswith("/"):
                    value = f"/preview/{doc_key}/_watch{value}"
                self.send_header(header, value)
            if "text/event-stream" in content_type:
                self.end_headers()
                while True:
                    chunk = res.readline()
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    self.wfile.flush()
                return
            body = res.read()
            body = rewrite_preview_bytes(body, content_type, f"/preview/{doc_key}/_watch/")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        finally:
            conn.close()

    def proxy_preview_api_from_referer(self, parsed: urllib.parse.ParseResult, body: bytes = b"") -> bool:
        referer = self.headers.get("Referer", "")
        referer_path = urllib.parse.urlparse(referer).path
        if not referer_path.startswith("/preview/"):
            return False
        parts = referer_path.split("/", 3)
        if len(parts) < 3 or not parts[2]:
            return False
        doc_key = parts[2]
        query = f"?{parsed.query}" if parsed.query else ""
        proxy_path = f"/preview/{doc_key}/_watch{parsed.path}{query}"
        self.proxy_preview(urllib.parse.urlparse(proxy_path), body)
        return True


def main() -> int:
    port = int(os.environ.get("OFFICE_DIRECTORY_PORT", "26315"))
    host = os.environ.get("OFFICE_DIRECTORY_HOST", "127.0.0.1")
    configured_roots()[0].mkdir(parents=True, exist_ok=True)
    httpd = ThreadingHTTPServer((host, port), Handler)
    print(f"Office live directory: http://{host}:{port}")
    print("Document roots:", ", ".join(str(root) for root in configured_roots()))
    httpd.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
