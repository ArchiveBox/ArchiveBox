from .fixtures import *
from archivebox.extractors import ignore_methods, get_default_archive_methods, should_save_title

def test_wget_broken_pipe(tmp_path, process):
    add_process = subprocess.run(['archivebox', 'add', 'http://127.0.0.1:8080/static/example.com.html'], capture_output=True)
    assert "TypeError chmod_file(..., path: str) got unexpected NoneType argument path=None" not in add_process.stdout.decode("utf-8")

def test_ignore_methods():
    """
    Takes the passed method out of the default methods list and returns that value
    """
    ignored = ignore_methods(['title'])
    assert should_save_title not in ignored