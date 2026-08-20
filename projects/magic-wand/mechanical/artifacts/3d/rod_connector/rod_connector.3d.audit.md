# magic_wand_rod_connector_axial_prototype - AICAD 3D feature audit

- Domain: `mechanical`
- Source SHA-256: `f1eaa4487e1d26a47276faae45addca9b400da3bf05a8881ece6411c71f97ec7`
- Origin: `(0,0,0)`
- Units: `mm`
- Tolerance: `0.001 mm`
- Feature count: `3`

| # | ID | Type | Roles | Editable | Purpose | Dependency | Profile | Depth/end | Expected volume delta | Reasoning |
|---:|---|---|---|---|---|---|---|---|---:|---|
| 1 | `F001` | `base_extrude` | outline | `true` | Create the external transition collar. | `principal_plane` | circle R13.5 at (0.0, 0.0) | 10 / blind | 5725.55 mm3 | The collar continues the handle outer diameter over the exact exposed transition length. |
| 2 | `F002` | `boss_extrude` | boss | `true` | Create the shell insertion plug. | `F001` | circle R11.3 at (0.0, 0.0) | 15 / blind | 6017.25 mm3 | The smaller concentric boss enters the shell bore with positive diametral clearance and keeps one body. |
| 3 | `F003` | `cut_extrude` | hole | `true` | Create the continuous GFRP spine adhesive bore. | `F002` | circle R3.7 at (0.0, 0.0) | 25 / through_all | -1075.21 mm3 | The concentric through bore preserves a positive annular wall and lets the spine extend behind the collar. |

## Native SolidWorks topology save/reopen verification

- SolidWorks revision: `34.0.0`
- Native topology authority: `true`
- Stored and reopened references: `11`
- Required sketch references: `3`
- Unresolved required references: `0`
- Exact saved/reopened semantic-key set equality: `PASS`
- Body/volume/bounding-box reopen checks: `PASS`
- Safety locks: `reviewOnly=true`, `accepted=false`, `ruleEnabled=false`, `packagingGated=true`
