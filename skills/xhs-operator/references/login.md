# Login workflow

Use this workflow for first login, expired login state, QR login, SMS login, and logout.

## Login method

Prefer QR login. Use SMS only when the user requests it.

### QR login

```bash
node ${HERMES_SKILL_DIR}/scripts/xhs-operator.mjs login --mode qr
node ${HERMES_SKILL_DIR}/scripts/xhs-operator.mjs status --run <run-id>
```

When status is `waiting_for_scan`, deliver `qrScreenshot` to the user and poll status after the user scans it.

### SMS login

Ask for the phone number, start login, and ask for the received code only after status becomes `waiting_for_code`:

```bash
node ${HERMES_SKILL_DIR}/scripts/xhs-operator.mjs login --mode sms --phone <phone>
node ${HERMES_SKILL_DIR}/scripts/xhs-operator.mjs sms-code --run <run-id> --code <code>
```

Never echo or retain the SMS code.

## Login state

Login state is stored at `$HOME/xiaohongshu/auth/state.json`. Publishing restores this state automatically. If the creator page redirects to login, report that authentication expired and start a new login workflow.

If status is `risk_verification_required`, stop. Do not retry, bypass verification, or use a CAPTCHA service.

## Logout

Require explicit user confirmation before deleting login state:

```bash
node ${HERMES_SKILL_DIR}/scripts/xhs-operator.mjs logout --confirm
```
