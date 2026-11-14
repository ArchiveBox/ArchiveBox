from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.views.decorators.http import require_http_methods

from archivebox.config.collection import ConfigMirrorError
from archivebox.config.forms import MachineSettingsForm
from archivebox.core.admin_site import archivebox_admin
from archivebox.machine.models import Machine


@require_http_methods(["GET", "POST"])
def system_settings(request):
    if not request.user.is_active or not request.user.is_superuser:
        raise PermissionDenied
    machine = Machine.current_readonly() or Machine.current()
    form = MachineSettingsForm(request.POST if request.method == "POST" else None, machine=machine)
    if request.method == "POST" and form.is_valid():
        machine.config = form.cleaned_data["config"]
        try:
            machine.save(update_fields=["config", "modified_at"], strict_config_mirror=True)
        except ConfigMirrorError:
            form.add_error(
                None,
                "Settings saved to the database, but ArchiveBox.conf could not be updated. Check the file permissions and save again.",
            )
        else:
            messages.success(request, "Saved.")
            return redirect("system-settings")
    return TemplateResponse(
        request,
        "admin/system_settings.html",
        {
            **archivebox_admin.each_context(request),
            "title": "System settings",
            "form": form,
            "machine": machine,
            "media": form.media,
        },
    )
