__package__ = 'archivebox.workers'

import abx

from django.contrib.auth import get_permission_codename

from huey_monitor.apps import HueyMonitorConfig
from huey_monitor.admin import TaskModel, TaskModelAdmin, SignalInfoModel, SignalInfoModelAdmin


HueyMonitorConfig.verbose_name = 'Background Workers'


class CustomTaskModelAdmin(TaskModelAdmin):
    actions = ["delete_selected"]

    def has_delete_permission(self, request, obj=None):
        codename = get_permission_codename("delete", self.opts)
        return request.user.has_perm("%s.%s" % (self.opts.app_label, codename))



@abx.hookimpl
def register_admin(admin_site):
    admin_site.register(TaskModel, CustomTaskModelAdmin)
    admin_site.register(SignalInfoModel, SignalInfoModelAdmin)
