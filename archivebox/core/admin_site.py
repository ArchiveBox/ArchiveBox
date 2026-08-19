__package__ = "archivebox.core"

from typing import TYPE_CHECKING, Any

from admin_data_views.admin import (
    admin_data_index_view as adv_admin_data_index_view,
)
from admin_data_views.admin import (
    get_admin_data_urls as adv_get_admin_data_urls,
)
from admin_data_views.admin import (
    get_app_list as adv_get_app_list,
)
from django.contrib import admin
from django.contrib.auth import REDIRECT_FIELD_NAME, get_user_model, login as auth_login
from django.contrib.auth.decorators import login_not_required
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.views import LoginView
from django.db import DatabaseError, connection, transaction
from django.http import HttpResponseRedirect
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.utils.translation import gettext as _
from django.views.decorators.cache import never_cache

from archivebox.config import VERSION
from archivebox.core.context_processors import get_static_cache_key
from archivebox.core.routes_util import is_allowed_archivebox_redirect_url

if TYPE_CHECKING:
    from admin_data_views.typing import AppDict
    from django.http import HttpRequest
    from django.template.response import TemplateResponse
    from django.urls import URLPattern, URLResolver


class ArchiveBoxLoginView(LoginView):
    def get_redirect_url(self) -> str:
        redirect_to = self.request.POST.get(
            self.redirect_field_name,
            self.request.GET.get(self.redirect_field_name),
        )
        if is_allowed_archivebox_redirect_url(redirect_to, request=self.request):
            return redirect_to
        return ""


class ArchiveBoxAdmin(admin.AdminSite):
    site_header = "ArchiveBox"
    index_title = "Admin Views"
    site_title = "Admin"
    namespace = "admin"

    def each_context(self, request: "HttpRequest") -> dict[str, Any]:
        context = super().each_context(request)
        context["VERSION"] = VERSION
        context["STATIC_CACHE_KEY"] = get_static_cache_key()
        return context

    @staticmethod
    def _format_object_count(count: int) -> tuple[int, str, str]:
        if count >= 1_000_000_000:
            count_label = f"{count / 1_000_000_000:.1f}B"
        elif count >= 1_000_000:
            count_label = f"{count / 1_000_000:.1f}M"
        elif count >= 1_000:
            count_label = f"{count / 1_000:.1f}K"
        else:
            count_label = f"{count:,}"
        count_label = count_label.replace(".0", "")
        return count, count_label, f"Object count: {count:,}"

    def _set_model_object_count(
        self,
        models_by_table: dict[str, list[dict[str, Any]]],
        table: str,
        count: int,
        title: str | None = None,
    ) -> None:
        models = models_by_table.get(table)
        if not models:
            return
        count, count_label, count_title = self._format_object_count(count)
        if title:
            count_title = title
        for model in models:
            model["object_count"] = count
            model["object_count_label"] = count_label
            model["object_count_title"] = count_title

    def get_app_list(self, request: "HttpRequest", app_label: str | None = None) -> list["AppDict"]:
        if app_label is None:
            return adv_get_app_list(self, request)
        return adv_get_app_list(self, request, app_label)

    def admin_data_index_view(self, request: "HttpRequest", **kwargs: Any) -> "TemplateResponse":
        return adv_admin_data_index_view(self, request, **kwargs)

    @method_decorator(never_cache)
    @login_not_required
    def login(self, request: "HttpRequest", extra_context: dict[str, Any] | None = None) -> "TemplateResponse":
        if request.method == "GET" and self.has_permission(request):
            return HttpResponseRedirect(reverse("admin:index", current_app=self.name))

        from django.contrib.admin.forms import AdminAuthenticationForm

        User = get_user_model()
        first_admin_setup = not User.objects.filter(is_superuser=True).exclude(username="system").exists()
        context = {
            **self.each_context(request),
            "title": _("Set up ArchiveBox") if first_admin_setup else _("Log in"),
            "subtitle": None,
            "app_path": request.get_full_path(),
            "username": request.user.get_username(),
            "first_admin_setup": first_admin_setup,
        }
        if REDIRECT_FIELD_NAME not in request.GET and REDIRECT_FIELD_NAME not in request.POST:
            context[REDIRECT_FIELD_NAME] = reverse("admin:index", current_app=self.name)
        context.update(extra_context or {})

        index_path = reverse("admin:index", current_app=self.name)
        request.current_app = self.name
        if first_admin_setup:
            form = UserCreationForm(request.POST or None)
            if request.method == "POST" and form.is_valid():
                with transaction.atomic():
                    # Fresh collections contain the system superuser, which also
                    # provides a row lock while the first real admin is created.
                    list(User.objects.select_for_update().filter(is_superuser=True).values_list("pk", flat=True))
                    if User.objects.filter(is_superuser=True).exclude(username="system").exists():
                        form.add_error(None, _("An admin account was already created. Log in instead."))
                    else:
                        user = form.save(commit=False)
                        user.is_staff = True
                        user.is_superuser = True
                        user.save()
                        auth_login(request, user, backend="django.contrib.auth.backends.ModelBackend")
                        return HttpResponseRedirect(index_path)

            context["form"] = form
            return TemplateResponse(
                request,
                self.login_template or "admin/login.html",
                context,
            )

        return ArchiveBoxLoginView.as_view(
            extra_context=context,
            authentication_form=self.login_form or AdminAuthenticationForm,
            template_name=self.login_template or "admin/login.html",
            next_page=index_path,
        )(request)

    def index(self, request: "HttpRequest", extra_context: dict[str, Any] | None = None) -> "TemplateResponse":
        response = super().index(request, extra_context)

        models_by_table: dict[str, list[dict[str, Any]]] = {}
        for app in response.context_data.get("app_list", []):
            for model in app.get("models", []):
                model_class = model.get("model")
                if not model_class or not model.get("perms", {}).get("view"):
                    continue
                models_by_table.setdefault(model_class._meta.db_table, []).append(model)

        if not models_by_table:
            return response

        from archivebox.misc.db import approximate_row_counts

        for table, count in approximate_row_counts(connection).items():
            if table not in models_by_table:
                continue
            self._set_model_object_count(
                models_by_table,
                table,
                count,
                title=f"Approximate count from database stats: {count:,}",
            )
            models_by_table.pop(table, None)

        for table in list(models_by_table):
            try:
                with connection.cursor() as cursor:
                    cursor.execute(f"SELECT COUNT(*) FROM {connection.ops.quote_name(table)}")
                    count = int(cursor.fetchone()[0])
            except DatabaseError:
                continue
            self._set_model_object_count(models_by_table, table, count)
            models_by_table.pop(table, None)
        return response

    def get_admin_data_urls(self) -> list["URLResolver | URLPattern"]:
        return adv_get_admin_data_urls(self)

    def get_urls(self) -> list["URLResolver | URLPattern"]:
        return self.get_admin_data_urls() + super().get_urls()


archivebox_admin = ArchiveBoxAdmin()
# Note: delete_selected is enabled per-model via actions = ['delete_selected'] in each ModelAdmin
# TODO: https://stackoverflow.com/questions/40760880/add-custom-button-to-django-admin-panel


############### Admin Data View sections are defined in settings.ADMIN_DATA_VIEWS #########


def register_admin_site():
    """Replace the default admin site with our custom ArchiveBox admin site."""
    from django.contrib import admin
    from django.contrib.admin import sites

    admin.site = archivebox_admin
    sites.site = archivebox_admin

    # Register admin views for each app
    # (Previously handled by ABX plugin system, now called directly)
    from archivebox.api.admin import register_admin as register_api_admin
    from archivebox.core.admin import register_admin as register_core_admin
    from archivebox.crawls.admin import register_admin as register_crawls_admin
    from archivebox.machine.admin import register_admin as register_machine_admin
    from archivebox.personas.admin import register_admin as register_personas_admin
    from archivebox.workers.admin import register_admin as register_workers_admin

    register_core_admin(archivebox_admin)
    register_crawls_admin(archivebox_admin)
    register_api_admin(archivebox_admin)
    register_machine_admin(archivebox_admin)
    register_personas_admin(archivebox_admin)
    register_workers_admin(archivebox_admin)

    return archivebox_admin
