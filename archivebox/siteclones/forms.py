import ipaddress
import re
from urllib.parse import urlsplit, urlunsplit

from django import forms
from django.db import transaction
from django.utils import timezone

from archivebox.config.common import get_config
from archivebox.core.permissions import PERMISSIONS_CHOICES
from archivebox.crawls.models import Crawl, CrawlSchedule
from archivebox.crawls.schedule_util import next_run_for_schedule, validate_schedule
from archivebox.personas.models import Persona
from archivebox.plugins.forms import get_plugin_choices

from .models import SiteClone


class SiteCloneForm(forms.Form):
    url = forms.URLField(
        label="Start URL",
        max_length=4096,
        assume_scheme="https",
        help_text="Start at the homepage or a section. Only links within this host are followed.",
    )
    name = forms.CharField(label="Name", max_length=64, required=False)
    include_subdomains = forms.BooleanField(required=False, label="Include subdomains of this host")
    max_depth = forms.IntegerField(
        label="Link depth",
        min_value=1,
        max_value=4,
        initial=2,
        help_text="Follow links up to 1–4 hops from the start URL.",
    )
    max_urls = forms.IntegerField(
        label="Maximum pages",
        min_value=1,
        max_value=1000000,
        initial=100,
        help_text="Stop adding new pages at this budget. Adjust the limit from Crawl settings.",
    )
    concurrency = forms.IntegerField(label="Pages at a time", min_value=1, max_value=64, initial=2)
    timeout_minutes = forms.IntegerField(label="Time budget (minutes)", min_value=1, max_value=10080, initial=60)
    schedule = forms.CharField(
        required=False,
        max_length=64,
        label="Repeat (optional)",
        widget=forms.TextInput(attrs={"placeholder": "One-time clone (leave blank)"}),
        help_text="Repeat hourly, daily, weekly, or use a cron expression. Each run keeps these domain and capture limits.",
    )
    exclude_paths = forms.CharField(
        label="Exclude paths",
        required=False,
        widget=forms.Textarea(attrs={"rows": 4, "placeholder": "/login\n/logout\n/cart"}),
        help_text="One path prefix per line. Matching paths and their children are excluded.",
    )
    persona = forms.ModelChoiceField(
        queryset=Persona.objects.none(),
        required=False,
        help_text="Use a saved browser identity for sites that require sign-in.",
    )
    only_new = forms.BooleanField(required=False, initial=True, label="Skip URLs already saved")
    tags = forms.CharField(required=False, max_length=1024, help_text="Comma-separated tags applied to captured pages.")
    permissions = forms.ChoiceField(choices=PERMISSIONS_CHOICES, initial="private", label="Visibility")
    plugins = forms.MultipleChoiceField(
        required=False,
        label="Capture plugins",
        help_text="Leave empty to use your configured plugins. A custom selection must include a link-discovery plugin to follow pages.",
        widget=forms.SelectMultiple(attrs={"size": 6}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["persona"].queryset = Persona.objects.order_by("name")
        self.fields["plugins"].choices = get_plugin_choices()

    def clean_url(self):
        value = self.cleaned_data["url"]
        parts = urlsplit(value)
        if parts.scheme not in {"http", "https"} or not parts.hostname:
            raise forms.ValidationError("Enter an HTTP or HTTPS website URL.")
        if parts.username is not None or parts.password is not None:
            raise forms.ValidationError("Use a Persona for authentication instead of credentials in the URL.")
        host = parts.hostname.encode("idna").decode("ascii").lower()
        if ":" in host:
            host = f"[{host}]"
        authority = f"{host}:{parts.port}" if parts.port else host
        return urlunsplit((parts.scheme.lower(), authority, parts.path or "/", parts.query, ""))

    def clean_exclude_paths(self):
        paths = []
        for path in self.cleaned_data["exclude_paths"].splitlines():
            path = path.strip()
            if not path:
                continue
            if not path.startswith("/") or path.startswith("//") or path == "/" or "?" in path or "#" in path:
                raise forms.ValidationError("Enter path prefixes such as /login or /account, not URLs, queries, or the whole site (/).")
            paths.append(path.rstrip("/"))
        return list(dict.fromkeys(paths))

    def clean_schedule(self):
        value = self.cleaned_data["schedule"].strip()
        if not value:
            return ""
        try:
            value = validate_schedule(value)
            next_run_for_schedule(value, timezone.now())
        except ValueError as error:
            raise forms.ValidationError(str(error)) from error
        return value

    def clean(self):
        data = super().clean()
        if data.get("url") and data.get("include_subdomains"):
            try:
                ipaddress.ip_address(urlsplit(data["url"]).hostname)
            except ValueError:
                pass
            else:
                self.add_error("include_subdomains", "IP addresses do not have subdomains.")
        return data

    def save(self, user):
        data = self.cleaned_data
        parts = urlsplit(data["url"])
        # Anchored authority boundaries prevent host-prefix matches (example.com.evil)
        # and userinfo tricks; an explicit source port stays scoped to that port.
        host = re.escape(parts.hostname)
        if ":" in parts.hostname:
            host = rf"\[{host}\]"
        elif data["include_subdomains"]:
            host = rf"(?:[a-zA-Z0-9-]+\.)*{host}"
        port = f":{parts.port}" if parts.port else r"(?::(?:80|443))?"
        authority = rf"^(?i:https?://{host}{port})"
        allowlist = authority + r"(?:/|\?|$)"
        persona = data.get("persona") or Persona.objects.filter(name="Default").first()
        effective = get_config(persona=persona) if persona else get_config()
        denylist = [effective.URL_DENYLIST] if effective.URL_DENYLIST else []
        denylist.extend(authority + re.escape(path) + r"(?:/|\?|$)" for path in data["exclude_paths"])
        clone_config = {
            "URL_ALLOWLIST": allowlist,
            # Keep inherited leading global regex flags at the start.
            "URL_DENYLIST": "|".join(denylist),
            "CRAWL_MAX_URLS": data["max_urls"],
            "CRAWL_MAX_CONCURRENT_SNAPSHOTS": data["concurrency"],
            "CRAWL_TIMEOUT": data["timeout_minutes"] * 60,
            "ONLY_NEW": data["only_new"],
            "PERMISSIONS": data["permissions"],
            **({"PLUGINS": ",".join(data["plugins"])} if data["plugins"] else {}),
        }
        with transaction.atomic():
            crawl = Crawl.objects.create(
                urls=data["url"],
                label=data["name"] or parts.hostname[:64],
                created_by=user,
                persona=persona,
                max_depth=data["max_depth"],
                tags_str=data["tags"],
                config=dict(clone_config),
            )
            if data["schedule"]:
                CrawlSchedule.objects.create(
                    template=crawl,
                    schedule=data["schedule"],
                    config=clone_config,
                    label=crawl.label,
                    created_by=user,
                )
            return SiteClone.objects.create(crawl=crawl)
