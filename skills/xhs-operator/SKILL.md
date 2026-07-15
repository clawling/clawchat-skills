---
name: xhs-operator
display_name: XHS Operator
description: "Upload and publish Xiaohongshu image-and-text notes: QR or SMS login, login-state reuse, 1-18 images, title/body/ordinary topics, remix/copy/visibility/scheduling/collections/locations, preview confirmation, publishing, draft fallback, and local records. Use for Xiaohongshu image-and-text note uploads and creator-account session maintenance."
version: 0.1.0
platforms: [macos, linux]
metadata:
  hermes:
    tags: [Social Media, Xiaohongshu, Publishing, Browser Automation]
    blueprint:
      schedule: "0 3 * * 1"
      deliver: origin
      prompt: "Use xhs-operator to clean expired Xiaohongshu run records, then report only the number removed. Do not log in or publish."
      no_agent: false
---

# XHS Operator

Upload and publish image-and-text notes for a Xiaohongshu creator account. Guide the user through content confirmation, uploading 1-18 images, filling the title and body, appending ordinary topics, configuring note settings, previewing the complete note, and approving the final publish action.

## Requirements

- Node.js 20 or later
- CloakBrowser, installed separately by the user: <https://cloakbrowser.dev>

Run the requirement check before login or publishing:

```bash
node ${HERMES_SKILL_DIR}/scripts/xhs-operator.mjs check
```

If the check fails, stop and report the missing requirement. Do not install or update dependencies from this skill.

## Workflows

- For QR login, SMS login, login-state recovery, or logout behavior, read [references/login.md](references/login.md).
- For image upload, title/body/topics, note settings, preview, confirmation, publishing, and failure handling, read [references/image-text-upload.md](references/image-text-upload.md).

Do not improvise browser operations. Use the bundled scripts and follow the applicable reference workflow.

## Records and logout

Every invocation removes successful runs older than 30 days and other runs older than 7 days. The optional Blueprint only suggests a weekly cleanup job; installation must never silently schedule it.

```bash
node ${HERMES_SKILL_DIR}/scripts/xhs-operator.mjs records
node ${HERMES_SKILL_DIR}/scripts/xhs-operator.mjs cleanup
node ${HERMES_SKILL_DIR}/scripts/xhs-operator.mjs cleanup --all --confirm
node ${HERMES_SKILL_DIR}/scripts/xhs-operator.mjs logout --confirm
```

Require explicit user confirmation before `cleanup --all --confirm` or `logout --confirm`.
