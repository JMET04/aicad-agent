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

## Assembly order

1. Deburr and dry-fit both shells, rear cap, rod connector and plunger.
2. Seat the protected cell in the carrier with a pull ribbon and thin nonconductive foam if needed.
3. Route the lead through the J2 channel. Do not crease or pinch the NTC lead.
4. Install the PCB component-side upward on H1/H2 using nylon M2 screws.
5. Fit the press-to-arm plunger and verify free return before closing the shell.
6. Close with M2x12 screws. Start all screws before tightening; do not overtighten printed bosses.
7. Perform USB charge, button, radio range and gesture tests before attaching the decorative rod.

This is a verified prototype print candidate, not an injection-mold release. Battery supplier drawing,
actual printed shrinkage and the first-article fit remain physical acceptance gates.
