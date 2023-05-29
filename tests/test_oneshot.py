from pathlib import Path

from .fixtures import *

def test_oneshot_command_exists(tmp_path, disable_extractors_dict):
    os.chdir(tmp_path)
    process = subprocess.run(['archivebox', 'oneshot'], capture_output=True, env=disable_extractors_dict)
    assert not "invalid choice: 'oneshot'" in process.stderr.decode("utf-8")

def test_oneshot_command_saves_page_in_right_folder(tmp_path, disable_extractors_dict):
    disable_extractors_dict.update({"SAVE_DOM": "true"})
    process = subprocess.run(
        [
            "archivebox",
            "oneshot",
            f"--out-dir={tmp_path}",
            "--extract=title,favicon,dom",
            "http://127.0.0.1:8080/static/example.com.html",
        ],
        capture_output=True,
        env=disable_extractors_dict,
    )
    items = ' '.join([str(x) for x in tmp_path.iterdir()])
    current_path = ' '.join([str(x) for x in Path.cwd().iterdir()])
    assert "index.json" in items
    assert not "index.sqlite3" in current_path
    assert "output.html" in items

def test_oneshot_command_succeeds(tmp_path, disable_extractors_dict):
    disable_extractors_dict.update({"SAVE_DOM": "true"})
    process = subprocess.run(
        [
            "archivebox",
            "oneshot",
            f"--out-dir={tmp_path}",
            "--extract=title,favicon,dom",
            "http://127.0.0.1:8080/static/example.com.html",
        ],
        capture_output=True,
        env=disable_extractors_dict,
    )

    assert process.returncode == 0

def test_oneshot_command_logs_archiving_finished(tmp_path, disable_extractors_dict):
    disable_extractors_dict.update({"SAVE_DOM": "true"})
    process = subprocess.run(
        [
            "archivebox",
            "oneshot",
            f"--out-dir={tmp_path}",
            "--extract=title,favicon,dom",
            "http://127.0.0.1:8080/static/example.com.html",
        ],
        capture_output=True,
        env=disable_extractors_dict,
    )

    output_str = process.stdout.decode("utf-8")
    assert "4 files" in output_str
