__package__ = 'archivebox.mcp'

from django.apps import AppConfig


class MCPConfig(AppConfig):
    name = 'mcp'
    verbose_name = 'Model Context Protocol Server'
    default_auto_field = 'django.db.models.BigAutoField'
