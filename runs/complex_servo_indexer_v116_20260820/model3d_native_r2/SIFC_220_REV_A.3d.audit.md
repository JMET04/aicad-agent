# SIFC_220_REV_A - AICAD 3D feature audit

- Domain: `mechanical`
- Source SHA-256: `5d214292944aa0603b537248e3d9bbd9ed64936cede5545178bb51b3e3bf4e84`
- Origin: `(0,0,0)`
- Units: `mm`
- Tolerance: `0.001 mm`
- Feature count: `25`

| # | ID | Type | Roles | Editable | Purpose | Dependency | Profile | Depth/end | Expected volume delta | Reasoning |
|---:|---|---|---|---|---|---|---|---|---:|---|
| 1 | `F001` | `base_extrude` | base_plate, review_selectable | `true` | 220 x 180 x 20 datum-A mounting base | `principal_plane` | rectangle 220x180 at (0.0, 0.0) | 20 / blind | 792000 mm3 | This feature is source-dimensioned, origin-anchored, fully constrained, and committed only after its declared support is validated. |
| 2 | `F002` | `boss_extrude` | bearing_boss, review_selectable | `true` | diameter 130 dual-bearing housing boss | `F001` | circle R65 at (0.0, 0.0) | 36 / blind | 477836 mm3 | This feature is source-dimensioned, origin-anchored, fully constrained, and committed only after its declared support is validated. |
| 3 | `F003` | `boss_extrude` | rib_pad, review_selectable | `true` | right vertical stiffness rib pad | `F001` | rectangle 42x72 at (48.0, 0.0) | 12 / blind | 6476.35 mm3 | This feature is source-dimensioned, origin-anchored, fully constrained, and committed only after its declared support is validated. |
| 4 | `F004` | `boss_extrude` | rib_pad, review_selectable | `true` | left vertical stiffness rib pad | `F001` | rectangle 42x72 at (-48.0, 0.0) | 12 / blind | 6476.35 mm3 | This feature is source-dimensioned, origin-anchored, fully constrained, and committed only after its declared support is validated. |
| 5 | `F005` | `boss_extrude` | rib_pad, review_selectable | `true` | upper horizontal stiffness rib pad | `F001` | rectangle 72x42 at (0.0, 48.0) | 12 / blind | 6476.35 mm3 | This feature is source-dimensioned, origin-anchored, fully constrained, and committed only after its declared support is validated. |
| 6 | `F006` | `boss_extrude` | rib_pad, review_selectable | `true` | lower horizontal stiffness rib pad | `F001` | rectangle 72x42 at (0.0, -48.0) | 12 / blind | 6476.35 mm3 | This feature is source-dimensioned, origin-anchored, fully constrained, and committed only after its declared support is validated. |
| 7 | `F007` | `cut_extrude` | seal_recess, review_selectable | `true` | diameter 92 H8 seal and cover recess | `F002` | circle R46 at (0.0, 0.0) | 6 / blind | -39885.7 mm3 | This feature is source-dimensioned, origin-anchored, fully constrained, and committed only after its declared support is validated. |
| 8 | `F008` | `cut_extrude` | bearing_seat, review_selectable | `true` | diameter 80 H7 paired-6208 bearing seat | `F002` | circle R40 at (0.0, 0.0) | 36 / blind | -150796 mm3 | This feature is source-dimensioned, origin-anchored, fully constrained, and committed only after its declared support is validated. |
| 9 | `F009` | `cut_extrude` | shaft_clearance, review_selectable | `true` | diameter 50 shaft clearance through bore | `F002` | circle R25 at (0.0, 0.0) | 56 / through_all | -39269.9 mm3 | This feature is source-dimensioned, origin-anchored, fully constrained, and committed only after its declared support is validated. |
| 10 | `F010` | `cut_extrude` | indexer_hole_pattern, review_selectable | `true` | eight diameter 9 indexer holes on diameter 108 PCD | `F002` | 8x R4.5 on PCD 108 | 56 / through_all | -28500.5 mm3 | This feature is source-dimensioned, origin-anchored, fully constrained, and committed only after its declared support is validated. |
| 11 | `F011` | `cut_extrude` | cover_hole_pattern, review_selectable | `true` | four diameter 7 cover holes on diameter 104 PCD | `F002` | 4x R3.5 on PCD 104 | 56 / through_all | -8620.53 mm3 | This feature is source-dimensioned, origin-anchored, fully constrained, and committed only after its declared support is validated. |
| 12 | `F012` | `cut_extrude` | frame_mount_hole, review_selectable | `true` | frame mounting through hole 1 | `F001` | circle R7 at (85.0, 65.0) | 20 / through_all | -3078.76 mm3 | This feature is source-dimensioned, origin-anchored, fully constrained, and committed only after its declared support is validated. |
| 13 | `F013` | `cut_extrude` | frame_mount_hole, review_selectable | `true` | frame mounting through hole 2 | `F001` | circle R7 at (-85.0, 65.0) | 20 / through_all | -3078.76 mm3 | This feature is source-dimensioned, origin-anchored, fully constrained, and committed only after its declared support is validated. |
| 14 | `F014` | `cut_extrude` | frame_mount_hole, review_selectable | `true` | frame mounting through hole 3 | `F001` | circle R7 at (-85.0, -65.0) | 20 / through_all | -3078.76 mm3 | This feature is source-dimensioned, origin-anchored, fully constrained, and committed only after its declared support is validated. |
| 15 | `F015` | `cut_extrude` | frame_mount_hole, review_selectable | `true` | frame mounting through hole 4 | `F001` | circle R7 at (85.0, -65.0) | 20 / through_all | -3078.76 mm3 | This feature is source-dimensioned, origin-anchored, fully constrained, and committed only after its declared support is validated. |
| 16 | `F016` | `cut_extrude` | frame_counterbore, review_selectable | `true` | diameter 24 by 10 frame counterbore 1 | `F001` | circle R12 at (85.0, 65.0) | 10 / blind | -2984.51 mm3 | This feature is source-dimensioned, origin-anchored, fully constrained, and committed only after its declared support is validated. |
| 17 | `F017` | `cut_extrude` | frame_counterbore, review_selectable | `true` | diameter 24 by 10 frame counterbore 2 | `F001` | circle R12 at (-85.0, 65.0) | 10 / blind | -2984.51 mm3 | This feature is source-dimensioned, origin-anchored, fully constrained, and committed only after its declared support is validated. |
| 18 | `F018` | `cut_extrude` | frame_counterbore, review_selectable | `true` | diameter 24 by 10 frame counterbore 3 | `F001` | circle R12 at (-85.0, -65.0) | 10 / blind | -2984.51 mm3 | This feature is source-dimensioned, origin-anchored, fully constrained, and committed only after its declared support is validated. |
| 19 | `F019` | `cut_extrude` | frame_counterbore, review_selectable | `true` | diameter 24 by 10 frame counterbore 4 | `F001` | circle R12 at (85.0, -65.0) | 10 / blind | -2984.51 mm3 | This feature is source-dimensioned, origin-anchored, fully constrained, and committed only after its declared support is validated. |
| 20 | `F020` | `cut_extrude` | dowel_hole, review_selectable | `true` | primary diameter 8 H7 datum-C dowel hole | `F001` | circle R4 at (70.0, 0.0) | 20 / through_all | -1005.31 mm3 | This feature is source-dimensioned, origin-anchored, fully constrained, and committed only after its declared support is validated. |
| 21 | `F021` | `cut_extrude` | dowel_hole, review_selectable | `true` | secondary diameter 8 H7 dowel hole | `F001` | circle R4 at (-70.0, 0.0) | 20 / through_all | -1005.31 mm3 | This feature is source-dimensioned, origin-anchored, fully constrained, and committed only after its declared support is validated. |
| 22 | `F022` | `cut_extrude` | lightening_pocket, review_selectable | `true` | 36 x 34 x 10 non-through lightening pocket 1 | `F001` | rectangle 36x34 at (86.0, 30.0) | 10 / blind | -12240 mm3 | This feature is source-dimensioned, origin-anchored, fully constrained, and committed only after its declared support is validated. |
| 23 | `F023` | `cut_extrude` | lightening_pocket, review_selectable | `true` | 36 x 34 x 10 non-through lightening pocket 2 | `F001` | rectangle 36x34 at (-86.0, 30.0) | 10 / blind | -12240 mm3 | This feature is source-dimensioned, origin-anchored, fully constrained, and committed only after its declared support is validated. |
| 24 | `F024` | `cut_extrude` | lightening_pocket, review_selectable | `true` | 36 x 34 x 10 non-through lightening pocket 3 | `F001` | rectangle 36x34 at (-86.0, -30.0) | 10 / blind | -12240 mm3 | This feature is source-dimensioned, origin-anchored, fully constrained, and committed only after its declared support is validated. |
| 25 | `F025` | `cut_extrude` | lightening_pocket, review_selectable | `true` | 36 x 34 x 10 non-through lightening pocket 4 | `F001` | rectangle 36x34 at (86.0, -30.0) | 10 / blind | -12240 mm3 | This feature is source-dimensioned, origin-anchored, fully constrained, and committed only after its declared support is validated. |

## Native SolidWorks topology save/reopen verification

- SolidWorks revision: `34.0.0`
- Native topology authority: `true`
- Stored and reopened references: `222`
- Required sketch references: `62`
- Unresolved required references: `0`
- Exact saved/reopened semantic-key set equality: `PASS`
- Body/volume/bounding-box reopen checks: `PASS`
- Safety locks: `reviewOnly=true`, `accepted=false`, `ruleEnabled=false`, `packagingGated=true`
