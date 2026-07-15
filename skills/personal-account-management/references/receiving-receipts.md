# Receiving Receipts & OCR

Workflow for processing receipt screenshots the user sends in chat. Pairs with the related `ocr-and-documents` skill — this skill only stores the extracted facts.

Operator-only note: this file names tools and storage fields for implementation. Do not echo those names to the user. User-facing receipt replies should be natural Chinese previews and confirmation questions.

## End-to-end flow

1. **Receive the image.** The user posts a URL (often on `media.clawling.chat`, the ClawChat media CDN) or an inline base64.
2. **Try `vision_analyze(image_url=URL)` first.** Many CDNs return 403 for the stdlib default `Python-urllib/x.y` User-Agent. If `vision_analyze` reports "Invalid image source" or 403, **fall through to step 3**.
3. **Download the image with a real User-Agent.** Use `curl` (it has a non-default UA) or a Python urllib request with a custom UA header:
   - `curl -L -o /tmp/receipt.jpg "https://media.clawling.chat/media/.../foo.jpg"`
   - Python: `urllib.request.Request(url, headers={"User-Agent": "ClawChat-Hermes/1.0"})`
   Verified-good UAs: `Mozilla/5.0`, `ClawChat-Hermes-Agent/1.0`, `curl/8.0.1`, `Wget/1.21`. Blocked: `Python-urllib/3.13` (403).
4. **Re-run `vision_analyze` on the local path.** `image_url` accepts `/tmp/...` local paths. The image will load into the model's native context and you can read it directly.
5. **Extract structured fields.** Always ask the model for: type, merchant name(s), total amount + currency, date/time, payment method, line items, and any **uncertain reads** (low confidence, partial crop, blurry digits). Force an explicit "OCR-uncertain" section in the response — never assume the digits you see are correct.
6. **Build the candidate transaction internally.** Map date, type, amount, currency, title, merchant, category, and payment account to the ledger. Ask the user naturally when category or payment method is ambiguous.
7. **Disambiguate "initial balance" requests.** When the user says "set the initial balance to X" but X is fuzzy ("start of July", "beginning of the month"), ask which exact day and which currency. Do not infer from a single screenshot — the "start of the month" frame can mean the end-of-previous-month closing balance or the first business day, depending on user intent.
8. Preview the candidate and show it in natural language. Do not loop a second preview "to remind the user".
9. **Wait for explicit "confirm" / "OK" / "write it"**, then write. Do not chain multiple writes in one go when the user asked for a single change.
10. **Skip transfers unless asked.** When a screenshot contains a mix of "transfer to bank card" lines and "purchase" lines, default to recording only the expense lines and surface the transfers as a question, not as a silent inclusion. Writing transfers requires both source and destination accounts, so ask the user to choose/create the destination ledger account first.

## Anti-patterns

- **Don't read the image via `vision_analyze` on a `media.clawling.chat` URL directly.** The default UA gets 403, the tool reports "Invalid image source", and you'll waste a turn. Always download with a real UA first.
- **Don't auto-run `curl /api/book` / `healthz` to "verify" the write went through.** The user can refresh the dashboard themselves. (See `personal-account-management` Pitfall #13.)
- **Don't write transfers as `expense`.** They inflate the user's apparent spend and break the cashflow math. (See Pitfall #14.)
- **Don't paste the receipt raw text into the ledger.** Build a structured candidate first so the agent only ever writes confirmed finance records.

## Platform disambiguation — DO NOT trust your own inference

When the user sends a balance-change / balance-detail screenshot, **never assume which platform it is based on the icon, color scheme, or layout.** WeChat (WeChat Wallet balance) and Alipay (balance change details) render nearly identically in compressed images: white card, descending date list, red negative amounts, top status bar that looks the same after compression. Icon recognition in vision models is unreliable across iOS/Android, dark/light mode, and trimmed crops.

Required workflow when an image-only balance detail arrives:

1. Do NOT write any account or transaction based on inferred platform.
2. Ask the user explicitly: "Is this screenshot from WeChat or Alipay?" Frame it naturally — "It looks like X, but X and Y are very hard to distinguish with compressed screenshots, so please confirm for me."
3. If the user names a destination account in passing ("this is my WeChat wallet", "this is Alipay"), still confirm once before writing — vision model inferences are wrong often enough that one confirmation is cheaper than a wrong-source migration.
4. If the user is unsure ("I also cannot distinguish them with 100% certainty"), treat their stated preference as authoritative and proceed, but log the uncertainty in the transaction `source.source_text` so future audits can find it.

Failure mode this prevents: writing a WeChat-balance account named WeChat Wallet when the source is actually Alipay, then having to retroactively rename the account, re-attribute every transaction, and reverse the initial balance calculation.

## Anchor-balance reconstruction when the bottom is cropped

The screenshot's last visible transaction is **almost never the real month-end or account-opening balance** — there are usually more entries below the visible area. Most users will give you a partial-crop image and say "use the month-end balance as the initial balance" without realizing the bottom is cut off.

Required workflow:

1. Compute the candidate initial balance by taking the lowest visible post-transaction balance, then subtracting any obvious offscreen tail you can infer (e.g. the user mentioned "there is another -100 transfer that was cut off").
2. State the inference explicitly in the preview: "I can see the balance at 6/30 09:24 near the bottom of the screenshot as ¥1480.35, but one -100 entry is cut off — the back-calculated initial balance is ¥1380.35. Please confirm?"
3. Wait for the user's confirmation of the inferred number, not just the account write.
4. If the user can supply the exact number, skip the inference and use their value verbatim. Never silently use the visible post-transaction balance — that double-counts the offscreen tail.

## Worked example (abbreviated)

User posts a screenshot of an Alipay "balance change details" page that shows:

```
2026-07-03 11:48  Lawson Convenience Store, Qianhai Fund Town  -23.00   Balance 255.55
2026-07-03 11:47  Transfer to bank card - transfer - Shen Hui   -250.00  Balance 278.55
2026-07-02 19:51  Old Brown Sugar Pearl Milk Tea               -11.90   Balance 528.55
2026-07-02 19:49  Top Picks Longfa Signature Chicken Hot Pot for Two  -145.90  Balance 540.45
```

Correct handling:
- Ask for the initial balance separately (the 6-30 09:24 entry visible at the bottom of the screenshot is *not* necessarily the 7/1 balance — more June entries may be off-screen).
- Surface 4 expense candidates + 1 transfer candidate. Show the expense ones, explicitly call out the transfer, and let the user decide whether to record it (and if so, which destination ledger account to use).
- After user confirms, write the 4 expense lines as confirmed records using the known-good account-book invocation shape. Do not tell the user about command syntax or internal batching choices.
- Do not run dashboard probes automatically; the user can refresh the ClawChat liveware dashboard.

## Balance-history effect

The receipt preview must include the affected account's before/after balance and state naturally that this month's recorded account state will reflect the result. After confirmation, receipt evidence copy, transaction creation, account balance update, and current-month snapshot capture are one candidate workflow. Dry-run performs none of them.

A receipt imported with `--no-balance-update` is history-only: store the confirmed transaction/evidence but leave both current accounts and every monthly snapshot unchanged. A receipt with an older receipt date still updates only the current recorded-month account state; it does not rewrite that old month's assets.
