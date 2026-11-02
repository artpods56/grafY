# Grafy SQL family

Application-owned node family for database queries against an operator-named
PostgreSQL destination.
Its stable identifier is `external.sql`, and it is registered in-process by
`apps/api/src/grafy_api/services/families.py`, resolving `grafy_core` through the
monorepo workspace. SQL stays destination-checked and read-only because query
validation is not a process sandbox.
