# Provider usage and per-drawing cost ledger

AICAD records one `*.provider-run.json` ledger for every natural-language
generation. The ledger stores a SHA-256 digest of the request, never the prompt
or API key. It distinguishes input, cached input, cache-miss input, output and
reasoning tokens whenever the provider response exposes those fields.

Cost semantics are fail-closed:

- deterministic offline generation has exactly USD 0 API cost, while token
  fields are `null` because tokens are not applicable;
- missing API usage, inconsistent cache totals or an unknown model price yields
  `amount: null` and `status: unknown`, never a fictitious zero;
- API-response usage plus a known price snapshot yields an estimate that must be
  reconciled with the provider invoice;
- no drawing inherits shared conversation cost silently. A future multi-drawing
  orchestrator must allocate shared input explicitly and retain that allocation
  method in its ledger.
For GPT-5.6, explicit cache writes are billed at 1.25 times the uncached input
rate. Requests with more than 272,000 input tokens apply the published 2x input
and 1.5x output multipliers to the full request. Both adjustments are recorded
in the cost ledger instead of being hidden in a flat token rate.

## Price snapshot used by 1.17 development

Snapshot date: 2026-08-21. Rates are USD per one million tokens.

| Provider/model | Cached input | Cache-miss input | Output |
|---|---:|---:|---:|
| DeepSeek V4 Flash | 0.0028 | 0.14 | 0.28 |
| DeepSeek V4 Pro | 0.003625 | 0.435 | 0.87 |
| OpenAI gpt-5.4-mini | 0.075 | 0.75 | 4.50 |
| OpenAI gpt-5.4 | 0.25 | 2.50 | 15.00 |
| OpenAI gpt-5.6-luna | 0.02 | 0.20 | 1.20 |
| OpenAI gpt-5.6-terra | 0.20 | 2.00 | 12.00 |
| OpenAI gpt-5.6-sol | 0.50 | 5.00 | 30.00 |

Authoritative sources:

- DeepSeek: <https://api-docs.deepseek.com/quick_start/pricing/>
- OpenAI GPT-5.6 model pages: <https://developers.openai.com/api/docs/models/compare>

The in-code snapshot expires after 90 days. Refresh it from the authoritative
pages before cost comparisons made after that window. Provider invoices and
billing dashboards remain the financial source of truth.

## DeepSeek configuration

```powershell
$env:DEEPSEEK_API_KEY = "..."
python -m aicad.cli setup --provider deepseek
python -m aicad.cli natural request.txt --provider deepseek --out build
```

The default endpoint is `https://api.deepseek.com/chat/completions` and the
default model is `deepseek-v4-flash`. The key can also be read from stdin into a
separate Windows Credential Manager target:

```powershell
Get-Content .\deepseek-key.txt | python -m aicad.cli setup --provider deepseek --api-key-stdin
```

Delete the plaintext key file after secure enrollment. Do not commit keys or
provider-run HTTP payloads.
