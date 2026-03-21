"""
Workers admin module.

Background runner processes do not need Django admin registration.
"""

__package__ = 'archivebox.workers'


def register_admin(admin_site):
    """No models to register - workers are process-based, not Django models."""
    pass
