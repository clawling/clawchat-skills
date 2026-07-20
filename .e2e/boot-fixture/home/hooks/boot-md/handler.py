import logging
import os
import traceback
from datetime import datetime, timezone
import threading

logger = logging.getLogger("hooks.boot-md")
_lock = threading.Lock()
_started = False

def _audit(message):
    try:
        root = os.environ.get("HERMES_HOME", "/opt/data")
        os.makedirs(os.path.join(root, "logs"), exist_ok=True)
        with open(os.path.join(root, "logs", "boot-hook.log"), "a", encoding="utf-8") as fh:
            fh.write(f"{datetime.now(timezone.utc).isoformat()} {message}\n")
    except Exception:
        pass

def _run(platforms, session_store):
    _audit(f"worker_start platforms={list(platforms)} session_store={session_store is not None}")
    if "clawchat" not in {str(item).lower() for item in platforms}:
        logger.warning("delivery-unavailable: clawchat is not connected")
        return
    try:
        from clawchat_gateway.storage import get_clawchat_store
        from gateway.run import _resolve_gateway_model, _resolve_runtime_agent_kwargs
        from run_agent import AIAgent
        from gateway.config import Platform
        from gateway.session import SessionSource
        store = get_clawchat_store()
        conversation_id = str(store.get_activation_conversation(platform="hermes", account_id="default") or "").strip()
        owner_user_id = str(store.get_activation_owner_user_id(platform="hermes", account_id="default") or "").strip()
        if not conversation_id:
            logger.warning("delivery-unavailable: no ClawChat activation conversation")
            return
        checklist = open(os.path.join(os.environ.get("HERMES_HOME", "/opt/data"), "BOOT.md"), encoding="utf-8").read().strip()
        _audit(f"agent_start prompt_chars={len(checklist)}")
        runtime = _resolve_runtime_agent_kwargs()
        agent = AIAgent(model=_resolve_gateway_model(), **runtime, platform="gateway", quiet_mode=True, skip_context_files=False, skip_memory=False, enabled_toolsets=[], disabled_toolsets=[], max_iterations=3)
        result = agent.run_conversation(checklist)
        greeting = str((result or {}).get("final_response") or "").strip()
        _audit(f"agent_done response_chars={len(greeting)}")
        if not greeting:
            logger.warning("boot greeting skipped: agent returned no response")
            return
        chat_id = conversation_id
        if session_store is not None:
            source = SessionSource(platform=Platform("clawchat"), chat_id=conversation_id, chat_name=conversation_id, chat_type="dm", user_id=owner_user_id or None)
            entry = session_store.get_or_create_session(source)
            chat_id = str(getattr(getattr(entry, "origin", None), "chat_id", "") or "").strip()
            if not chat_id:
                logger.warning("delivery-unavailable: SessionStore returned no origin")
                return
        _audit(f"route_resolved source=activation chat_id_present={bool(chat_id)}")
        from tools.send_message_tool import send_message_tool
        result = send_message_tool({"target": f"clawchat:{chat_id}", "message": greeting})
        _audit(f"send_result {str(result)[:1000]}")
        logger.info("boot greeting send result: %s", str(result)[:500])
    except Exception:
        _audit("worker_exception\n" + traceback.format_exc())
        logger.exception("boot greeting worker failed")

def handle(event_type: str, context: dict) -> None:
    if event_type != "gateway:startup":
        return
    global _started
    with _lock:
        if _started:
            return
        _started = True
    threading.Thread(target=_run, args=(tuple((context or {}).get("platforms") or ()), (context or {}).get("session_store")), daemon=True).start()
    _audit("hook_triggered")
