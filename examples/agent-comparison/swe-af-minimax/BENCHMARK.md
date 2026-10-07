# Todo App Benchmark Fixture

This directory replaces the broken upstream gitlink that pointed at
`d5fbea402cd490e36d57a5d588aa91e58768f11a`, an unavailable repository
object.

## Task

Build a Node.js CLI todo app with:

- `add`, `list`, `complete`, and `delete` commands.
- Persistent JSON-file storage.
- Automated tests.
- Git initialized with meaningful commits.

The benchmark evaluator is in `examples/agent-comparison/evaluator/`.

## Reproducibility rule

The agent output must be generated in a fresh working copy of this fixture.
The fixture itself is intentionally empty apart from `.gitkeep`; it is not a
pre-solved project and must not contribute implementation or quality points.

The original upstream gitlink target could not be recovered from the public
Git object database. This fixture therefore restores the benchmark as a
reproducible **task baseline**, not as a claim that the missing upstream
repository contents were recovered byte-for-byte.

Original upstream gitlink SHA:
`d5fbea402cd490e36d57a5d588aa91e58768f11a`.
