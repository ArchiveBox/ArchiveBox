import os
import unittest
from pathlib import Path


os.environ.setdefault("DJANGO_SETTINGS_MODULE", "archivebox.settings")


from archivebox.machine.models import Process


class TestProcessRuntimePaths(unittest.TestCase):
    def test_hook_processes_use_isolated_runtime_dir(self):
        process = Process(
            process_type=Process.TypeChoices.HOOK,
            pwd="/tmp/archive/example/chrome",
            cmd=["node", "/plugins/chrome/on_Snapshot__11_chrome_wait.js", "--url=https://example.com"],
        )

        expected_dir = Path("/tmp/archive/example/chrome/.hooks/on_Snapshot__11_chrome_wait.js")
        self.assertEqual(process.runtime_dir, expected_dir)
        self.assertEqual(process.stdout_file, expected_dir / "stdout.log")
        self.assertEqual(process.stderr_file, expected_dir / "stderr.log")
        self.assertEqual(process.pid_file, expected_dir / "process.pid")

    def test_non_hook_processes_keep_runtime_files_in_pwd(self):
        process = Process(
            process_type=Process.TypeChoices.WORKER,
            pwd="/tmp/archive/example",
            cmd=["archivebox", "run", "--snapshot-id", "123"],
        )

        expected_dir = Path("/tmp/archive/example")
        self.assertEqual(process.runtime_dir, expected_dir)
        self.assertEqual(process.stdout_file, expected_dir / "stdout.log")
        self.assertEqual(process.stderr_file, expected_dir / "stderr.log")
        self.assertEqual(process.pid_file, expected_dir / "process.pid")
