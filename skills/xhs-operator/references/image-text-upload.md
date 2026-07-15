# Image-and-text note upload workflow

Use this workflow to upload images, fill an image-and-text note, configure its settings, preview it, and then publish immediately or on a schedule after explicit confirmation.

## Collect content

Ask one question at a time when required information is missing.

1. Propose a title, body, ordinary topics, and conservative settings.
2. Ask whether to use the proposal. If rejected, require concrete replacement content.
3. Before running `prepare`, show the finalized content and settings.

Defaults: original statement off, remix off, body copying off, public visibility, scheduling off, no collection, and no location.

## Options

- Images: 1-18 existing JPG, JPEG, PNG, or WebP files in the supplied order. Never crop, convert, or compress them.
- Title: required, up to 20 characters.
- Body and ordinary topics: up to 1000 characters combined. Format topics as `#topic-one #topic-two`. Activity topics are not available.
- Original statement: on or off; default off.
- Remix: on or off; default off.
- Body copying: on or off; default off.
- Visibility: `公开可见`, `仅自己可见`, or `仅互关好友可见`; default `公开可见`. Recommend `仅自己可见` for tests.
- Scheduled publishing: off, or a Beijing time (`Asia/Shanghai`) in `YYYY-MM-DD HH:mm`; default off.
- Collection: none, an existing collection by exact name, or a new collection. Creating one requires separate confirmation, a name up to 20 characters, and an optional description up to 50 characters.
- Location: none, or one unique location. If candidates are ambiguous, show them and ask for the exact name and address.

## Prepare a preview

Create a UTF-8 request JSON in the current workspace. Use absolute image paths:

```json
{
  "images": ["/absolute/path/one.jpg"],
  "title": "不超过 20 个字符",
  "body": "正文",
  "topics": ["<topic one>", "<topic two>"],
  "settings": {
    "original": false,
    "allowRemix": false,
    "allowCopy": false,
    "visibility": "仅自己可见",
    "scheduledAt": null,
    "collection": null,
    "location": null
  }
}
```

Append `topics` to `body` with spaces between tags. `scheduledAt` is `null` or Beijing time in `YYYY-MM-DD HH:mm`.

For an existing collection, use `{ "name": "<exact name>" }`. To create one after separate confirmation, add `"create": true`, `"confirmed": true`, a name of at most 20 characters, and an optional description of at most 50 characters.

For a location, use `{ "name": "<exact name>" }`. If multiple candidates are returned, add the selected candidate's displayed address. Do not invent collection or location choices from examples.

Start preparation:

```bash
node ${HERMES_SKILL_DIR}/scripts/xhs-operator.mjs prepare --request /absolute/path/request.json
node ${HERMES_SKILL_DIR}/scripts/xhs-operator.mjs status --run <run-id>
```

When status becomes `awaiting_confirmation`, send `summary.json` and `preview.png` to the user. Use `[[as_document]]` when screenshot compression would make inspection difficult.

## Confirm and publish

Publish only after the user replies with the exact `confirmationPhrase` from `state.json`. Extract its short task ID and run:

```bash
node ${HERMES_SKILL_DIR}/scripts/xhs-operator.mjs confirm --run <run-id> --token <task-id>
```

Any content or setting change requires a new request and new run. An old confirmation never applies.

The worker waits 15 minutes for confirmation. If confirmation expires, it attempts `暂存离开` and closes the browser.

## Result handling

Poll status and interpret terminal states exactly:

- `published`: report success with the success screenshot.
- `confirmation_expired`: report whether `draftSaved` succeeded; require a new preview and confirmation.
- `failed`: publishing was not clicked; report `draftSaved` and diagnostics.
- `publish_unknown`: never click publish again and never save another draft. Ask the user to inspect the creator content list.
- `risk_verification_required`: stop all automation.

Do not claim success from a click alone.
