"""Native destination pickers retain distinct ancestor paths and validation."""

import pytest
from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory

pytestmark = pytest.mark.django_db


def test_native_folder_picker_paths_and_destination_filters(admin_user):
    from archivebox.core.models import Folder
    from archivebox.core.forms import AddLinkForm
    from archivebox.crawls.admin import CrawlAdminForm
    from archivebox.importers.catalog import get_importer
    from archivebox.importers.forms import ImporterSourceForm
    from archivebox.api.webhook_views import editor_data

    first = Folder.objects.create(name="Research", position=0)
    second = Folder.objects.create(name="Work", position=1)
    child = Folder.objects.create(name="Papers", parent=first)
    other = Folder.objects.create(name="Papers", parent=second)
    smart = Folder.objects.create(name="Smart", rules={"field": "url", "lookup": "icontains", "value": "news"})
    expected = {child.pk: "Research / Papers", other.pk: "Work / Papers"}
    request = RequestFactory().get("/add/")
    request.user = admin_user
    add = AddLinkForm(request=request)
    crawl = CrawlAdminForm()
    importer = ImporterSourceForm(definition=get_importer("importer_rss", "feed"))
    for form in (add, crawl, importer):
        choices = list(form.fields["folder"].choices)
        labels = dict(choices)
        for pk, label in expected.items():
            assert labels[pk] == label
        assert choices[0][0] == ""
        assert form.fields["folder"].clean(str(child.pk)).pk == child.pk
    assert list(add.fields["folder"].choices)[0] == ("", "No folder")
    assert list(crawl.fields["folder"].choices)[0] == ("", "No folder")
    assert smart.pk not in dict(add.fields["folder"].choices)
    assert smart.pk not in dict(crawl.fields["folder"].choices)
    assert smart.pk in dict(importer.fields["folder"].choices)
    importer.cleaned_data = {"folder": smart}
    from django.core.exceptions import ValidationError

    with pytest.raises(ValidationError, match="regular folder"):
        importer.clean_folder()
    schema = {row["id"]: row["name"] for row in editor_data()["folders"]}
    assert all(schema[str(pk)] == label for pk, label in expected.items())
    request.user = AnonymousUser()
    assert "folder" not in AddLinkForm(request=request).fields
