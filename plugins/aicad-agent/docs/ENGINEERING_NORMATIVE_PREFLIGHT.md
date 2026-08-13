# Mechanical and electronics normative generation preflight

The canonical guide is distributed with the plugin source at `docs/ENGINEERING_NORMATIVE_PREFLIGHT.md`. Mechanical plans derive 54 exact generation gates and electronics plans derive 63 from `rules/production_readiness_rules.json`; no shorter checklist is allowed.

Use `aicad_get_engineering_preflight_schema`, `aicad_get_engineering_preflight_template` and `aicad_validate_engineering_preflight`, then embed the passing contract as `engineering_normative_preflight`. A pass permits controlled generation only; it does not expose artifacts or grant technical, manufacturing, fabrication or release readiness.
