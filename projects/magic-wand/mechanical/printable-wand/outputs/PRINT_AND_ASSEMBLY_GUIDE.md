# Magic Wand printable enclosure Rev A0.2

Status: **GEOMETRY_VERIFIED_PHYSICAL_GATES_OPEN**

Computational geometry gates: **PASS**

## Mandatory physical gates still open

- [ ] actualUsbCableSelectedAndFitChecked
- [ ] slicerLayerReviewComplete
- [ ] firstArticlePrintedAndAssembled
- [ ] buttonCycleTestComplete
- [ ] carrierAndRodRetentionPullTestComplete
- [ ] pcbComponentEnvelopeVerified
- [ ] fastenerToolSweepVerified
- [ ] actualUsbCableParameterSelected

This package is not a fully verified print candidate until the actual cable,
slicer layer review and physical first article close the gates above.

## Print settings

- Shells: PETG/ASA/ABS/PA12, 0.20 mm layers, 4 perimeters, 35% gyroid.
- Carrier: PETG or PA12, 0.20 mm layers, 4 perimeters, 35% gyroid.
- Place each flush Y=0 shell split face on the bed.
- Carrier: print PCB rails upward. Rear cap and rod connector: print flange on the bed.
- A real slicer first-layer review remains mandatory.

## Geometry closure

- Frozen factory-design component envelopes: 36/36 bodies, shell/carrier collision 0.0 / 0.0 mm^3.
- M2 driver access: 4 sweeps, 0.25 mm radial clearance, shell/internal collision 0.0 / 0.0 mm^3.
- Shell/carrier collision: 0.0 / 0.0 mm^3.
- Carrier shell-boss relief radius: 2.95 mm.
- Battery side/axial clearance: 0.4 / 0.4 mm.
- Plunger released/pressed collision: 0.0 / 0.0 mm^3.
- USB recess and gauge reach margin: 6.634 / 0.066 mm.
- Complete reserved assembly length: 316.0 mm.

## Power reservation and service

- Maximum protected pack envelope: **11 x 6 x 42 mm** including insulation.
- Thread a removable 3 mm nonconductive strap through both floor slots.
- Install a pull ribbon beneath the cell and retain the modeled 8 mm lead-bend reserve.
- Confirm J2 BAT+/NTC/GND order and polarity before connection.

## Press-to-arm button

- Placeholder: SKQGAFE010, 5.2 x 5.2 x 1.5 mm, 0.25 mm maximum travel.
- Insert MW-P-005 from outside and snap MW-P-006 into its internal groove.
- Verify free return and the printed 0.25 mm hard stop.
- External head remains 4.6 mm diameter x 1.8 mm long.

## USB-C

- J1 and the visible +X opening remain at the frozen coordinates.
- The enlarged feature is an internal-only stepped counterbore.
- The parameterized plug sweep is a geometry gauge, not a selected cable.
- Select and physically fit-test the real cable before release.

## Wand rod

- Use an 8 mm solid GFRP rod cut to 195 mm.
- Insert to case z=116 mm; complete reserved overall length is 316 mm.
- Do not substitute conductive carbon-fiber or metal rod without renewed RF review.

## Assembly order

1. Deburr and dry-fit the shells, cap, connector, plunger and C-retainer.
2. Thread the battery strap and pull ribbon into the carrier.
3. Seat the protected cell and close the strap without crushing the pouch.
4. Route the J2 lead, fit the haptic actuator, and install the PCB on H1/H2.
5. Insert MW-P-005 and snap MW-P-006 into its groove.
6. Verify return and hard-stop travel before closing with M2x12 screws.
7. Perform USB, charging, button, haptic and RF tests before bonding the rod.
