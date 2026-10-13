"""Plugin templates select only their needed stored result manifests."""

import pytest
from django.db import connection
from django.db.models import prefetch_related_objects
from django.template import Context, Template
from django.test.utils import CaptureQueriesContext
from django.utils.html import escapejs

from archivebox.core.models import ArchiveResult

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("prefetched", [False, True])
def test_snapshot_results_reuses_selected_manifests_across_template_loops(snapshot, prefetched):
    for plugin in ("responses", "liteparse", "git", "wget", "archivewebpage", "singlefile"):
        ArchiveResult.objects.create(
            snapshot=snapshot,
            plugin=plugin,
            output_files={f"{plugin}/asset-{index}.html": {"size": index, "mimetype": "text/html"} for index in range(128)},
        )
    if prefetched:
        prefetch_related_objects([snapshot], "archiveresult_set")
    card = Template(
        "{% load core_tags %}"
        "{% snapshot_results snapshot 'responses, liteparse' as captures %}"
        "{% for capture in captures %}{{ capture.plugin }}:{{ capture.output_files|length }};{% endfor %}"
        "|{% for capture in captures %}{{ capture.plugin }};{% endfor %}",
    )
    with CaptureQueriesContext(connection) as queries:
        rendered = card.render(Context({"snapshot": snapshot}))
    first, second = rendered.split("|")
    assert set(first.strip(";").split(";")) == {"responses:128", "liteparse:128"}
    assert set(second.strip(";").split(";")) == {"responses", "liteparse"}
    assert len(queries) == (0 if prefetched else 1), [query["sql"] for query in queries]
    if not prefetched:
        selected_columns = queries[0]["sql"].split(" FROM ")[0]
        assert '"output_files"' in selected_columns
        assert '"output_str"' not in selected_columns
        assert '"config"' not in selected_columns
        assert '"status"' not in selected_columns
        ArchiveResult.objects.filter(snapshot=snapshot, plugin="responses").update(output_files={})
        assert "responses:0;" in card.render(Context({"snapshot": snapshot}))


def test_snapshot_results_empty_selection_does_not_load_unrelated_results(snapshot):
    ArchiveResult.objects.create(snapshot=snapshot, plugin="responses", output_files={"all/example.png": {"size": 12}})
    card = Template("{% load core_tags %}{% snapshot_results snapshot '' as captures %}{{ captures|length }}")
    with CaptureQueriesContext(connection) as queries:
        rendered = card.render(Context({"snapshot": snapshot}))
    assert rendered == "0"
    assert len(queries) == 0


@pytest.mark.parametrize("plugin", ["responses", "liteparse", "git"])
def test_plugin_cards_query_only_their_source_manifests(snapshot, plugin):
    from archivebox.core.templatetags.core_tags import render_plugin_card_document

    results = {}
    for name in ("responses", "staticfile", "wget", "liteparse", "papersdl", "git", "dom", "singlefile", "archivewebpage"):
        results[name] = ArchiveResult.objects.create(
            snapshot=snapshot,
            plugin=name,
            status="succeeded",
            output_str="index.html",
            output_files={
                f"{name}/asset-{index}.html": {"size": index, "mimetype": "text/html", "root_relative": True} for index in range(128)
            },
        )
    with CaptureQueriesContext(connection) as queries:
        rendered = render_plugin_card_document(Context({}), results[plugin])
    manifest_queries = [query["sql"] for query in queries if '"core_archiveresult"' in query["sql"] and '"output_files"' in query["sql"]]
    assert len(manifest_queries) == 1, manifest_queries
    assert '"plugin" IN (' in manifest_queries[0]
    columns = manifest_queries[0].split(" FROM ")[0]
    assert '"output_str"' not in columns
    assert escapejs("archivewebpage/asset-") not in rendered
    assert escapejs("wget/asset-127.html") in rendered
