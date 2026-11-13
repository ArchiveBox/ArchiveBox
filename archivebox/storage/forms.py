import json
import os
from pathlib import Path

from django import forms

from archivebox.config.constants import CONSTANTS


class DestinationForm(forms.Form):
    provider = forms.ChoiceField(
        choices=[("drive", "Google Drive"), ("s3", "Amazon S3 / compatible storage"), ("local", "Local directory / mounted drive")],
    )
    path = forms.CharField(
        max_length=2048,
        help_text="S3: bucket/prefix. Google Drive: folder below the selected root. Local: absolute path outside this collection.",
    )
    s3_provider = forms.ChoiceField(
        choices=[("AWS", "Amazon S3"), ("Cloudflare", "Cloudflare R2"), ("Minio", "MinIO"), ("Other", "Other S3 compatible")],
        required=False,
    )
    region = forms.CharField(required=False, initial="us-east-1")
    endpoint = forms.URLField(
        required=False,
        help_text="Required for S3 compatible providers. Example: https://your-account.r2.cloudflarestorage.com",
    )
    access_key_id = forms.CharField(required=False)
    secret_access_key = forms.CharField(required=False, widget=forms.PasswordInput(render_value=False))
    drive_auth = forms.ChoiceField(choices=[("oauth", "Sign in with Google"), ("service_account", "Service account")], required=False)
    client_id = forms.CharField(required=False, label="Google OAuth client ID")
    client_secret = forms.CharField(required=False, label="Google OAuth client secret", widget=forms.PasswordInput(render_value=False))
    service_account = forms.CharField(
        required=False,
        label="Service account JSON",
        widget=forms.Textarea(attrs={"rows": 4}),
        help_text="Share the destination Drive folder with the service account email.",
    )
    root_folder_id = forms.CharField(
        required=False,
        label="Google Drive folder ID",
        help_text="The part after /folders/ in the Google Drive folder URL.",
    )

    def __init__(self, *args, **kwargs):
        self.existing = kwargs.pop("existing", {})
        super().__init__(*args, **kwargs)
        self.fields["service_account"].widget = forms.PasswordInput(render_value=False, attrs={"autocomplete": "off"})
        self.initial.update(
            {key: self.existing.get(key, "") for key in ("region", "endpoint", "access_key_id", "client_id", "root_folder_id")},
        )
        self.initial["s3_provider"] = self.existing.get("provider", "AWS")
        self.initial["drive_auth"] = "service_account" if self.existing.get("service_account_credentials") else "oauth"

    def clean(self):
        data = super().clean()
        existing = self.existing if self.existing.get("type") == data.get("provider") else {}
        provider = data.get("provider")
        path = data.get("path", "").strip()
        if any(char in path for char in ("\n", "\r", "\x00")):
            self.add_error("path", "Enter a single destination path.")
        if provider == "local":
            if not os.path.isabs(path):
                self.add_error("path", "Choose an absolute directory outside the collection and its parent directories.")
            elif "path" not in self.errors:
                # Resolve symlinks before checking the collection boundary, and
                # persist that same destination rather than an unchecked alias.
                local = Path(os.path.realpath(path))
                collection = CONSTANTS.DATA_DIR.resolve()
                if local.is_relative_to(collection) or collection.is_relative_to(local):
                    self.add_error("path", "Choose an absolute directory outside the collection and its parent directories.")
                else:
                    data["path"] = str(local)
        elif path.startswith("/") or ":" in path or ".." in Path(path).parts:
            self.add_error("path", "Use a folder or bucket/prefix without a remote name, leading slash, or parent traversal.")
        if provider == "s3":
            if not data.get("s3_provider"):
                self.add_error("s3_provider", "Choose your S3 provider.")
            if data.get("s3_provider") != "AWS" and not data.get("endpoint"):
                self.add_error("endpoint", "Enter this provider's HTTPS endpoint.")
            if data.get("endpoint") and not data["endpoint"].startswith("https://"):
                self.add_error("endpoint", "Use an HTTPS endpoint.")
            for key in ("access_key_id", "secret_access_key"):
                if not data.get(key) and not existing.get(key):
                    self.add_error(key, "This credential is required.")
        if provider == "drive":
            if data.get("drive_auth") == "service_account":
                raw = data.get("service_account")
                if raw:
                    try:
                        account = json.loads(raw)
                        if (
                            not isinstance(account, dict)
                            or account.get("type") != "service_account"
                            or not account.get("client_email")
                            or not account.get("private_key")
                        ):
                            raise ValueError
                    except (ValueError, TypeError):
                        self.add_error("service_account", "Paste a valid Google service-account JSON key.")
                elif not existing.get("service_account_credentials"):
                    self.add_error("service_account", "A service-account key is required.")
            else:
                for key in ("client_id", "client_secret"):
                    if not data.get(key) and not existing.get(key):
                        self.add_error(key, "Create a Google web OAuth client and enter its credential.")
        return data

    def remote_options(self, existing=None):
        data = self.cleaned_data
        options = dict(existing or {})
        options["type"] = data["provider"]
        if data["provider"] == "s3":
            options.update(provider=data["s3_provider"], region=data["region"], endpoint=data["endpoint"], env_auth="false")
            for key in ("access_key_id", "secret_access_key"):
                if data[key]:
                    options[key] = data[key]
        if data["provider"] == "drive":
            options.update(scope="drive", root_folder_id=data["root_folder_id"])
            if data.get("drive_auth") == "service_account":
                if data["service_account"]:
                    options["service_account_credentials"] = json.dumps(json.loads(data["service_account"]), separators=(",", ":"))
                for key in ("token", "client_id", "client_secret"):
                    options.pop(key, None)
            else:
                options.pop("service_account_credentials", None)
                for key in ("client_id", "client_secret"):
                    if data[key]:
                        options[key] = data[key]
        return options
