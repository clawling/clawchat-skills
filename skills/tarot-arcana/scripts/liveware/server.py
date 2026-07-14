#!/usr/bin/env python3
"""
tarot-liveware server

Serves the tarot web app and proxies interpretation requests
to the Hermes API Server (running on port 8642).

Usage:
  python3 server.py [--port PORT]
"""

import json
import os
import re
import sys
import uuid
import urllib.request
from datetime import datetime, timezone
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse

# ── Config ────────────────────────────────────────────────────────────────
DEFAULT_PORT = 5080
HERMES_API = "http://127.0.0.1:8642/v1/chat/completions"
HERMES_HOME = Path(os.environ.get("HERMES_HOME", str(Path.home() / ".hermes")))
READINGS_DIR = Path.home() / "tarot-readings"

# Read API key from .env
ENV_PATH = HERMES_HOME / ".env"
API_KEY = ""

if ENV_PATH.exists():
    with open(ENV_PATH) as f:
        for line in f:
            line = line.strip()
            if line.startswith("API_SERVER_KEY="):
                # Strip quotes if present
                val = line.split("=", 1)[1].strip("\"'")
                API_KEY = val
                break

if not API_KEY:
    print("WARNING: API_SERVER_KEY not found in .env. Interpretation will fail.", file=sys.stderr)

# ── Prompts ───────────────────────────────────────────────────────────────
SEND_USER_PROMPT = """## 任务

Tarot liveware生成的塔罗牌解读报告通过 send_message 工具发送给 owner 在 clawchat 最近的对话会话中。

## 工具参数

- tool: send_message
- target: "clawchat"
- message: 用户提供的文本内容（原样传递，不要修改）

## 约束

- 必须实际调用 send_message 工具，不要用文字描述替代工具调用
- 不要添加额外解释或格式化，直接发送

## 兜底

如果 send_message 发送后用户看不到消息内容，解读已同时保存到文件：
~/tarot-readings/latest.json（含完整牌面、解读、reading_id）
Luna 可在对话中主动读取该文件。"""

def save_reading(cards, question, spread, interpretation, reading_id):
    """Save reading files used for history and conversation follow-up.

    The liveware UI and ClawChat delivery are separate surfaces; saved files under
    ~/tarot-readings/ are the reliable handoff when the user asks about a web
    reading later in chat.
    """
    READINGS_DIR.mkdir(parents=True, exist_ok=True)

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    ts_local = datetime.now().strftime("%Y-%m-%d %H:%M")

    # Build card summary for filename
    first = cards[0] if cards else {}
    safe_name = re.sub(r'[\\/:*?"<>|]', '_', first.get("name", "未知"))
    filename = f"{datetime.now().strftime('%Y%m%d-%H%M')}-{safe_name}.md"
    filepath = READINGS_DIR / filename

    # Card details block
    card_lines = []
    for i, c in enumerate(cards):
        orientation = "逆位" if c.get("orientation") == "reversed" else "正位"
        pos = c.get("position", f"位置{i+1}")
        card_lines.append(f"- **{pos}**：{c.get('name', '未知牌')}（{orientation}）")

    content = f"""# 塔罗解读

- 时间：{ts_local}
- 问题：{question or '（未填写）'}
- 牌阵：{'单张' if spread == 1 else '三张'}牌

## 抽牌结果

"""
    content += "\n".join(card_lines) + "\n\n"
    content += interpretation.strip()
    content += "\n"

    filepath.write_text(content, encoding="utf-8")

    # Update index
    index_path = READINGS_DIR / "index.json"
    if index_path.exists():
        index = json.loads(index_path.read_text(encoding="utf-8"))
    else:
        index = []

    index.append({
        "id": reading_id,
        "timestamp": ts,
        "filename": filename,
        "question": question,
        "spread": spread,
        "cards": [
            {"position": c.get("position"), "name": c.get("name"),
             "orientation": "reversed" if c.get("orientation") == "reversed" else "upright"}
            for c in cards
        ],
    })

    index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")

    # Write latest.json for Luna to read in conversation
    latest = {
        "id": reading_id,
        "timestamp": ts,
        "question": question,
        "spread": spread,
        "cards": [
            {"position": c.get("position"), "name": c.get("name"),
             "orientation": "reversed" if c.get("orientation") == "reversed" else "upright"}
            for c in cards
        ],
        "interpretation": interpretation,
    }
    latest_path = READINGS_DIR / "latest.json"
    latest_path.write_text(json.dumps(latest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  → Reading saved: {filepath}", file=sys.stderr)


def _api_call(prompt, timeout=120, max_tokens=4096, user=None):
    """Make one Hermes API Server call and return the assistant message.

    Keep the payload to a single role=user message. The API Server agent already
    has its own system/profile instructions; adding a second system message here
    makes tool-relay prompts less reliable. The optional top-level `user` field
    is caller metadata, not an extra chat message.
    """
    if not API_KEY:
        raise RuntimeError("API_SERVER_KEY not configured in .env")

    payload_obj = {
        "model": "hermes-agent",
        "messages": [
            {"role": "user", "content": prompt}
        ],
        "stream": False,
        "max_tokens": max_tokens,
    }
    if user:
        # OpenAI-compatible caller metadata: the delivery request is made on
        # behalf of the ClawChat owner, while the actual message body still
        # lives in the single role=user message above.
        payload_obj["user"] = str(user)

    payload = json.dumps(payload_obj, ensure_ascii=False).encode("utf-8")

    req = urllib.request.Request(
        HERMES_API,
        data=payload,
        headers={
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json",
        },
        method="POST"
    )

    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        return data["choices"][0]["message"]


def send_to_clawchat(interpretation):
    """Button-triggered ClawChat delivery for an existing interpretation.

    Do not send automatically from /api/interpret. When the user clicks the UI
    button, merge the unchanged SEND_USER_PROMPT and the exact reading text into
    the single role=user message expected by the Hermes API Server.
    """
    send_prompt = f"{SEND_USER_PROMPT}\n\n## 发送内容\n\n{interpretation}"
    _api_call(send_prompt, timeout=60, user="tarot-liveware")


def _build_card_prompt(cards, question, spread):
    """Build card descriptions for the interpret prompt."""
    card_lines = []
    for c in cards:
        orientation = "逆位" if c.get("orientation") == "reversed" else "正位"
        keywords_list = c.get("keywords", [])
        meaning = "、".join(keywords_list) if isinstance(keywords_list, list) else str(keywords_list)
        arcana = c.get("arcana", "")
        suit = c.get("suit") or ""
        num = c.get("number")
        num_str = str(num) if num is not None else ""
        arcana_part = ""
        if arcana == "minor" and suit:
            suit_names = {"wands": "权杖", "cups": "圣杯", "swords": "宝剑", "pentacles": "星币"}
            arcana_part = f" [{suit_names.get(suit, suit)} {num_str}]"
        elif arcana == "major":
            arcana_part = " [大阿尔卡纳]"
        modern_summary = c.get("summaryModern") or c.get("summary") or ""
        card_lines.append(
            f"- {c.get('position', '位置')}：{c.get('name', '未知牌')}（{orientation}）\n"
            f"  关键词：{meaning}{arcana_part}\n"
            f"  现代牌义：{modern_summary}"
        )

    prompt = """## 任务

你正在处理 tarot-arcana liveware 网页提交的一次塔罗解读请求。

liveware 只是网页入口；塔罗分析必须由 Hermes agent 使用 `tarot-arcana` 技能完成，不要把网页服务当成独立的塔罗解读引擎。

## 必须使用的技能

1. 调用 `skill_view(name='tarot-arcana')` 载入技能说明。
2. 调用并遵循这些参考文件：
   - `skill_view(name='tarot-arcana', file_path='references/interpretation-rules.md')`
   - `skill_view(name='tarot-arcana', file_path='references/spreads.md')`
3. 必须按 interpretation-rules 中的读牌层次、看局规则和反思问题规则完成解读。
4. 只解读下面已经提交的牌面；不要重新抽牌，不要编造牌。

## 用户问题

"""
    prompt += f"{question or '（未填写问题）'}\n\n"
    prompt += f"## 已提交牌阵（{spread}张牌）\n\n"
    prompt += "\n".join(card_lines)
    prompt += """\n\n## 输出要求

请提供完整、有结构、温和且有行动建议的塔罗解读。解读内容应当包括：

1. **单牌解读**——对每张牌的含义和位置意义的解读，不只翻译关键词，要读出象征、情绪、能量方向和现实对应
2. **看局分析**——把用户的问题从单一结果拉回关系结构、局势张力、盲点、选择和代价
3. **综合分析**——牌与牌之间的联系和整体故事
4. **建议与反思问题**——基于牌面给出行动指引，并提出 1-3 个帮助用户看清欲望、恐惧、边界、选择或主动权的问题

解读中**不要**出现以下内容：

- 不要单独列出"你问的是什么"或描述用户问题
- 不要说明"牌阵"类型或牌阵说明
- 不要出现解读过程的元说明（如"我将从过去开始分析..."）

把位置意义融入每张牌的解读中，自然连贯。"""
    return prompt


# ── HTTP Handler ──────────────────────────────────────────────────────────
class TarotHandler(SimpleHTTPRequestHandler):

    def __init__(self, *args, **kwargs):
        skill_root = Path(__file__).resolve().parents[2]
        super().__init__(*args, directory=str(skill_root / "assets" / "liveware"), **kwargs)

    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        super().end_headers()

    def _read_body(self):
        """Read request body, handling both Content-Length and chunked TE."""
        length = int(self.headers.get("Content-Length", 0))
        if length > 0:
            return self.rfile.read(length)
        # Chunked transfer encoding (common through proxies/Cloudflare)
        body = b""
        while True:
            line = self.rfile.readline().strip()
            if not line:
                break
            try:
                chunk_size = int(line, 16)
            except ValueError:
                break
            if chunk_size == 0:
                break
            body += self.rfile.read(chunk_size)
            self.rfile.readline()  # trailing CRLF
        return body

    def do_POST(self):
        parsed = urlparse(self.path)

        if parsed.path == "/api/interpret":
            raw = self._read_body()
            if not raw:
                self._send_json(400, {"error": "Empty request body"})
                return
            body = raw.decode("utf-8")
            try:
                data = json.loads(body)
            except json.JSONDecodeError:
                self._send_json(400, {"error": "Invalid JSON"})
                return

            cards = data.get("cards", [])
            question = data.get("question", "")
            spread = len(cards)  # numeric count for prompt display

            # Step 1: Generate interpretation
            try:
                card_prompt = _build_card_prompt(cards, question, spread)
                msg1 = _api_call(card_prompt, timeout=120)
                interpretation = msg1.get("content", "")
            except Exception as e:
                self._send_json(500, {"error": f"解读生成失败: {str(e)}"})
                return

            if not interpretation:
                self._send_json(500, {"error": "解读生成为空"})
                return

            # Save to archive
            reading_id = str(uuid.uuid4())
            save_reading(cards, question, spread, interpretation, reading_id)

            # Return interpretation to frontend. ClawChat delivery is user-triggered
            # by the frontend button via /api/send-to-chat.
            self._send_json(200, {
                "interpretation": interpretation,
                "reading_id": reading_id,
                "sent_to_chat": False,
            })
        elif parsed.path == "/api/send-to-chat":
            raw = self._read_body()
            if not raw:
                self._send_json(400, {"error": "Empty request body"})
                return
            body = raw.decode("utf-8")
            try:
                data = json.loads(body)
            except json.JSONDecodeError:
                self._send_json(400, {"error": "Invalid JSON"})
                return

            interpretation = data.get("interpretation", "")
            reading_id = data.get("reading_id", "")
            if not interpretation or not str(interpretation).strip():
                self._send_json(400, {"error": "Missing interpretation"})
                return

            try:
                send_to_clawchat(str(interpretation))
                print("  → Reading sent to ClawChat", file=sys.stderr)
                self._send_json(200, {"sent_to_chat": True, "reading_id": reading_id})
            except Exception as e:
                self._send_json(500, {"error": f"发送到 ClawChat 失败: {str(e)}"})
        else:
            self._send_json(404, {"error": "Not found"})

    def do_GET(self):
        parsed = urlparse(self.path)

        if parsed.path == "/api/deck":
            deck_path = Path(__file__).resolve().parents[2] / "assets" / "deck.json"
            if deck_path.exists():
                data = deck_path.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            else:
                self._send_json(404, {"error": "deck.json not found"})
            return

        # Redirect / -> /index.html
        if self.path == "/" or self.path == "":
            self.path = "/index.html"
        return super().do_GET()

    def _send_json(self, status, data):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        print(f"[{self.log_date_time_string()}] {fmt % args}", file=sys.stderr)


# ── Main ──────────────────────────────────────────────────────────────────
def main():
    port = int(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[1] == "--port" else DEFAULT_PORT

    server = HTTPServer(("0.0.0.0", port), TarotHandler)
    print(f"✨ Tarot Liveware Server")
    print(f"   Static:  http://127.0.0.1:{port}")
    print(f"   API:     POST http://127.0.0.1:{port}/api/interpret")
    print(f"   Hermes:  {HERMES_API}")
    print(f"   API key: {'✓ configured' if API_KEY else '✗ MISSING'}")
    print()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        server.server_close()


if __name__ == "__main__":
    main()
