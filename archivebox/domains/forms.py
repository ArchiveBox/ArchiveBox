import ipaddress
import re
from urllib.parse import urlsplit, urlunsplit

from django import forms
from django.db import transaction
from django.utils import timezone

from archivebox.config.common import get_config
from archivebox.core.permissions import PERMISSIONS_CHOICES
from archivebox.core.widgets import TagEditorWidget, URLFiltersWidget
from archivebox.crawls.models import Crawl, CrawlSchedule
from archivebox.crawls.schedule_util import next_run_for_schedule, validate_schedule
from archivebox.personas.models import Persona


class DomainCrawlForm(forms.Form):
    url = forms.URLField(
        label="Start URL",
        max_length=4096,
        assume_scheme="https",
        help_text="Start at the homepage or a section. Only links within this host are followed.",
    )
    include_subdomains = forms.BooleanField(required=False, label="Include subdomains of this host")
    max_depth = forms.IntegerField(
        label="Link depth",
        min_value=1,
        max_value=4,
        initial=3,
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
        widget=forms.TextInput(attrs={"placeholder": "One-time"}),
        help_text="Repeat hourly, daily, weekly, or use a cron expression. Each run keeps these domain and capture limits.",
    )
    persona = forms.ModelChoiceField(
        queryset=Persona.objects.none(),
        required=False,
        help_text="Use a saved browser identity for sites that require sign-in.",
    )
    url_filters = forms.Field(
        label="URL filters",
        required=False,
        initial={"same_domain_only": True, "subpaths_only": False, "only_new": True},
        widget=URLFiltersWidget(source_selector='input[name="url"]', auto_update_allowlist=False, collapse_patterns=True),
    )
    tags = forms.CharField(label="Tags", strip=True, required=False, widget=TagEditorWidget())
    permissions = forms.ChoiceField(choices=PERMISSIONS_CHOICES, initial="private", label="Visibility")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["persona"].queryset = Persona.objects.order_by("name")

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
        authority = f"{host}:{parts.port}" if parts.port is not None else host
        return urlunsplit((parts.scheme.lower(), authority, parts.path or "/", parts.query, ""))

    def clean_url_filters(self):
        value = self.cleaned_data.get("url_filters") or {}
        for key in ("allowlist", "denylist"):
            patterns = Crawl.split_filter_patterns(value.get(key, ""))
            for pattern in patterns:
                if not re.fullmatch(r"[\w.*:-]+", pattern):
                    try:
                        re.compile(pattern)
                    except re.error as error:
                        raise forms.ValidationError(f"Invalid {key} pattern: {error}") from error
            value[key] = "\n".join(patterns)
        return value

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
        filters = data["url_filters"]
        host = re.escape(parts.hostname)
        if ":" in parts.hostname:
            host = rf"\[{host}\]"
        elif data["include_subdomains"]:
            host = rf"(?:[a-zA-Z0-9-]+\.)*{host}"
        port = f":{re.escape(str(parts.port))}" if parts.port is not None else r"(?::(?:80|443))?"
        authority = rf"^(?i:https?://{host}{port})"
        boundary = authority + r"(?:/|[?#]|$)"
        if filters.get("subpaths_only") and parts.path.rstrip("/"):
            boundary = authority + re.escape(parts.path.rstrip("/")) + r"(?:/|[?#]|$)"
        persona = data.get("persona") or Persona.objects.filter(name="Default").first()
        effective = get_config(persona=persona) if persona else get_config()
        sitemap = urlunsplit(("https", parts.netloc, "/sitemap.xml", "", ""))
        # Native /add/ semantics: explicit patterns replace the generated host/path
        # defaults; do not silently constrain them with a synthetic deny rule.
        allowlist = filters["allowlist"] or effective.URL_ALLOWLIST or f"{boundary}\n^{re.escape(sitemap)}$"
        denylist = Crawl.split_filter_patterns(effective.URL_DENYLIST)
        denylist.extend(Crawl.split_filter_patterns(filters["denylist"]))
        clone_config = {
            "URL_ALLOWLIST": allowlist,
            # Preserve native per-pattern matching and inline regex flags.
            "URL_DENYLIST": "\n".join(denylist),
            "CRAWL_MAX_URLS": int(data["max_urls"]),
            "CRAWL_MAX_CONCURRENT_SNAPSHOTS": int(data["concurrency"]),
            "CRAWL_TIMEOUT": int(data["timeout_minutes"]) * 60,
            "ONLY_NEW": filters.get("only_new") is True,
            "PERMISSIONS": next(value for value, _label in PERMISSIONS_CHOICES if value == data["permissions"]),
        }
        with transaction.atomic():
            crawl = Crawl.objects.create(
                urls="\n".join(dict.fromkeys([data["url"], sitemap])),
                label=parts.hostname[:64],
                created_by=user,
                persona=persona,
                max_depth=data["max_depth"],
                tags_str=",".join(Crawl.parse_tag_names([*Crawl.parse_tag_names(data["tags"]), "site-clone"])),
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
            return crawl
