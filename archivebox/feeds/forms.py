from urllib.parse import urlsplit, urlunsplit

from django import forms
from django.utils import timezone

from archivebox.crawls.schedule_util import next_run_for_schedule, validate_schedule
from .models import SavedFeed


class SubscribeForm(forms.Form):
    name = forms.CharField(max_length=200)
    url = forms.URLField(label="Feed URL or RSSHub server", assume_scheme="https", max_length=4096)
    rsshub_route = forms.CharField(
        required=False,
        label="RSSHub route (optional)",
        help_text="For sites without RSS, enter a route from the RSSHub directory. Leave blank for ordinary RSS or Atom feeds.",
    )
    schedule = forms.CharField(
        initial="daily",
        required=False,
        help_text="hourly, daily, weekly, or a cron expression. Leave blank for manual imports.",
    )
    tags = forms.CharField(required=False, max_length=1024)
    import_tags = forms.BooleanField(
        required=False,
        label="Import feed categories as tags",
        help_text="Keep each article's RSS or Atom categories as snapshot tags.",
    )

    def clean_url(self):
        url = self.cleaned_data["url"]
        if urlsplit(url).scheme not in {"http", "https"}:
            raise forms.ValidationError("Use an HTTP or HTTPS feed.")
        return url

    def clean_rsshub_route(self):
        route = self.cleaned_data["rsshub_route"].strip()
        try:
            parts = urlsplit(route)
        except ValueError as error:
            raise forms.ValidationError("Enter a valid route on your selected RSSHub server.") from error
        if route and (parts.scheme or route.startswith("//") or ".." in parts.path.split("/")):
            raise forms.ValidationError("Enter a route on your selected RSSHub server, not another URL.")
        return route

    def clean_schedule(self):
        value = self.cleaned_data["schedule"].strip()
        try:
            schedule = validate_schedule(value) if value else ""
            self.next_run_at = next_run_for_schedule(schedule, timezone.now()) if schedule else None
            return schedule
        except ValueError as error:
            raise forms.ValidationError(str(error)) from error

    @property
    def feed_url(self):
        url, route = self.cleaned_data["url"], self.cleaned_data["rsshub_route"]
        if not route:
            return url
        server, route_parts = urlsplit(url), urlsplit(route)
        path = server.path.rstrip("/") + "/" + route_parts.path.lstrip("/")
        query = "&".join(part for part in (server.query, route_parts.query) if part)
        return urlunsplit((server.scheme, server.netloc, path, query, ""))


class ExportForm(forms.ModelForm):
    class Meta:
        model = SavedFeed
        fields = ("name", "include_private")
        labels = {"include_private": "Include private and unlisted snapshots"}
        help_texts = {"include_private": "Anyone with the feed link can read its items. You can revoke the link at any time."}
