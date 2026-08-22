# Magic Wand printable enclosure Rev A0

Status: **VERIFIED_PRINT_CANDIDATE**

## Print settings

- Shells: PETG/ASA/ABS/PA12, 0.20 mm layers, 4 perimeters, 35% gyroid.
- Carrier: PETG or PA12, 0.20 mm layers, 4 perimeters, 35% gyroid.
- Upper/lower shells: print with the flat split face on the bed; supports should not be required.
- Carrier: print PCB rails upward. Rear cap and rod connector: print flange on the bed.
- First fit: deburr the seam and holes; do not force the PCB or cell.

## Power reservation

- Maximum reserved pack envelope: **11 x 6 x 42 mm** including protection/insulation.
- Pack: protected 1S LiPo, 10k NTC, JST-SH 1.0 mm 3-pin harness.
- Install a pull ribbon beneath the cell. Keep at least the modeled 8 mm lead-bend reserve.
- The battery begins at z=41 mm, leaving 11 mm after the RF antenna keepout ends at z=30 mm.
- Confirm J2 BAT+/NTC/GND order and polarity with a multimeter before connection.

## Haptic reservation

- Reserved actuator envelope: 10 mm diameter x 3.4 mm thick coin LRA/ERM.
- Fit in the upper-shell printed cup with thin nonconductive foam; route its two-wire lead to J3.
- The metal envelope begins at z=35 mm, leaving 5 mm after the RF antenna keepout.
- The exact actuator must match the DRV2605L library/configuration used by target firmware.

## Wand rod

- Use an 8 mm solid GFRP rod cut to 195 mm.
- Insert it to the socket bottom at case z=116 mm; the resulting target overall length is 315 mm.
- Exposed rod above the connector is 179 mm. Verify the first article before adhesive bonding.
- Do not substitute conductive carbon-fiber or metal rod without a renewed RF/mechanical review.

## Assembly order

1. Deburr and dry-fit both shells, rear cap, rod connector and plunger.
2. Seat the protected cell in the carrier with a pull ribbon and thin nonconductive foam if needed.
3. Route the lead through the J2 channel. Do not crease or pinch the NTC lead.
4. Fit the 10 mm haptic actuator in the upper-shell cup and route its lead to J3.
5. Install the PCB component-side upward on H1/H2 using nylon M2 screws.
6. Fit the press-to-arm plunger and verify free return before closing the shell.
7. Close with M2x12 screws. Start all screws before tightening; do not overtighten printed bosses.
8. Perform USB charge, button, haptic, radio range and gesture tests before attaching the decorative rod.

This is a verified prototype print candidate, not an injection-mold release. Battery supplier drawing,
actual printed shrinkage and the first-article fit remain physical acceptance gates.
