__package__ = "archivebox.core"

from django.apps import AppConfig
import os


class CoreConfig(AppConfig):
    name = "archivebox.core"
    label = "core"

    def ready(self):
        """Register the archivebox.core.admin_site as the main django admin site"""
        import sys
        from django.utils.autoreload import DJANGO_AUTORELOAD_ENV

        from archivebox.core.admin_site import register_admin_site

        register_admin_site()

        # Import models to register state machines with the registry
        # Skip during makemigrations to avoid premature state machine access
        if "makemigrations" not in sys.argv:
            from archivebox.core import models  # noqa: F401

        pidfile = os.environ.get("ARCHIVEBOX_RUNSERVER_PIDFILE")
        if pidfile:
            should_write_pid = True
            if os.environ.get("ARCHIVEBOX_AUTORELOAD") == "1":
                should_write_pid = os.environ.get(DJANGO_AUTORELOAD_ENV) == "true"
            if should_write_pid:
                try:
                    with open(pidfile, "w") as handle:
                        handle.write(str(os.getpid()))
                except Exception:
                    pass

        def _should_prepare_runtime() -> bool:
            if os.environ.get("ARCHIVEBOX_RUNSERVER") == "1":
                if os.environ.get("ARCHIVEBOX_AUTORELOAD") == "1":
                    return os.environ.get(DJANGO_AUTORELOAD_ENV) == "true"
                return True
            return False

        if _should_prepare_runtime():
            from archivebox.machine.models import Process, Machine

            Process.cleanup_stale_running()
            Process.cleanup_orphaned_workers()
            Machine.current()
