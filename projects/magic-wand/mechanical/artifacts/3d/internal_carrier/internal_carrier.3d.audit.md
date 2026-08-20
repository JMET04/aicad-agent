# magic_wand_internal_carrier_axial_cage_prototype - AICAD 3D feature audit

- Domain: `mechanical`
- Source SHA-256: `2c3753181eae2461e22438865ec4f3ca92a6261b9fbd106bacb9d8274f6ea8de`
- Origin: `(0,0,0)`
- Units: `mm`
- Tolerance: `0.001 mm`
- Feature count: `2`

| # | ID | Type | Roles | Editable | Purpose | Dependency | Profile | Depth/end | Expected volume delta | Reasoning |
|---:|---|---|---|---|---|---|---|---|---:|---|
| 1 | `F001` | `base_extrude` | outline | `true` | Create the carrier outer sliding envelope. | `principal_plane` | rectangle 17.8x12.8 at (0.0, 0.0) | 92 / blind | 20961.3 mm3 | The centered rectangle stays inside the circular shell bore with a computed positive corner clearance. |
| 2 | `F002` | `cut_extrude` | pocket | `true` | Create the axial module tunnel and four connected carrier walls. | `F001` | rectangle 15.4x10.4 at (0.0, 0.0) | 92 / through_all | -14734.7 mm3 | The centered through cut leaves the declared uniform rectangular wall while preserving one connected body. |

## Native SolidWorks topology save/reopen verification

- SolidWorks revision: `34.0.0`
- Native topology authority: `true`
- Stored and reopened references: `33`
- Required sketch references: `8`
- Unresolved required references: `0`
- Exact saved/reopened semantic-key set equality: `PASS`
- Body/volume/bounding-box reopen checks: `PASS`
- Safety locks: `reviewOnly=true`, `accepted=false`, `ruleEnabled=false`, `packagingGated=true`
