# magic_wand_handle_shell_axial_prototype - AICAD 3D feature audit

- Domain: `mechanical`
- Source SHA-256: `2fe4fc4542cb540ab73bc338e05c8c1e7971837e2a26f49991a8e61e079e1e0a`
- Origin: `(0,0,0)`
- Units: `mm`
- Tolerance: `0.001 mm`
- Feature count: `2`

| # | ID | Type | Roles | Editable | Purpose | Dependency | Profile | Depth/end | Expected volume delta | Reasoning |
|---:|---|---|---|---|---|---|---|---|---:|---|
| 1 | `F001` | `base_extrude` | outline | `true` | Create the nonconductive cylindrical grip shell envelope. | `principal_plane` | circle R13.5 at (0.0, 0.0) | 110 / blind | 62981.1 mm3 | The origin-centered outer cylinder establishes the common wand axis and the positive-Z shell length. |
| 2 | `F002` | `cut_extrude` | hole | `true` | Create the axial electronics and carrier cavity. | `F001` | circle R11.5 at (0.0, 0.0) | 110 / through_all | -45702.3 mm3 | A concentric through cut leaves the exact declared radial wall and an open tube for sliding assembly. |

## Native SolidWorks topology save/reopen verification

- SolidWorks revision: `34.0.0`
- Native topology authority: `true`
- Stored and reopened references: `7`
- Required sketch references: `2`
- Unresolved required references: `0`
- Exact saved/reopened semantic-key set equality: `PASS`
- Body/volume/bounding-box reopen checks: `PASS`
- Safety locks: `reviewOnly=true`, `accepted=false`, `ruleEnabled=false`, `packagingGated=true`
