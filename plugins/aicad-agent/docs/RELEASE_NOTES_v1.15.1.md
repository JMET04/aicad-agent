# aicad-agent 1.15.1

## Reviewer-first drawing opening

- Generic requests to open, show, view, inspect, or look at drawings now resolve only to the current content-bound interactive drawing modifier.
- The new `aicad_open_review_request` MCP/CLI boundary requires `data-artifact-role=interactive_drawing_modifier`; arbitrary HTML wrappers and stale showcase pages fail closed.
- Merely supplying a PDF, image, DWG, DXF, STEP, SolidWorks, or KiCad path never authorizes a native application launch.
- Native CAD requires an explicit `open_native_cad=true` signal that reflects the user's request for native editing/output, an existing allowlisted CAD path, and a successfully launched modifier first.
- Responses record the launch order, and native CAD remains blocked when the modifier cannot launch.

## Verification

- Added root and packaged negative regression tests for ambiguous CAD paths, raw PDFs, unmarked HTML, headless review launch, MCP schema defaults, dispatch defaults, and CLI defaults.
- The standardized mechanical/electronics set was assembled into one self-contained 7-document, 17-page modifier with zoom, rotation, paging, local review pins, and JSON note export.
- Browser QA verified the document inventory, five-page PCB view, zoom, annotation workflow, policy metadata, and zero console errors.

This patch changes opening behavior only. It does not grant engineering acceptance, technical readiness, manufacturing authorization, fabrication authorization, or release authorization.
