"""Platform-level parsing (Stories 2.2 Part B, 3.2): the shared rules and the parsers for
the formats every module can store (`.txt`, `.md`, `.docx`, `.pdf`), the sandboxed child
process entry (`cli`) and its runner (`runner`).

Only the parse child process runs the parsers, under its time and memory limits; the api
and the worker's own process never import `parsers`. Customer files are untrusted."""
