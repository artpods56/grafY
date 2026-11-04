"""Agent-owned canvas objects: history, keys, and model resolution (ADR 0021).

These are application owners, not HTTP. Nothing here imports a route module or a request
resource: the boundary guard in ``tests/unit/architecture/test_import_boundaries.py``
walks this package and fails if it does.
"""
