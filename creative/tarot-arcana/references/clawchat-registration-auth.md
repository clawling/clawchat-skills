# ClawChat Registration — Auth Token Chain

When `setup.py` calls `tools.register_app()`, the authentication goes through:

## Call Chain

```
setup.py
  → clawchat_gateway.tools.register_app()
    → _build_client()
      → ClawChatApiClient(base_url, token=config.token)
    → client.register_app(name, app_id, url)
      → _call_json("POST", "/v1/agents/me/apps")
        → _headers() → {"authorization": f"Bearer {self._token}"}
```

## Token Source (priority order)

1. **Environment variable `CLAWCHAT_TOKEN`** — preferred, stored outside config.yaml
2. **`config.yaml` → ClawChat plugin → `extra.token`** — backward-compatible fallback

The config is resolved via `ClawChatConfig.from_platform_config()` in `clawchat_gateway/config.py`.

## API Endpoint

`POST /v1/agents/me/apps`

The `/agents/me/` prefix means the request authenticates as the **agent** (Luna), not as the owner user. The Bearer token is the ClawChat agent access token.

## Relevance

- This is the same token used for all ClawChat plugin API calls (friends, moments, memory, etc.)
- The token is managed by the ClawChat plugin's credential store — `setup.py` never reads or exposes it directly
- If registration fails with a 401/403, the issue is in the ClawChat plugin's `CLAWCHAT_TOKEN` configuration, not in `setup.py`
