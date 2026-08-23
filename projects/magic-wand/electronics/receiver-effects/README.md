# Receiver Effects A0

Status: design input only; fabrication is blocked.

This is the independent media receiver direction. It is intentionally separate
from both the existing receiver baseline and the wand order. It contains only
the NINA-B302 radio/MCU concept, protected 5 V / 2 A USB-C input, 3.3 V logic,
an 8-pin GC9A01A module interface, MAX98357A I2S amplifier with differential
4 ohm speaker connector, and a discrete 3.3 V RGB status LED. Legacy UART,
optocoupler and 12 V MOSFET actuator channels are not copied.

The exact pin, power, effect and resource design inputs are in
receiver-effects-contract.json. fabrication-gate.json is authoritative for
ordering: there are no KiCad sources, native ERC/DRC, Gerber, drill, qualified
BOM or placement files yet, so fabrication_authorized is false.

The portable firmware can host-test eight isolated sessions and procedural
display/audio effects. That evidence does not close target, power, RF, EMC,
thermal, acoustic or manufacturing gates.
