import pytest
from django.template.loader import render_to_string
from lxml import html

from archivebox.core.models import Folder


@pytest.mark.django_db
@pytest.mark.parametrize("readonly", [False, True])
def test_folder_tree_renders_final_emoji_icons_without_javascript(readonly, rf):
    parent = Folder.objects.create(name="👩🏽‍💻 OneTab")
    children = [
        Folder.objects.create(parent=parent, name=name)
        for name in ("🇺🇸 2026", "1️⃣ 2025", "📚 Projects & notes", "Plain 🧭 folder", "123 Reports", "🧭")
    ]
    rendered = render_to_string("core/folder_tree.html", {"folder_tree": Folder.tree(), "folder_readonly": readonly}, request=rf.get("/"))
    assert "Projects &amp; notes" in rendered
    tree = html.fragment_fromstring(rendered, create_parent=True)

    def row(folder):
        return tree.xpath(f'.//div[@data-folder-id="{folder.pk}"]')[0]

    parent_row = row(parent)
    assert parent_row.xpath("./a/span[@aria-hidden='true']/text()") == ["👩🏽‍💻"]
    assert parent_row.xpath("./a/span[last()]/text()") == ["OneTab"]
    assert parent_row.xpath("./a/@aria-label") == [parent.name]
    assert not parent_row.xpath("./a/*[local-name()='svg']")
    assert parent_row.xpath("./a/following-sibling::button[1]/@aria-expanded") == ["true"]

    for folder, emoji, label in zip(
        children,
        ("🇺🇸", "1️⃣", "📚", "", "", "🧭"),
        ("2026", "2025", "Projects & notes", "Plain 🧭 folder", "123 Reports", ""),
        strict=True,
    ):
        link = row(folder).xpath("./a")[0]
        assert link.xpath("./span[last()]")[0].text_content() == label
        assert link.xpath("./span[@aria-hidden='true']/text()") == ([emoji] if emoji else [])
        assert bool(link.xpath("./*[local-name()='svg']")) == (not emoji)
        assert link.get("aria-label") == (folder.name if emoji else None)
        assert row(folder).get("data-folder-name") == folder.name
