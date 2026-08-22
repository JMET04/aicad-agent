---
name: aicad-system-design
description: Plan and verify cross-domain engineering systems whose requirements span multiple subsystems or disciplines. Use for PCB-enclosure-firmware products, manufacturing handoffs, or coordinated mechanical, electronics, packaging, civil, architecture, and other engineering work; use the narrower drawing or 3D skill for an isolated artifact with no cross-subsystem interface.
---

# AICAD System Design

Create one auditable system contract while keeping each discipline's engineering authority and verification separate.

## Workflow

1. Confirm that the request crosses at least two real subsystem boundaries. Name the intended use, prohibited uses, revision, domains, subsystem scopes, and authoritative inputs. Do not hide an unknown specialist domain under `other` or a generic drawing workflow.
2. Read [the system engineering workflow](../../docs/SYSTEM_ENGINEERING_WORKFLOW.md) when creating or changing a contract. Author `aicad.system-engineering-contract.v1` against `rules/system_engineering_contract.schema.json` before claiming integration.
3. Give every system requirement an ID, owning subsystem set, verification method, status, and bidirectional verification-gate trace.
4. Freeze every cross-subsystem interface with provider, consumer, kind, authoritative parameters, units/tolerances, failure behavior, and verification gates. Model the ordered energy, signal, data, force, thermal, material, fluid, human, and manufacturing flows that matter to the intended use.
5. Register every deliverable under exactly one subsystem. Bind real evidence with safe relative paths, byte sizes, SHA-256 digests, evidence levels, and tool versions where known. A drawing, report, or manifest is not evidence merely because its filename exists.
6. Add an explicit change-impact rule for every interface. Name the affected requirements, artifacts, interfaces, or flows and the gates that must be replayed after a change.
7. Run the deterministic contract QA from the plugin root:

   ```powershell
   python scripts/aicad_system_engineering_qa.py system-contract.json --root evidence-root --output system-qa.json --markdown system-qa.md
   ```

8. Run the applicable domain-native tools and physical tests separately. The system QA validates contract consistency and bound-file integrity; it does not replay CAD/EDA tools, prove engineering adequacy, or replace licensed review.

## Release boundary

- `prototypeBuild=true` may document an explicitly authorized prototype while gates remain open, but keep it visibly marked as a prototype and preserve the open risks.
- Open gates require `productionRelease=false` and `productionReleaseEligible=false`.
- Production eligibility requires all required gates passed, `reviewOnly=false`, `technicalReady=true`, `physicalVerified=true`, and separate production authorization.
- Approval to design or prototype does not authorize purchasing, fabrication, site work, deployment, payment, or production release unless the user explicitly grants that action.
- Never promote `generated` or `tool_verified` evidence to `physical_verified`; real assembly, fit, environmental, site, and acceptance evidence must remain distinct.

Report the contract path, QA report, open gates, authorized next action, and exact claim boundary with the handoff.
