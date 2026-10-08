# Grafy Python Plugin

Self-contained System publication input for the Python node (ADR 0012). The
project vendors the exact Grafy SDK wheel referenced by `uv.lock`; it does not
resolve dependencies through the monorepo Workspace.

The published Plugin identity is `external.python`. It runs user code from node
config in the isolated Plugin sandbox:

- `python.transform@1` runs applied code on one input. Its ports are generic
  over `input` and `output`, and each node chooses their shapes through config.
- `python.inspect@1` derives the contract of code for Apply. It is never a
  canvas node.

Port types are the artifact type dependencies in `declaration.py`. Adding a type
is a new release.
