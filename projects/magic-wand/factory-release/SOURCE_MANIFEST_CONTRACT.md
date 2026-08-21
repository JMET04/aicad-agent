# Upstream source-manifest contract

The integration builder accepts fixed upstream files relative to
`projects/magic-wand`:

- `mechanical/factory-rfq/reports/factory-delivery-manifest.json` (primary)
- `mechanical/factory-rfq/reports/mechanical-source-manifest.json` (compatibility)
- `electronics/factory-release-source-manifest.json`

The primary mechanical schema is
`aicad_magic_wand_mechanical_factory_delivery_manifest_v1`; the compatibility
copy uses `aicad_magic_wand_mechanical_source_manifest_v1`. The two mechanical
documents must be byte-semantically identical after removing only `schema`.
The electronics schema is
`aicad_magic_wand_electronics_source_manifest_v1`. All three documents declare
`status=frozen`; both domains declare the same package/release revision,
portable POSIX-relative evidence paths, and exact `{path,size,sha256}` references. Preview evidence
also carries `previewOfRole`, `subjectId`, and `sourceSha256`.

The mechanical document contains `coordinateSystem`, exactly nine `parts`,
exactly two `assemblies`, and `receiverInterface`. The integration adapter
selects only the frozen core roles, converts the documented right-handed datum
to the numeric core basis, normalizes portable process identifiers, and binds
each actual preview to its exact subject/source role/SHA. It also declares a
neutral RFQ recipient requirement inventory but never supplier authority.

The electronics document contains `coordinateSystem`, authority-backed
`suppliers`, exactly two `pcbs`, `gateAssertions`, and `receiverInterface`.
PCB objects are directly compatible with the corresponding manufacturing
package array. Each board assertion is exact and must state:

```json
{
  "ercErrors": 0,
  "drcViolations": 0,
  "unconnected": 0,
  "exclusions": 0,
  "suppressions": 0
}
```

The electronics `receiverInterface.artifact.sha256`, mechanical
`receiverInterface.artifact.sha256`, and mechanical
`receiverInterface.consumedSha256` must be identical. The integration layer
does not infer or repair a mismatch.
The receiver routes keep KiCad's internal `top-left/right/down` millimetre
basis. The mechanical interface mirror must explicitly declare the
`bottom-left/right/up` board frame and case-centred mechanical frame with:

- `x_board=x_k`, `y_board=42-y_k`;
- `x_case=x_board-25`, `y_case=y_board-21`;
- `caseShiftMm=[-25,-21]`.

The builder independently recomputes both directions for every mounting hole,
connector centre, and RF keepout vertex. The receiver native-board SHA must be
identical in the PCB artifact, frozen-routes document, interface artifact, and
both domain manifests. The interface artifact SHA must likewise equal the
mechanical consumed/actual SHA. A declared `transformVerified` or `hashMatch`
boolean never substitutes for these recomputations.


The wand interface is a separate, stricter contract. Both source manifests use
the key `wandInterface`; the only artifact path is
`electronics/wand/wand-electromechanical-interface.json`. The artifact must
declare schema `aicad_wand_electromechanical_interface_v1`, status `FROZEN`,
and integer `authorityReleaseBlockedRefs=0`. The mechanical manifest mirrors
all interface semantics and records the identical artifact
`consumedSha256`/`actualSha256`; the electronics manifest mirrors its
canonical board, frozen-routes, and native-DRC references.

The builder independently recomputes the wand transform
`X=x_source-7.5`, `Z=y_source+9.0` and its inverse for all nine present
references. It also closes the canonical board SHA through the package PCB,
interface, both source manifests, the interface's `sourceRoutes.sourceBoard`,
and the frozen-routes document. Native DRC must be the same exact report used
by the zero-error gate. The lock preserves the controlled SW1 four-pad/0.25 mm
button stack, J1 16-contact/four-DIP/two-locator +X mating opening, H1/H2 2.4 mm
NPTH positions with H3/H4 absent, NINA full-ground/10 mm metal/5 mm casing
keepout, nonmetallic retention, and positive-clearance board-channel semantics.

Receiver remains governed by its independently approved v1 interface:
`aicad_receiver_mechanical_interface_v1` with lowercase `status=frozen`.
Its connector-authority and coordinate validator is not silently coerced into
the wand schema.

Domain manifests may include `upstreamEvidence`, an array of additional exact
references such as raw native reports, section/interference audits, or
supplier source snapshots. These files are locked and included in the
delivery manifest but do not replace any mandatory package artifact role.
