from .fixtures import *

def test_title_is_htmlencoded_in_index_html(tmp_path, process, disable_extractors_dict):
    """
    https://github.com/pirate/ArchiveBox/issues/330
    Unencoded content should not be rendered as it facilitates xss injections
    and breaks the layout.
    """
    add_process = subprocess.run(['archivebox', 'add', 'http://localhost:8080/static/title_with_html.com.html'],
                                 capture_output=True, env=disable_extractors_dict)

    with open(tmp_path / "index.html", "r") as f:
        output_html = f.read()

    assert "<textarea>" not in output_html