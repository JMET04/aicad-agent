# MW-M-004 rod connector review drawing - AI CAD audit

- Schema: `2.0`
- Domain: `mechanical`
- Units: `mm`
- Origin: `(0, 0)`
- Tolerance: `0.001`
- Source SHA-256: `30933b67298b7170af8a89202067a574f29bedc836af01fd868aaf2aeb4389b6`
- Entity count: `19`

| # | ID | Type | Layer | Roles | Depends on | Editable | Purpose | Geometry | Constraints | Reasoning |
|---:|---|---|---|---|---|---|---|---|---|---|
| 1 | `P1` | `line` | `OUTLINE` | outline | origin | `true` | Define the stepped axial visible profile. | `(0, 0) -> (10, 0); L=10` | length=10.0; horizontal | Each segment continues the exact local part section without a gap. |
| 2 | `P2` | `line` | `OUTLINE` | outline | P1 | `true` | Define the stepped axial visible profile. | `(10, 0) -> (10, 2.2); L=2.2` | length=2.1999999999999993; start_coincident=P1.end; vertical | Each segment continues the exact local part section without a gap. |
| 3 | `P3` | `line` | `OUTLINE` | outline | P2 | `true` | Define the stepped axial visible profile. | `(10, 2.2) -> (25, 2.2); L=15` | length=15.0; start_coincident=P2.end; horizontal | Each segment continues the exact local part section without a gap. |
| 4 | `P4` | `line` | `OUTLINE` | outline | P3 | `true` | Define the stepped axial visible profile. | `(25, 2.2) -> (25, 24.8); L=22.6` | length=22.6; start_coincident=P3.end; vertical | Each segment continues the exact local part section without a gap. |
| 5 | `P5` | `line` | `OUTLINE` | outline | P4 | `true` | Define the stepped axial visible profile. | `(25, 24.8) -> (10, 24.8); L=15` | length=15.0; start_coincident=P4.end; horizontal | Each segment continues the exact local part section without a gap. |
| 6 | `P6` | `line` | `OUTLINE` | outline | P5 | `true` | Define the stepped axial visible profile. | `(10, 24.8) -> (10, 27); L=2.2` | length=2.1999999999999993; start_coincident=P5.end; vertical | Each segment continues the exact local part section without a gap. |
| 7 | `P7` | `line` | `OUTLINE` | outline | P6 | `true` | Define the stepped axial visible profile. | `(10, 27) -> (0, 27); L=10` | length=10.0; start_coincident=P6.end; horizontal | Each segment continues the exact local part section without a gap. |
| 8 | `P8` | `line` | `OUTLINE` | outline | P7 | `true` | Define the stepped axial visible profile. | `(0, 27) -> (0, 0); L=27` | length=27.0; start_coincident=P7.end; vertical; end_coincident=origin | Each segment continues the exact local part section without a gap. |
| 9 | `C1` | `line` | `CENTER` | datum | origin | `true` | Show the common part axis. | `(0, 13.5) -> (25, 13.5); L=25` | start_offset=origin + (0, 13.5); length=25.0; horizontal | The explicit origin-relative start and exact endpoint make this centerline deterministic. |
| 10 | `H1` | `line` | `HIDDEN` | interface | origin | `true` | Show the lower spine-bore boundary. | `(0, 9.8) -> (25, 9.8); L=25` | start_offset=origin + (0, 9.8); length=25.0; horizontal | The explicit origin-relative start and exact endpoint make this hidden bore line deterministic. |
| 11 | `H2` | `line` | `HIDDEN` | interface | origin | `true` | Show the upper spine-bore boundary. | `(0, 17.2) -> (25, 17.2); L=25` | start_offset=origin + (0, 17.200000000000003); length=25.0; horizontal | The explicit origin-relative start and exact endpoint make this hidden bore line deterministic. |
| 12 | `D1` | `dimension` | `DIMENSION` | interface | P1, P4 | `true` | Control the total part length. | `P1=(0, 0); P2=(25, 24.8); BASE=(0, -8); KIND=horizontal; PURPOSE=overall; STYLE=AICAD_MECH; M=25` | dimension_measurement=25.0; dimension_orientation=0; base_offset=P1.start + (0.0, -8.0) | The dimension is bound to earlier physical geometry and carries an explicit measurement, orientation and base offset. |
| 13 | `D2` | `dimension` | `DIMENSION` | interface | P1 | `true` | Control the first axial segment. | `P1=(0, 0); P2=(10, 0); BASE=(0, -14); KIND=horizontal; PURPOSE=general; STYLE=AICAD_MECH; M=10` | dimension_measurement=10.0; dimension_orientation=0; base_offset=P1.start + (0.0, -14.0) | The dimension is bound to earlier physical geometry and carries an explicit measurement, orientation and base offset. |
| 14 | `D3` | `dimension` | `DIMENSION` | interface | P1, P8 | `true` | Control the maximum diameter. | `P1=(0, 0); P2=(0, 27); BASE=(33, 0); KIND=vertical; PURPOSE=general; STYLE=AICAD_MECH; M=27` | dimension_measurement=27.0; dimension_orientation=90; base_offset=P1.start + (33.0, 0.0) | The dimension is bound to earlier physical geometry and carries an explicit measurement, orientation and base offset. |
| 15 | `N1` | `line` | `NOTE_FRAME` | interface | origin | `true` | bounded note frame lower edge | `(0, 41) -> (120, 41); L=120` | horizontal; length=120; start_offset=origin + (0, 41.0) | Starts the closed typed outline from a controlled datum. |
| 16 | `N2` | `line` | `NOTE_FRAME` | interface | N1 | `true` | bounded note frame far edge | `(120, 41) -> (120, 53); L=12` | start_coincident=N1.end; vertical; length=12.0 | Continues from the preceding endpoint and fixes the transverse extent. |
| 17 | `N3` | `line` | `NOTE_FRAME` | interface | N2 | `true` | bounded note frame upper edge | `(120, 53) -> (0, 53); L=120` | start_coincident=N2.end; horizontal; length=120 | Returns parallel to the first edge with the same exact length. |
| 18 | `N4` | `line` | `NOTE_FRAME` | interface | N3, N1 | `true` | bounded note frame closing edge | `(0, 53) -> (0, 41); L=12` | start_coincident=N3.end; vertical; length=12.0; end_coincident=N1.start | Closes the outline at the controlled start point. |
| 19 | `NT` | `text` | `NOTES` | interface | origin | `true` | Place the review limitation inside its note frame. | `P=(60, 47); H=2.5; R=0; TEXT=ADHESIVE BORE IS PROTOTYPE ONLY; COUPON VALIDATION REQUIRED` | position_offset=origin + (60.0, 47.0); text_height=2.5; rotation=0 | Middle-center alignment and the frame dimensions keep the complete text inside the declared card. |
