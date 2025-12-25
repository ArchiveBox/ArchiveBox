"""
Workers admin module.

The orchestrator/worker system doesn't need Django admin registration
as workers are managed via CLI commands and the orchestrator.
"""

__package__ = 'archivebox.workers'


def register_admin(admin_site):
    """No models to register - workers are process-based, not Django models."""
    pass
