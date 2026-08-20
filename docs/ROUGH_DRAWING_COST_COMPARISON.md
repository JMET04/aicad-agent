# Rough drawing cost comparison

This is a planning estimate, not an invoice. It uses a fixed budgeting exchange
rate of CNY 7.20/USD and the 2026-08-20 API price snapshot. It excludes image
generation, CAD/EDA licenses, workstation time, standards purchases, prototypes
and statutory/professional sign-off.

Assumed API models:

- OpenAI `gpt-5.4-mini`: USD 0.75/M uncached input and 4.50/M output.
- DeepSeek `deepseek-v4-flash`: USD 0.14/M cache-miss input and 0.28/M output.
- Cached input is conservatively treated as cache miss in this rough table.

| Drawing/work item | Rough input/output tokens | OpenAI API | DeepSeek API | Human drafting only | AI + mandatory human review |
|---|---:|---:|---:|---:|---:|
| Architectural plan review candidate | 25k / 8k | USD 0.0548 / CNY 0.39 | USD 0.0057 / CNY 0.04 | 4–8 h | 1.5–3.5 h + API |
| Steel/structural intent drawing | 30k / 10k | USD 0.0675 / CNY 0.49 | USD 0.0070 / CNY 0.05 | 6–12 h | 3–7 h + API |
| Mechanical 3D review model and views | 20k / 6k | USD 0.0420 / CNY 0.30 | USD 0.0045 / CNY 0.03 | 3–6 h | 1.5–4 h + API/host |
| Electronics schematic/PCB review package | 35k / 12k | USD 0.0803 / CNY 0.58 | USD 0.0083 / CNY 0.06 | 8–20 h | 4–12 h + API/EDA |
| Packaging dieline review candidate | 25k / 8k | USD 0.0548 / CNY 0.39 | USD 0.0057 / CNY 0.04 | 3–8 h | 1.5–4 h + API/trial |
| Civil constrained review drawing | 35k / 10k | USD 0.0713 / CNY 0.51 | USD 0.0077 / CNY 0.06 | 8–24 h | 4–14 h + API/survey tools |

For a labor-rate comparison, multiply the hour ranges by the actual loaded
hourly cost. At CNY 120/hour, the architectural row is roughly CNY 480–960 for
manual drafting versus CNY 180–420 plus a sub-CNY model call for AI-assisted
work. This does not mean the AI result is construction-ready; it means the
economics are dominated by human verification rather than model tokens.

## Formula

```text
remote_model_cost =
  cache_hit_input_tokens  × cache_hit_rate / 1,000,000
+ cache_miss_input_tokens × cache_miss_rate / 1,000,000
+ output_tokens           × output_rate / 1,000,000

delivered_cost = remote_model_cost
               + requirements_hours × loaded_hourly_rate
               + specialist_review_hours × loaded_hourly_rate
               + CAD/EDA_host_cost
               + rework_cost
               + prototype/test/certification_cost
```

Use the generated `*.provider-run.json` file for actual token counts. If usage
is absent or a model is not in the dated price catalog, AICAD reports `unknown`
rather than zero. Provider invoices remain the financial source of truth.
