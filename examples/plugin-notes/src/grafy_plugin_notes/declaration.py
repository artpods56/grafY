from grafy_core.plugins import Plugin

# Workspace-local slug. Origin is assigned at catalog install time, not here.
NOTES = Plugin(slug="notes", title="Notes")

# Native tools would require a named image digest (python-uv-gdal), not apt.
RUNTIME_PROFILE = "python-uv"
