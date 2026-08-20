# Engineering domain registry and universal workflow

AICAD is a universal engineering drawing framework, not a claim that generic
geometry is specialist engineering. Every request is routed to one registered
domain before geometry. Unknown domains fail closed and a declared specialist
domain never falls back to `general`.

## Current domain boundary

| Domain | Current stage | What AICAD may expose | Hard external boundary |
|---|---|---|---|
| General | constrained | origin-anchored portable 2D/3D review geometry | specialist meaning and release |
| Mechanical | constrained | preflight-bound 2D and limited extrude/cut 3D review candidates | assemblies, advanced features, analysis, manufacturing authorization |
| Electronics | constrained | preflight-bound enclosure/board-envelope review plus external EDA evidence workflow | native schematic/PCB authoring and fabrication authorization |
| Packaging | constrained | requirement/normality/guarded dieline review candidates | material trials, tooling and manufacturing release |
| Architecture | constrained | detail-contract-bound architectural review candidates | jurisdictional approval and professional release |
| Sheet metal | constrained semantics | semantic review geometry | native bends, flat patterns and tooling proof |
| Civil | constrained | source-bound CRS/survey/alignment/profile/drainage review candidates | terrain modelling, LandXML, hydraulic analysis, construction issue and professional release |
| Structural, electrical, plumbing, HVAC, process piping, product design | foundation | typed intent, rule recall and exact coverage template | specialist calculation, native authoring, professional release |

`foundation` does not mean ignored. It means the system knows the domain,
recalls its obligations, preserves its vocabulary and refuses to manufacture a
false technical conclusion. Promotion requires executable schema/semantics,
authority binding, a specialist validator, negative regressions, native-host
evidence and artifact closure.

## Maturity authority

The registry `maturity` field is a declaration, never an authorization. Runtime
behavior derives an effective maturity from three code-owned controls: a domain
ceiling, executable AST probes for the required validators, and an exact
regular-file evidence closure whose size and SHA-256 are recorded. Missing,
unreadable, linked/reparse, path-escaping or changing evidence fails closed.

A declaration above the code ceiling is rejected. An incomplete capability or
evidence closure automatically earns only `foundation`, and the behavior gate
emits hard `DOMAIN.G000` before technical artifact exposure. The six
foundation-locked domains cannot be promoted by editing JSON; changing their
boundary requires reviewed code, executable validators, evidence closure and
negative regression tests.

## Non-skippable workflow

1. Resolve domain, requested space and delivery stage.
2. Bind jurisdiction, current standards and immutable source evidence.
3. Recall canonical rules and reviewed experience; free-text lesson matches are
   advisory and cannot satisfy coverage.
4. Build the exact coverage inventory. Every applicable key appears once.
5. Validate the domain contract before geometry.
6. Compile in staging and run domain QA.
7. Reopen the native host when the requested maturity requires it.
8. Close visual, artifact and evidence ledgers.
9. Hand off a review candidate. Professional/manufacturing authorization stays
   external and explicit.

The plugin compilation entry now automatically evaluates the registered domain
gate before it creates an artifact directory. Foundation-domain geometry is
blocked with `DOMAIN.G000`; warnings are preserved without being confused with
hard failures. Mechanical and electronics additionally require their complete
source-bound normative preflight.

## Experience coverage evidence

Coverage `PASS` entries must reference real files under a controlled evidence
root using `{path,size,sha256,kind}`. Absolute paths, traversal, missing files,
links/reparse points, size drift and hash drift fail. Catalog fingerprints cover
the catalog, registry and every referenced rule source, so a rule edit makes an
old ledger stale.

The public tools are:

- `aicad_get_engineering_domain_registry`
- `aicad_get_civil_review_candidate_schema`
- `aicad_validate_civil_review_candidate`
- `aicad_guarded_packaging_delivery`
- `aicad_get_guarded_delivery_workflow`
- `aicad_recall_experience`
- `aicad_validate_review_coverage`
- schema resources for context and coverage

These tools are pre-generation controls; candidate learning records remain
review-only and cannot silently become rules.
