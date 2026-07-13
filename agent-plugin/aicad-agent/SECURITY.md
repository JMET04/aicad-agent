# Security and execution policy

- The default caller-plan workflow needs no API key and makes no model-provider network call.
- AICAD execution records are ASCII and restricted to validated entity records.
- All output paths are resolved locally; temporary JSON writes are atomic.
- Unsupported constraints or host capabilities fail closed.
- Native CAD save/reopen checks are never inferred from portable DXF or STEP generation.
- Packaging rules remain review-only until separately accepted by a responsible reviewer.

Do not commit API keys, CAD customer files, personal paths, temporary jobs, or native-host credentials.

