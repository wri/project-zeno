"""The near-real-time monitoring template.

``registry`` imports this module by name and reads ``TEMPLATE``.
"""

from src.api.services.analysis_templates.nrt_monitoring.recipe import (
    NAME,
    TEMPLATE,
    NrtParams,
)

__all__ = ["NAME", "TEMPLATE", "NrtParams"]
