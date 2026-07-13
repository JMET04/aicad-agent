# aicad-agent 1.2.1

`aicad-agent` is a local-first Codex/MCP plugin for deterministic 2D CAD, packaging-dieline review, and transactional SolidWorks part generation.

The default Agent-first path does not require an API key. The caller authors a typed plan, then the plugin validates mathematical constraints and compiles ASCII execution artifacts. Optional AutoCAD and SolidWorks hosts execute and reopen native files when those products are installed.

## Safety state

- `reviewOnly=true`
- `accepted=false`
- `ruleEnabled=false`
- `packagingGated=true`

Generated drawings are engineering review candidates. They are not production acceptance or manufacturing approval.

## Install

Build the package from the repository root:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/build-agent-plugin.ps1
powershell -ExecutionPolicy Bypass -File scripts/install-agent-plugin.ps1
```

Start a new Codex task after installation so the skill and MCP server are discovered.

## No-key Agent workflow

1. Call `aicad_get_plan_schema`.
2. Author the plan in the current Agent conversation.
3. Call `aicad_validate_plan`.
4. Call `aicad_compile_plan`.
5. Execute in an available CAD host and verify save/reopen persistence.

`OPENAI_API_KEY` is only used by the optional standalone natural-language provider. It is not used by the default caller-plan workflow.

## Packaging review loop

The package includes `scripts/aicad_packaging_qa.py` and `rules/packaging_dieline_rules.json`. Every detected defect must record its symptom, root cause, corrective action, persistent prevention rule, and regression evidence.

## Optional hosts

- AutoCAD: the source bundle is under `runtime/autocad` in the built plugin.
- SolidWorks: source and the build helper are included. Dassault Systèmes interop assemblies are not redistributed in the default package; build them locally on a licensed SolidWorks workstation.

Without a native host, plan validation and portable artifact generation remain available, while native DWG/SLDPRT persistence checks report unavailable instead of being simulated.

