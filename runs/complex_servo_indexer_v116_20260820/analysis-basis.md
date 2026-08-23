# Independent preliminary calculations — SIFC-220-REV-A

All values are in N, mm, MPa and hours unless stated otherwise. These conservative calculations gate controlled geometry; they are not a substitute for signed design verification.

## Strength and stiffness

- Conservative boss ligament area: A = 2 × 25 × 36 = 1,800 mm².
- Direct radial stress: 4,500 / 1,800 = 2.50 MPa.
- Conservative paired-ligament section modulus: Z = 2 × 36 × 25² / 6 = 7,500 mm³.
- Moment stress: 350,000 / 7,500 = 46.67 MPa.
- Combined nominal stress: 49.17 MPa; 2 g abnormal nominal stress: 98.34 MPa.
- Minimum 7075-T651 yield basis used for review: 435 MPa.
- Abnormal-case yield factor: 435 / 98.34 = 4.42, above the required 2.0.
- Base bending check, conservative full-width section: Z = 180 × 20² / 6 = 12,000 mm³; 350,000 / 12,000 = 29.17 MPa.
- Elastic deflection is bounded by the 20 mm base, Ø130 boss and four integral rib pads; native geometry volume/bounding box and feature integrity are independently read back. Detailed FEA remains a release prerequisite, not a generation prerequisite.

## Joint and bearing

- M12 class 10.9 tensile stress area: 84.3 mm².
- Per-bolt target preload: 0.70 × 830 × 84.3 = 48.98 kN.
- Four-bolt clamp: 195.9 kN; slip capacity at μ=0.15 is 29.4 kN.
- Service shear ratio: 29.4 / 4.5 = 6.53; abnormal 2 g ratio = 3.27.
- Assembly torque estimate with K=0.20: T = 0.20 × 48.98 kN × 12 mm = 117.6 N·m per bolt; final torque must follow validated lubricant/process data.
- 6208 review dynamic rating basis: C = 32.5 kN; equivalent dynamic load P = 5.2 kN.
- L10 = (C/P)^3 × 10^6 = 244.1 million revolutions.
- At 120 r/min, L10h = 244.1e6 / (60 × 120) = 33,900 h, above 20,000 h.

## Thermal and tolerance stack

- Differential aluminium/steel radial-fit growth from 20 °C to 60 °C: (23.6−11.5)e−6 × 80 × 40 = 0.0387 mm diametral clearance increase.
- H7 housing fit is retained because the outer rings are stationary; axial retention and anti-creep risk remain controlled by cover clamp, surface finish and inspection.
- Bearing-pair axial stack: seat depth 36.00 +0.05/0.00 mm against two nominal 18 mm bearings; cover uses a controlled shim/shoulder allowance of 0.05–0.15 mm.
- Coaxiality target between Ø50 clearance and datum B is 0.03 mm; mounting and cover patterns have true position Ø0.10 to A|B.

## Failure modes and controls

- Bearing-seat creep: H7 fit, Ra 1.6, axial cover and inspection.
- Frame slip: preload calculation, dowels and torque process.
- Ligament crack or boss yielding: 25 mm wall, abnormal FOS 4.42 and later FEA.
- Misalignment: datum A/B/C, flatness/perpendicularity/coaxiality controls.
- Thermal loosening: temperature stack above and cover retention.
- Tool/assembly interference: counterbore, spanner and cover-envelope checks in the drawing review.

