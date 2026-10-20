"""Real filesystem boundaries for scheduled artifact deletion."""

import pytest

from archivebox.base_models.models import ModelWithOutputDir


def test_delete_unlinks_cyclic_final_symlink_without_resolving_it(tmp_path):
    path = tmp_path / "loop"
    path.symlink_to(path.name)

    ModelWithOutputDir.delete_output_paths([path])

    assert not path.is_symlink()
    assert not path.exists()


def test_delete_rejects_intermediate_symlink_escape(tmp_path, tmp_path_factory):
    outside = tmp_path_factory.mktemp("outside-deletion-root")
    sentinel = outside / "saved.txt"
    sentinel.write_bytes(b"must remain outside the collection")
    alias = tmp_path / "outside"
    alias.symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError, match="outside DATA_DIR"):
        ModelWithOutputDir.delete_output_paths([alias / sentinel.name])

    assert sentinel.read_bytes() == b"must remain outside the collection"
    assert alias.is_symlink()


def test_delete_only_unlinks_final_symlink_to_external_directory(tmp_path, tmp_path_factory):
    outside = tmp_path_factory.mktemp("external-final-target")
    sentinel = outside / "saved.txt"
    sentinel.write_bytes(b"preserve target")
    alias = tmp_path / "alias"
    alias.symlink_to(outside, target_is_directory=True)

    ModelWithOutputDir.delete_output_paths([alias])

    assert not alias.is_symlink()
    assert sentinel.read_bytes() == b"preserve target"


def test_delete_removes_real_file_directory_and_dangling_link(tmp_path):
    file = tmp_path / "saved.txt"
    file.write_bytes(b"saved")
    directory = tmp_path / "capture"
    directory.mkdir()
    (directory / "saved.txt").write_bytes(b"captured")
    dangling = tmp_path / "dangling"
    dangling.symlink_to("missing-target")
    missing = tmp_path / "missing-parent" / "missing"

    ModelWithOutputDir.delete_output_paths([file, directory, dangling, missing, file, directory])

    assert not file.exists()
    assert not directory.exists()
    assert not dangling.is_symlink()
    assert not missing.exists()


def test_delete_rejects_collection_root_and_parent_traversal(tmp_path, tmp_path_factory):
    sentinel = tmp_path / "saved.txt"
    sentinel.write_bytes(b"keep collection")
    with pytest.raises(ValueError, match="outside DATA_DIR"):
        ModelWithOutputDir.delete_output_paths([tmp_path])
    assert sentinel.read_bytes() == b"keep collection"
    outside = tmp_path_factory.mktemp("parent-traversal")
    external = outside / "saved.txt"
    external.write_bytes(b"keep external")
    traversal = tmp_path / ".." / outside.name / external.name
    with pytest.raises(ValueError, match="outside DATA_DIR"):
        ModelWithOutputDir.delete_output_paths([traversal])
    assert external.read_bytes() == b"keep external"


@pytest.mark.django_db(transaction=True)
def test_scheduled_deletion_preserves_unsafe_row_and_continues_next_page(admin_user, tmp_path_factory):
    from archivebox.core.models import Snapshot
    from archivebox.crawls.models import Crawl

    crawl = Crawl.objects.create(urls="https://archivebox.io/tests/delete", created_by=admin_user)
    unsafe = Snapshot.objects.create(
        url=crawl.urls,
        crawl=crawl,
        status="deleting",
        fs_version=Snapshot._fs_current_version(),
    )
    outside = tmp_path_factory.mktemp("outside-queued-deletion")
    path = unsafe.output_dir
    path.parent.parent.mkdir(parents=True, exist_ok=True)
    path.parent.symlink_to(outside, target_is_directory=True)
    external = outside / path.name
    external.mkdir()
    (external / "saved.txt").write_bytes(b"preserve outside")
    safe = Snapshot.objects.create(
        url="https://docs.archivebox.io/tests/delete",
        crawl=crawl,
        status="deleting",
        fs_version=Snapshot._fs_current_version(),
    )
    safe_path = safe.output_dir
    safe_path.mkdir(parents=True)
    (safe_path / "saved.txt").write_bytes(b"remove this capture")

    Snapshot.delete_requested(batch_size=1, drain=True)

    assert Snapshot.objects.filter(pk=unsafe.pk, status="deleting").exists()
    assert (external / "saved.txt").read_bytes() == b"preserve outside"
    assert not Snapshot.objects.filter(pk=safe.pk).exists()
    assert not safe_path.exists()
