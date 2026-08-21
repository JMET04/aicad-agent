# Manufacturing release candidate contract

The manufacturing release workflow validates a controlled evidence package. It does not manufacture parts, replay native CAD/KiCad execution, approve tooling, or claim production release.

## Readiness layers

- `factoryRfqCandidateReady`: the mechanical digital RFQ closure passes. A project-authored `unassigned_rfq_recipient` profile is allowed here, so an RFQ can be prepared without inventing a supplier.
- `prototypeFabricationCandidateReady`: the PCB native KiCad/ERC/DRC/CAM closure passes and every fabrication/assembly supplier has a current, attributable public or qualified capability record. The neutral RFQ recipient is forbidden.
- `digitalPackageReady`: every domain present in the package passes its digital gate.
- `factoryHandoffReady`: the full digital package passes and each supplier used by this exact package/revision provides a supplier-owned confirmation acknowledging the exact artifact hash map.
- `productionReady`, `toolSteelCutAuthorized`, and `massProductionAuthorized` are always `false`. External professional and supplier release remains mandatory.

A partial candidate has status `partial_digital_candidate`, a non-null `artifactClosureSha256`, per-domain values in `domainArtifactClosureSha256`, and only passing-domain rows in `candidateArtifactLocations`.

## Controlled evidence

Every evidence reference is exactly `{path, size, sha256}`. Paths are portable POSIX-relative paths below a real controlled root; absolute paths, `..`, backslashes, links/junctions, duplicate role paths, size drift, and hash drift fail closed.

Coordinate systems require unit axes, mutual orthogonality, and a right-handed `X×Y=Z` basis. Native execution logs bind an exact gate, subject, revision, named tool/version, `nativeExecution=true`, exact input/output role hashes, and a unique non-empty list of passing checks.

SolidWorks `.sldprt`/`.sldasm` evidence is role/suffix checked, at least 4 KiB, has the observed version word at bytes 4–7, and must pass non-trivial binary probes. Renamed text, 128-byte stubs, zero-entropy files, and role-swapped suffixes are rejected.

Actual SVG previews are parsed as XML, require at least two real graphic elements, and bind the exact source hash on the root `<svg data-aicad-source-sha256="…">`. Comments or child attributes cannot impersonate the root binding. PNG previews require valid chunk boundaries/CRC/IEND closure, no trailing data, meaningful non-dominant content spanning at least 20% of both axes, and one exact structured `tEXt`/`iTXt` value named `aicad-source-sha256`.

## Required subject roles

Mechanical parts require native part CAD, STEP, manufacturing drawing, actual 2D/3D previews, and native reopen/export log. Mechanical assemblies require native assembly, STEP, assembly/exploded/section drawings, actual 2D/3D previews, assembly work instruction, inspection plan, molding input, BOM, positions, interference log, and native reopen/export log.

Each PCB requires native KiCad project/schematic/board, ERC and DRC logs, schematic PDF, fabrication and assembly drawings/notes/previews, a 3D model and actual preview, BOM, CPL, IPC-D-356 connectivity, CAM log, Gerber job, PTH and NPTH drills, native reopen/export log, and exactly one Gerber for every native fabrication layer (all copper plus F/B paste, mask, silk, and `Edge.Cuts`).

## Neutral RFQ recipient

The release-basis supplier list may contain this non-supplier variant:

```json
{
  "supplierId": "unassigned_rfq_recipient",
  "recipientProfile": {"path": "rfq/recipient.json", "size": 1234, "sha256": "<64 lowercase hex>"}
}
```

The referenced document uses schema `aicad_rfq_recipient_profile_v1`, status `rfq_recipient_unassigned`, authorship `project_rfq_requirements`, `supplierAuthorityClaimed=false`, and exact unit/coordinate/process/format inventories. It may support mechanical RFQ candidacy only. It can never support PCB prototype fabrication, factory handoff, tool steel cutting, or mass production.

## CLI and Python API

```powershell
python -m aicad.cli manufacturing-release-schema
python -m aicad.cli manufacturing-release-validate package.json --evidence-root evidence
python -m aicad.cli manufacturing-release-build package.json --evidence-root evidence --out output --name release
python -m aicad.cli manufacturing-release-review package.json --evidence-root evidence --output review.html --review-launch never
```

Python entry points are `validate_manufacturing_release_value(package, evidence_root)`, `build_manufacturing_release_value(package, evidence_root, output_dir, name, review_launch)`, and `open_manufacturing_release_review_value(review_html, review_launch)` in `aicad.manufacturing_api`. Package input may be an object, JSON string, or UTF-8 JSON file path. Build output must be new or empty.

The MCP surface exposes `aicad_get_manufacturing_release_schema`, `aicad_validate_manufacturing_release_package`, `aicad_build_manufacturing_release_package`, and `aicad_open_manufacturing_release_review`; the same schema is readable from `aicad://manufacturing-release-schema`.

## Build and reviewer output

A candidate build writes a portable validation JSON, a package-specific interactive HTML reviewer, a digital candidate manifest when either domain passes, and a blockers JSON while supplier handoff remains closed. A factory-handoff candidate manifest is written only after real per-package supplier confirmations pass.

The reviewer renders every package subject on both 2D and 3D tabs, shows actual hash-bound SVG/PNG previews, links to verified native/STEP/DXF/PDF/CAM evidence with percent-encoded relative URLs, keeps all labels in bounded annotation boxes, uses distinct line types/weights only as a legend, and lists every blocker with its individual repair. It rejects `file://`, drive/username paths, generic-only CAD-sheet substitutes, missing preview/subject closure, and production/tooling claims.
