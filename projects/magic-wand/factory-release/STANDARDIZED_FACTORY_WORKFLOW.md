# Standardized factory-release workflow

## 1. Freeze design inputs

1. Freeze package ID, revision, units, right-handed coordinate systems, and
   subject identifiers.
2. Freeze the receiver PCB-to-enclosure interface file after the final native
   PCB DRC. The electronics manifest publishes its SHA-256; the mechanical
   manifest records the exact consumed SHA-256.
3. Reject any path containing a probe, temporary, WIP, local user, drive, or
4. Recompute the receiver `top-left/y-down` to `bottom-left/y-up` and
   case-centred transforms in both directions for every hole, connector, and
   RF keepout vertex. Bind the same native-board SHA through PCB, routes,
   interface and mechanical-consumption evidence.
   traversal component.

## 2. Close mechanical evidence

1. Export nine unique manufactured parts as authentic native part CAD, STEP,
   a manufacturing DXF, actual source-bound 2D/3D previews, and a passing
   native reopen log.
2. Export the wand and receiver assemblies as authentic native assemblies and
   STEP, plus general, exploded, and section drawings; actual source-bound
   2D/3D previews; work and inspection PDFs; exact BOM and occurrence
   positions; molding input; native reopen; and interference logs.
3. Require each part to occur in at least one assembly BOM and require BOM
   quantities to equal positioned occurrence counts.
4. Keep all molded subjects in the seven-field tooling-input closure. These
   are RFQ/DFM inputs, not permission to cut production steel.

## 3. Close electronics evidence

1. Reopen both boards in native KiCad and bind the project, schematic, and
   board bytes to the native logs.
2. Require exact zero ERC errors, zero DRC violations, zero unconnected items,
   and zero exclusions/suppressions for both the wand and receiver boards.
3. Export every native fabrication layer: all four copper layers, F/B paste,
   F/B mask, F/B silk, and Edge.Cuts. Gerber job membership must equal the
   declared/native layer set exactly.
4. Export PTH and NPTH drill files, IPC-D-356, BOM, CPL, schematic PDF,
   assembly/fabrication drawings and notes, a STEP model, actual hash-bound
   schematic/board/assembly/fabrication/3D previews, CAM log, and native reopen
   log.
5. Bind a current supplier-owned capability source for PCB fabrication and
   assembly. A neutral RFQ recipient is not valid for this domain.

## 4. Freeze and build

1. Validate the two upstream domains and their exact artifact references. For
   mechanical, require the primary factory-delivery manifest and compatibility
   source manifest to differ only by schema; never select whichever WIP file
   happens to be newest.
2. Freeze `source-lock.json` and `manufacturing-release-package.json` only
   after all source bytes are stable.
3. On every ordinary build, re-hash the source manifests, package, interface,
   and all package artifacts before invoking the frozen core validator.
4. Build into a new staging directory, validate the package-specific reviewer
   DOM, then atomically publish the `built/` directory.
5. Emit portable validation, blockers, a digital-candidate manifest when a
   domain passes, a delivery manifest, and per-blocker repair actions.

## 5. Review and external release

1. Open the package-specific HTML reviewer and inspect every subject in both
   the 2D and 3D tabs.
2. Verify the preview count closure (nine parts x two, two assemblies x two,
   two PCBs x five = 32 actual previews) and follow the linked native,
   exchange, drawing, PDF, and CAM evidence.
3. Resolve every digital blocker and rebuild; never edit readiness fields by
   hand.
4. Send the frozen candidate to the selected suppliers. Only genuine
   supplier-owned per-package confirmation may unlock factory handoff.
5. Professional approval, DFM signoff, tooling authorization, pilot approval,
   and mass-production release remain external controlled actions.
