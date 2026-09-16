"""Crawl form input parsing; lifecycle operations remain on Crawl."""

import json
from copy import copy
from typing import ClassVar
from urllib.parse import urlparse

from django import forms

from archivebox.core.widgets import TagEditorWidget, URLFiltersWidget
from archivebox.crawls.models import Crawl


class URLFiltersField(forms.Field):
    widget = URLFiltersWidget(source_selector="#id_urls")

    def to_python(self, value):
        value = value if isinstance(value, dict) else {}
        return {
            "allowlist": "\n".join(Crawl.split_filter_patterns(value.get("allowlist", ""))),
            "denylist": "\n".join(Crawl.split_filter_patterns(value.get("denylist", ""))),
            "same_domain_only": bool(value.get("same_domain_only")),
            "subpaths_only": bool(value.get("subpaths_only")),
            "only_new": bool(value.get("only_new")),
        }


class CrawlAdminForm(forms.ModelForm):
    """Custom form for Crawl admin to render urls field as textarea."""

    tags_editor = forms.CharField(
        label="Tags",
        required=False,
        widget=TagEditorWidget(),
        help_text="Type tag names and press Enter or Space to add. Click × to remove.",
    )
    url_filters = URLFiltersField(
        label="URL Filters",
        required=False,
        help_text="Set URL_ALLOWLIST / URL_DENYLIST for this crawl.",
    )

    class Meta:
        model = Crawl
        fields = "__all__"
        widgets: ClassVar[dict[str, forms.Widget]] = {
            "urls": forms.Textarea(
                attrs={
                    "rows": 8,
                    "style": "width: 100%; font-family: monospace; font-size: 13px;",
                    "placeholder": "https://example.com\nhttps://example2.com\n# Comments start with #",
                },
            ),
            "notes": forms.Textarea(
                attrs={
                    "rows": 1,
                    "style": "width: 100%; min-height: 0; resize: vertical;",
                },
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        config = dict(self.instance.config or {}) if self.instance and self.instance.pk else {}
        if self.instance and self.instance.pk:
            self.initial["tags_editor"] = self.instance.tags_str
        effective_only_new = self.effective_only_new(self.instance if self.instance and self.instance.pk else None)
        derived_filter_toggles = self.derive_filter_toggles(
            self.instance.urls if self.instance and self.instance.pk else "",
            config.get("URL_ALLOWLIST", ""),
        )
        self.initial["url_filters"] = {
            "allowlist": config.get("URL_ALLOWLIST", ""),
            "denylist": config.get("URL_DENYLIST", ""),
            "same_domain_only": derived_filter_toggles["same_domain_only"],
            "subpaths_only": derived_filter_toggles["subpaths_only"],
            "only_new": effective_only_new,
        }

    @staticmethod
    def extract_url_line(line):
        line = str(line or "").strip()
        if not line or line.startswith("#"):
            return ""
        if line.startswith("{"):
            try:
                return str(json.loads(line).get("url", "")).strip()
            except (TypeError, ValueError, json.JSONDecodeError):
                return ""
        return line

    @staticmethod
    def regex_escape(text):
        escaped = ""
        for char in str(text or ""):
            escaped += f"\\{char}" if char in r".*+?^${}()|[]\\" else char
        return escaped

    @classmethod
    def generated_host_allowlist(cls, urls):
        seen = set()
        domains = []
        for raw_line in str(urls or "").splitlines():
            url = cls.extract_url_line(raw_line)
            if not url:
                continue
            parsed = urlparse(url)
            domain = (parsed.hostname or "").lower()
            if not domain or domain in seen:
                continue
            seen.add(domain)
            domains.append(domain)
        if not domains:
            return ""
        return "^https?://(" + "|".join(cls.regex_escape(domain) for domain in domains) + ")([:/]|$)"

    @staticmethod
    def subpath_prefix(pathname):
        path = str(pathname or "/")
        while "//" in path:
            path = path.replace("//", "/")
        if not path or path == "/":
            return "/"
        if path.endswith("/"):
            return path
        last_slash = path.rfind("/")
        last_part = path[last_slash + 1 :]
        if "." in last_part:
            return path[: last_slash + 1] or "/"
        return path

    @staticmethod
    def parsed_host_and_port(parsed):
        host = (parsed.hostname or "").lower()
        if not host:
            return ""
        try:
            port = parsed.port
        except ValueError:
            port = None
        return f"{host}:{port}" if port is not None else host

    @classmethod
    def generated_subpath_allowlist(cls, urls):
        seen = set()
        paths = []
        for raw_line in str(urls or "").splitlines():
            url = cls.extract_url_line(raw_line)
            if not url:
                continue
            parsed = urlparse(url)
            domain = (parsed.hostname or "").lower()
            if domain:
                seen.add(domain)
            host = cls.parsed_host_and_port(parsed)
            path = cls.subpath_prefix(parsed.path)
            path_key = f"{host}{path}"
            if not host or path_key in seen:
                continue
            seen.add(path_key)
            paths.append((host, path))
        if not paths:
            return ""
        patterns = []
        for host, path in paths:
            if path == "/":
                patterns.append(f"^https?://{cls.regex_escape(host)}([/?#]|$)")
            elif path.endswith("/"):
                patterns.append(f"^https?://{cls.regex_escape(host)}{cls.regex_escape(path)}")
            else:
                patterns.append(f"^https?://{cls.regex_escape(host)}{cls.regex_escape(path)}([/?#]|$)")
        return "\n".join(patterns)

    @classmethod
    def derive_filter_toggles(cls, urls, allowlist):
        normalized_allowlist = "\n".join(Crawl.split_filter_patterns(allowlist))
        if not normalized_allowlist:
            return {"same_domain_only": False, "subpaths_only": False}
        if normalized_allowlist == cls.generated_subpath_allowlist(urls):
            return {"same_domain_only": True, "subpaths_only": True}
        if normalized_allowlist == cls.generated_host_allowlist(urls):
            return {"same_domain_only": True, "subpaths_only": False}
        return {"same_domain_only": False, "subpaths_only": False}

    @staticmethod
    def effective_only_new(crawl=None):
        from archivebox.config.common import get_config

        if crawl is not None:
            return bool(get_config(crawl=crawl, resolve_plugins=False).ONLY_NEW)
        return bool(get_config(resolve_plugins=False).ONLY_NEW)

    @staticmethod
    def inherited_only_new(crawl):
        crawl_without_only_new = copy(crawl)
        config = dict(crawl.config or {})
        config.pop("ONLY_NEW", None)
        crawl_without_only_new.config = config
        return CrawlAdminForm.effective_only_new(crawl_without_only_new)

    def clean_tags_editor(self):
        tags_str = self.cleaned_data.get("tags_editor", "")
        tag_names = []
        seen = set()
        for raw_name in tags_str.split(","):
            name = raw_name.strip()
            if not name:
                continue
            lowered = name.lower()
            if lowered in seen:
                continue
            seen.add(lowered)
            tag_names.append(name)
        return ",".join(tag_names)

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.tags_str = self.cleaned_data.get("tags_editor", "")
        if f"{self.add_prefix('url_filters')}_allowlist" in self.data or f"{self.add_prefix('url_filters')}_denylist" in self.data:
            url_filters = self.cleaned_data.get("url_filters") or {}
            instance.set_url_filters(
                url_filters.get("allowlist", ""),
                url_filters.get("denylist", ""),
            )
            config = dict(instance.config or {})
            only_new = bool(url_filters.get("only_new"))
            inherited_only_new = self.inherited_only_new(instance)
            if only_new != inherited_only_new:
                config["ONLY_NEW"] = only_new
            else:
                config.pop("ONLY_NEW", None)
            instance.config = config
        if commit:
            instance.save()
            instance.apply_crawl_config_filters()
            self._save_m2m()
        return instance
