import pytest

from archivebox.core.forms import TagField, TagWidget
from archivebox.core.models import Tag


pytestmark = pytest.mark.django_db


def test_tag_field_parses_legacy_tag_input():
    field = TagField()

    assert field.clean("alpha beta alpha") == ["alpha", "beta"]
    assert field.clean("alpha, beta, Alpha") == ["Alpha", "alpha", "beta"]
    assert field.clean('"alpha beta", gamma') == ["alpha beta", "gamma"]
    assert field.clean('"alpha,beta", gamma') == ["alpha,beta", "gamma"]
    assert field.clean('alpha "beta gamma"') == ["alpha", "beta gamma"]
    assert field.clean('"alpha,beta') == ["alpha", "beta"]


def test_tag_widget_formats_real_tag_rows():
    tags = [
        Tag.objects.create(name="plain"),
        Tag.objects.create(name="two words"),
        Tag.objects.create(name="comma,tag"),
    ]

    rendered_value = TagWidget().format_value(tags)

    assert rendered_value == '"comma,tag", "two words", plain'
    assert TagField().clean(rendered_value) == ["comma,tag", "plain", "two words"]
