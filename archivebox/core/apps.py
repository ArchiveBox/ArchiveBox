__package__ = "archivebox.core"

from django.apps import AppConfig
import os


class CoreConfig(AppConfig):
    name = "archivebox.core"
    label = "core"

    def ready(self):
        """Register the archivebox.core.admin_site as the main django admin site"""
        from django.utils.autoreload import DJANGO_AUTORELOAD_ENV

        from archivebox.core.admin_site import register_admin_site

        register_admin_site()
        from archivebox.base_models.models import ModelWithOutputDir

        ModelWithOutputDir.register_delete_signal()

        # SQLite ignores VARCHAR(n) limits but PostgreSQL enforces them; clamp
        # CharField values on save so writes behave the same on both backends.
        from django.db.models.signals import pre_save

        from archivebox.misc.db import truncate_overlong_charfields

        pre_save.connect(truncate_overlong_charfields, dispatch_uid="archivebox_truncate_overlong_charfields")

        def _should_prepare_runtime() -> bool:
            if os.environ.get("ARCHIVEBOX_RUNSERVER") == "1":
                if os.environ.get("ARCHIVEBOX_AUTORELOAD") == "1":
                    return os.environ.get(DJANGO_AUTORELOAD_ENV) == "true"
                return True
            return False

        if _should_prepare_runtime():
            from archivebox.config import CONSTANTS
            from archivebox.machine.models import Process

            Process.current().mark_running(
                process_type=Process.TypeChoices.WORKER,
                worker_type="worker_runserver",
                pwd=str(CONSTANTS.DATA_DIR),
                url=os.environ.get("ARCHIVEBOX_RUNSERVER_BIND_URL") or "",
                timeout=CONSTANTS.MAX_HOOK_RUNTIME_SECONDS,
            )
