# MW-M-001 handle shell review drawing - AI CAD audit

- Schema: `2.0`
- Domain: `mechanical`
- Units: `mm`
- Origin: `(0, 0)`
- Tolerance: `0.001`
- Source SHA-256: `ef6eb794ff922560e1584707ce49276e6c37f19b189bd534050fbf9b50ce3631`
- Entity count: `16`

| # | ID | Type | Layer | Roles | Depends on | Editable | Purpose | Geometry | Constraints | Reasoning |
|---:|---|---|---|---|---|---|---|---|---|---|
| 1 | `O1` | `line` | `OUTLINE` | outline | origin | `true` | axial outer profile lower edge | `(0, 0) -> (110, 0); L=110` | horizontal; length=110.0 | Starts the closed typed outline from a controlled datum. |
| 2 | `O2` | `line` | `OUTLINE` | outline | O1 | `true` | axial outer profile far edge | `(110, 0) -> (110, 27); L=27` | start_coincident=O1.end; vertical; length=27.0 | Continues from the preceding endpoint and fixes the transverse extent. |
| 3 | `O3` | `line` | `OUTLINE` | outline | O2 | `true` | axial outer profile upper edge | `(110, 27) -> (0, 27); L=110` | start_coincident=O2.end; horizontal; length=110.0 | Returns parallel to the first edge with the same exact length. |
| 4 | `O4` | `line` | `OUTLINE` | outline | O3 | `true` | axial outer profile closing edge | `(0, 27) -> (0, 0); L=27` | start_coincident=O3.end; vertical; length=27.0; end_coincident=origin | Closes the outline at the controlled start point. |
| 5 | `H1` | `line` | `HIDDEN` | interface | origin | `true` | Show the lower internal cavity boundary. | `(0, 2) -> (110, 2); L=110` | start_offset=origin + (0, 2.0); length=110.0; horizontal | The explicit origin-relative start and exact endpoint make this hidden cavity line deterministic. |
| 6 | `H2` | `line` | `HIDDEN` | interface | origin | `true` | Show the upper internal cavity boundary. | `(0, 25) -> (110, 25); L=110` | start_offset=origin + (0, 25.0); length=110.0; horizontal | The explicit origin-relative start and exact endpoint make this hidden cavity line deterministic. |
| 7 | `C1` | `line` | `CENTER` | datum | origin | `true` | Show the common part axis. | `(0, 13.5) -> (110, 13.5); L=110` | start_offset=origin + (0, 13.5); length=110.0; horizontal | The explicit origin-relative start and exact endpoint make this centerline deterministic. |
| 8 | `E1` | `circle` | `OUTLINE` | shaft | origin | `true` | Show the outside diameter in the end view. | `C=(137, 13.5); R=13.5` | center_offset=origin + (137.0, 13.5); diameter=27.0 | The end-view circle is tied to an explicit origin-relative center and exact diameter. |
| 9 | `E2` | `circle` | `HOLE` | hole | origin | `true` | Show the cavity diameter in the end view. | `C=(137, 13.5); R=11.5` | center_offset=origin + (137.0, 13.5); diameter=23.0 | The end-view circle is tied to an explicit origin-relative center and exact diameter. |
| 10 | `D1` | `dimension` | `DIMENSION` | interface | O1 | `true` | Control the axial part length. | `P1=(0, 0); P2=(110, 0); BASE=(0, -8); KIND=horizontal; PURPOSE=overall; STYLE=AICAD_MECH; M=110` | dimension_measurement=110.0; dimension_orientation=0; base_offset=O1.start + (0.0, -8.0) | The dimension is bound to earlier physical geometry and carries an explicit measurement, orientation and base offset. |
| 11 | `D2` | `dimension` | `DIMENSION` | interface | O1, O2 | `true` | Control the outside diameter envelope. | `P1=(110, 0); P2=(110, 27); BASE=(118, 0); KIND=vertical; PURPOSE=general; STYLE=AICAD_MECH; M=27` | dimension_measurement=27.0; dimension_orientation=90; base_offset=O1.end + (8.0, 0) | The dimension is bound to earlier physical geometry and carries an explicit measurement, orientation and base offset. |
| 12 | `N1` | `line` | `NOTE_FRAME` | interface | origin | `true` | bounded note frame lower edge | `(0, 41) -> (120, 41); L=120` | horizontal; length=120; start_offset=origin + (0, 41.0) | Starts the closed typed outline from a controlled datum. |
| 13 | `N2` | `line` | `NOTE_FRAME` | interface | N1 | `true` | bounded note frame far edge | `(120, 41) -> (120, 53); L=12` | start_coincident=N1.end; vertical; length=12.0 | Continues from the preceding endpoint and fixes the transverse extent. |
| 14 | `N3` | `line` | `NOTE_FRAME` | interface | N2 | `true` | bounded note frame upper edge | `(120, 53) -> (0, 53); L=120` | start_coincident=N2.end; horizontal; length=120 | Returns parallel to the first edge with the same exact length. |
| 15 | `N4` | `line` | `NOTE_FRAME` | interface | N3, N1 | `true` | bounded note frame closing edge | `(0, 53) -> (0, 41); L=12` | start_coincident=N3.end; vertical; length=12.0; end_coincident=N1.start | Closes the outline at the controlled start point. |
| 16 | `NT` | `text` | `NOTES` | interface | origin | `true` | Place the review limitation inside its note frame. | `P=(60, 47); H=2.5; R=0; TEXT=SIDE APERTURE IS DATUM ONLY; ADD NATIVE SIDE-PLANE CUT BEFORE FABRICATION` | position_offset=origin + (60.0, 47.0); text_height=2.5; rotation=0 | Middle-center alignment and the frame dimensions keep the complete text inside the declared card. |
