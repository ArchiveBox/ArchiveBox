from .fixtures import *

def test_remove_leaves_index_in_consistent_state(tmp_path, process, disable_extractors_dict):
    os.chdir(tmp_path)
    subprocess.run(['archivebox', 'add', 'http://127.0.0.1:8080/static/example.com.html'], capture_output=True, env=disable_extractors_dict)
    remove_process = subprocess.run(['archivebox', 'remove', '127.0.0.1:8080/static/example.com.html', '--yes'], capture_output=True)
    list_process = subprocess.run(['archivebox', 'list'], capture_output=True)
    assert "Warning: SQL index does not match JSON index!" not in list_process.stderr.decode("utf-8")