# Exchange-rate lookup and conversion

Use this reference when a personal-finance record is denominated in a currency other than the ledger's base currency and the user asks Hermes to find or calculate the conversion.

## Authority order

Use the most authoritative amount available:

1. **Actual settled base-currency amount supplied by the user, bank, card statement, or receipt.** This is the bookkeeping amount and takes precedence over any searched market rate.
2. **A user-supplied exchange rate.** Preserve the user's stated source or context.
3. **A searched reference rate.** Treat it as an estimate, not the exact amount charged by a payment provider.
4. **No reliable rate.** Keep the original-currency amount and explain naturally that the base-currency value still needs confirmation. Never invent a rate.

Do not replace an actual statement amount with a web rate. Card networks, banks, and wallets may add spreads or fees, so a market reference rate can differ from the settled amount.

## Search workflow

1. Determine the required pair as `transaction currency -> profile.base_currency` and identify the transaction date.
2. Search the web for that exact pair and date. For example, search for an official or reputable historical reference rate for `USD to CNY on 2026-07-04`. For a transaction dated today, search for the latest available reference rate and record the rate's publication date.
3. Open the source page rather than relying only on a search-result snippet.
4. Prefer, in order:
   - an official central-bank or government reference-rate publication;
   - a regulated bank or payment-network reference page;
   - a reputable market-data provider with a clearly stated date and currency pair.
5. For a historical transaction, do not silently substitute today's rate. If the selected source has no rate for a weekend or holiday, use the source's nearest prior published business-day rate and disclose that choice in the preview.
6. If only the inverse pair is published, invert it using decimal arithmetic. Never round before the final converted amount.
7. When practical, compare against a second reputable source. If the rates materially disagree, tell the user and ask which source or settled amount to use.

## Rate semantics and calculation

The ledger rate means:

```text
1 unit of FROM currency = RATE units of TO currency
```

The CLI calculates:

```text
base amount = original major-unit amount x rate
```

Example:

```text
FROM = USD
TO = CNY
RATE = 7.20
USD 5.00 x 7.20 = CNY 36.00
```

Keep sufficient decimal precision for the rate. Round only the final monetary amount according to the target currency's minor-unit rules.

## Confirmation-first bundle

A searched rate is a supporting ledger record and must follow the same preview-and-confirm rule as every other finance mutation.

Before writing, show a concise natural-language bundle containing:

- original amount and currency;
- target/base currency;
- rate and rate date;
- source name and clickable URL;
- whether it is an estimated reference rate;
- calculated base-currency amount;
- the transaction/account effects that will be written.

One explicit confirmation may authorize both the exchange-rate record and the transaction when both were included in the same preview. After confirmation:

1. Write the searched rate with `add-exchange-rate --estimate --source <URL> --confirmed`.
2. Write the transaction with the resulting exchange-rate reference, or use the actual settled base amount when one was supplied.
3. Report the saved result in natural language. Do not expose command names, flags, generated ids, raw fields, or review codes.

Operator example:

```bash
python "$HERMES_SKILL_DIR/scripts/account_book.py" add-exchange-rate \
  --book "$ACCOUNT_BOOK" \
  --date 2026-07-04 \
  --from USD \
  --to CNY \
  --rate 7.20 \
  --source "https://example.org/reference-rate" \
  --estimate \
  --confirmed
```

## Failure and uncertainty handling

- If web search is unavailable, ask the user for the settled base amount or rate; otherwise keep the transaction under review without a fabricated conversion.
- If the transaction date is unknown and the rate could materially vary, ask for the date before searching.
- If a source does not clearly state the pair, direction, or date, do not use it.
- If the user only asks for an informational conversion and does not ask to save anything, search and answer without mutating the ledger.
- Always preserve the original amount and currency even when a base-currency conversion is recorded.
