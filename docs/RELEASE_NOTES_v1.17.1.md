# aicad-agent 1.17.1

Release date: 2026-08-21

## Manufacturing release candidate closure

- Added the hash-closed `aicad_manufacturing_release_package_v1` schema and
  matching Python API, CLI and MCP surfaces for validation, build and review.
- Actual 2D/3D previews bind their exact source hash; controlled native/source
  evidence binds a portable relative path, byte size and SHA-256 digest.
- Mechanical factory-RFQ and PCB prototype-fabrication workflows produce
  candidates only. Missing evidence, supplier capability or package confirmation,
  and missing external professional review all fail closed.
- This release does not authorize production or fabrication. `productionReady`,
  `toolSteelCutAuthorized` and `massProductionAuthorized` remain false, and
  supplier, professional and organizational approvals remain required.
