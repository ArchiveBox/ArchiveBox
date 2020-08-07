from .fixtures import *
from archivebox.extractors import ignore_methods, get_default_archive_methods, should_save_title

def test_wget_broken_pipe(tmp_path, process, disable_extractors_dict):
    disable_extractors_dict.update({"USE_WGET": "true"})
    add_process = subprocess.run(['archivebox', 'add', 'http://127.0.0.1:8080/static/example.com.html'],
                                 capture_output=True, env=disable_extractors_dict)
    assert "TypeError chmod_file(..., path: str) got unexpected NoneType argument path=None" not in add_process.stdout.decode("utf-8")

def test_ignore_methods():
    """
    Takes the passed method out of the default methods list and returns that value
    """
    ignored = ignore_methods(['title'])
    assert should_save_title not in ignored

def test_singlefile_works(tmp_path, process, disable_extractors_dict):
    disable_extractors_dict.update({"USE_SINGLEFILE": "true"})
    add_process = subprocess.run(['archivebox', 'add', 'http://127.0.0.1:8080/static/example.com.html'],
                                  capture_output=True, env=disable_extractors_dict) 
    archived_item_path = list(tmp_path.glob('archive/**/*'))[0]
    output_file = archived_item_path / "singlefile.html" 
    assert output_file.exists()
