"""AgentForge backend integrations (Agent 9, ForgeHacks 2026).

Currently ships:
- ``n8n_export`` — converts a run snapshot (GET /api/runs/{id} shape) into an
  importable n8n workflow JSON. Consumed by the backend route
  ``POST /api/runs/{id}/export/n8n`` via
  ``from integrations.n8n_export import export_n8n`` (cwd = backend/).

The package is stdlib-only at import time so the backend can import it lazily
without pulling optional dependencies.
"""

from __future__ import annotations

from integrations.n8n_export import (
    EXPORTER_VERSION,
    N8nExportError,
    export_n8n,
)

__all__ = ["EXPORTER_VERSION", "N8nExportError", "export_n8n"]
