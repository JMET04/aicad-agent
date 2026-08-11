# aicad-agent v1.10.0

- Removed a stale AutoCAD protocol-v2 limitation from the public capability matrix; REL-G021 now rejects contradictions between top-level claims, host matrices and native persistence evidence.

- DXF output now uses a standards-valid AC1018 container for semantic layers, linetypes, lineweights and constrained TEXT. REL-G020 permanently requires declared-version parity plus real AutoCAD import/save/reopen persistence checks.

v1.10.0 closes a gap between architectural drafting rules and the real AutoCAD execution path.

- Axis identifiers and geometry-bound labels can now be authored as constrained `text` plan steps. Their content, middle-centre insertion point, height, rotation, layer, purpose, reasoning and dependencies are audited.
- Schema 2.0 plans compile to backward-compatible AICAD protocol 3. LINE, CIRCLE, ARC and TEXT records retain their semantic layer; AutoCAD creates native entities with AICAD XData.
- Unicode BMP text remains UTF-8 in plans/audits and is transported through ASCII CAD artifacts as `\U+XXXX`, preventing locale-dependent mojibake.
- The architectural layer profile is enforced in DXF, SCR and AutoCAD: cut, projection, secondary, hidden, datum and annotation layers receive their declared lineweights and linetypes.
- New regression rules `ARCH-D030`–`ARCH-D035` require native axis text, semantic style transport parity, schema-to-host entity parity, unique redundant-door recovery, programme-authoritative room categories and exhaustive typed occupancy clearance. `REL-G019` requires generated target files to compile after migrations.
- Every room now cites the source of its declared programme before contents are checked. Vehicles, furniture, casework, sanitary fixtures and appliances all participate in sweep/access clearance unless a reviewed non-occupying semantic class explicitly excludes them.

This remains an engineering candidate. Architectural CAD is exposed only after the complete production drawing set, authority, native-host round trip, visual review and authorized-release gates pass. Review locks remain enabled by default.
