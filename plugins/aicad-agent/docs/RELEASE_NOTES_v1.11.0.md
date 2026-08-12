# aicad-agent v1.11.0

v1.11.0 closes the temporary-review, native-dimension and half-finished architectural output gaps found during real AutoCAD 2025 and villa contract calibration.

## Persistent, idempotent review launch

- Every GUI-launched HTML file is copied to a persistent content-addressed path, including ASCII temporary sources.
- CLI and Agent tools default to `review_launch=never`; repeated explicit `auto` calls for identical bytes are suppressed, while `always` is the only force-reopen mode.
- Launch JSON records source/staged paths and the persistent launch ledger. A deleted test directory no longer invalidates an open review page.

## Protocol 4 native dimensions

- Adds constrained `dimension` plan steps for horizontal, vertical and aligned native dimensions with overall/grid/partition/opening/general purposes.
- AICAD protocol 4 transports measurement, orientation, base-offset proof, DIMSTYLE and purpose metadata. DXF, SCR, audit and manifest output retain the same semantics.
- AutoCAD 2025 Core Console proved that its Application COM object is unavailable (`nil`), so the bundle now uses the shared native `-DIMSTYLE`, `DIMLINEAR` and `DIMALIGNED` execution path. Real save/reopen tests preserve five native dimensions, measurements, layer, style and AICAD XData.

## Architectural prevention rules

- `ARCH-D039` requires desktop/headless native-dimension parity.
- `ARCH-D040` forbids an artificial origin super-line and requires union-invariant physical segment splitting at dimension anchors.
- `PROD-G010` forbids exposing partial CAD when the requested delivery class is directly producible/constructible; any missing non-compensatory gate yields blocker reports only.
- Sofa, bed, casework, sanitary and appliance details remain typed selectable linework. The calibrated villa plan now passes its geometry and native-dimension bindings, but remains blocked because the complete drawing set, authority evidence and authorized release are absent.

Safety locks remain `reviewOnly=true`, `accepted=false`, `ruleEnabled=false`, and `packagingGated=true`. The plugin does not self-sign construction or manufacturing output.
