__package__ = 'archivebox.core'

import sys

from django.apps import AppConfig


class CoreConfig(AppConfig):
    name = 'core'

    def ready(self):
        """Register the archivebox.core.admin_site as the main django admin site"""
        from core.admin_site import register_admin_site
        register_admin_site()

        # Auto-start the orchestrator when running the web server
        self._maybe_start_orchestrator()

    def _maybe_start_orchestrator(self):
        """Start the orchestrator if we're running a web server."""
        import os

        # Don't start orchestrator during migrations, shell, tests, etc.
        # Only start when running: runserver, daphne, gunicorn, uwsgi
        if not self._is_web_server():
            return

        # Don't start if RUN_ORCHESTRATOR env var is explicitly set to false
        if os.environ.get('RUN_ORCHESTRATOR', '').lower() in ('false', '0', 'no'):
            return

        # Don't start in autoreload child process (avoid double-start)
        if os.environ.get('RUN_MAIN') != 'true' and 'runserver' in sys.argv:
            return

        try:
            from workers.orchestrator import Orchestrator

            if not Orchestrator.is_running():
                # Start orchestrator as daemon (won't exit on idle when started by server)
                orchestrator = Orchestrator(exit_on_idle=False)
                orchestrator.start()
        except Exception as e:
            # Don't crash the server if orchestrator fails to start
            import logging
            logging.getLogger('archivebox').warning(f'Failed to auto-start orchestrator: {e}')

    def _is_web_server(self) -> bool:
        """Check if we're running a web server command."""
        # Check for common web server indicators
        server_commands = ('runserver', 'daphne', 'gunicorn', 'uwsgi', 'server')
        return any(cmd in ' '.join(sys.argv).lower() for cmd in server_commands)
