# Third-party notices

The core Python runtime uses the Python standard library and is distributed under the project MIT license.

Optional packaging QA dependencies:

- ezdxf — MIT License
- jsonschema — MIT License
- Pillow — HPND License
- Shapely — BSD 3-Clause License

Optional native hosts:

- AutoCAD is a product of Autodesk. No Autodesk binaries are included.
- SolidWorks is a product of Dassault Systèmes. The default release does not include SolidWorks interop assemblies or other proprietary binaries. Users build the host locally against their licensed installation.

The package does not grant licenses for AutoCAD, SolidWorks, or their SDKs.

## Optional visual QA runtime

Playwright (Apache-2.0) may be supplied externally to run the real-browser reference-preview QA script. It is not redistributed in the default plugin archive. The script can use an installed Chrome or Edge executable.
