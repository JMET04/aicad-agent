# Magic Wand factory release

This directory is the controlled integration layer for the magic-wand factory
package. It consumes frozen mechanical and electronics source manifests,
verifies every referenced byte, builds the canonical
`aicad_manufacturing_release_package_v1`, and delegates the manufacturing gates
and reviewer rendering to the repository's frozen manufacturing-release core.

The generated package is a digital RFQ / PCB-prototype candidate only. It is
not a purchase order, supplier acknowledgement, tooling release, production
release, or permission to cut steel. The following locks are invariant:

- `factoryHandoffReady=false` until a real supplier-owned confirmation for the
  exact package revision and complete artifact hash map is received.
- `productionReady=false`.
- `productionReleaseAuthorized=false`.
- `toolSteelCutAuthorized=false`.
- `massProductionAuthorized=false`.

## Rebuild

Run from the repository root with the standard-library Python runtime:

```powershell
python projects/magic-wand/factory-release/build_factory_release.py --wait-seconds 0
python -m unittest discover -s tests -p test_magic_wand_factory_release.py -v
```

The normal build never refreshes upstream hashes. It reads
`source-lock.json`; any changed package, artifact, gate report, preview, or
interface file fails closed. Creating or refreshing the lock is a separate
review action and is permitted only when both upstream manifests declare
`status=frozen`, use portable paths, and pass all domain-specific checks:

```powershell
python projects/magic-wand/factory-release/build_factory_release.py --freeze-source-lock
```

The builder writes the package and controlled generated evidence under this
directory, then asks the core builder to create a fresh `built/` directory.
The main review entry is:

`built/magic-wand-factory-release.review.html`

## Truth boundary

Mechanical subjects may use the explicitly neutral
`unassigned_rfq_recipient` profile for a digital RFQ candidate. That profile
is project-authored, claims no supplier authority, and cannot unlock PCB
fabrication or factory handoff. PCB subjects require a real, current,
authority-backed fabrication/assembly capability record. No project-authored
document is converted into a supplier confirmation.

See [STANDARDIZED_FACTORY_WORKFLOW.md](STANDARDIZED_FACTORY_WORKFLOW.md) and
[SOURCE_MANIFEST_CONTRACT.md](SOURCE_MANIFEST_CONTRACT.md) for the complete
repeatable process and upstream contract.
