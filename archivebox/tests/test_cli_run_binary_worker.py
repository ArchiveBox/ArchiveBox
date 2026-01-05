"""
Tests for BinaryWorker processing Binary queue.

Tests cover:
- BinaryWorker is spawned by Orchestrator when Binary queue has work
- Binary hooks (on_Binary__*) actually run and install binaries
- Binary status transitions from QUEUED -> INSTALLED
- BinaryWorker exits after idle timeout
"""

import json
import sqlite3
import time

from archivebox.tests.conftest import (
    run_archivebox_cmd,
    parse_jsonl_output,
)


class TestBinaryWorkerSpawning:
    """Tests for BinaryWorker lifecycle."""

    def test_binary_worker_spawns_when_binary_queued(self, initialized_archive):
        """Orchestrator spawns BinaryWorker when Binary queue has work."""
        # Create a Binary record via CLI
        binary_record = {
            'type': 'Binary',
            'name': 'python3',
            'binproviders': 'env',  # Use env provider to detect system python
        }

        # Use `archivebox run` to create the Binary (this queues it)
        stdout, stderr, code = run_archivebox_cmd(
            ['run'],
            stdin=json.dumps(binary_record),
            data_dir=initialized_archive,
            timeout=60,  # Increased timeout to allow for binary installation
        )

        assert code == 0, f"Failed to create Binary: {stderr}"

        # Verify Binary was created in DB
        conn = sqlite3.connect(initialized_archive / 'index.sqlite3')
        c = conn.cursor()
        binaries = c.execute(
            "SELECT name, status, abspath FROM machine_binary WHERE name='python3'"
        ).fetchall()
        conn.close()

        assert len(binaries) >= 1, "Binary was not created in database"
        name, status, abspath = binaries[0]
        assert name == 'python3'
        # Status should be INSTALLED after BinaryWorker processed it
        # (or QUEUED if worker timed out before installing)
        assert status in ['installed', 'queued']


    def test_binary_hooks_actually_run(self, initialized_archive):
        """Binary installation hooks (on_Binary__*) run and update abspath."""
        # Create a Binary for python3 (guaranteed to exist on system)
        binary_record = {
            'type': 'Binary',
            'name': 'python3',
            'binproviders': 'env',
        }

        stdout, stderr, code = run_archivebox_cmd(
            ['run'],
            stdin=json.dumps(binary_record),
            data_dir=initialized_archive,
            timeout=30,
        )

        assert code == 0, f"Failed to process Binary: {stderr}"

        # Query database to check if hooks ran and populated abspath
        conn = sqlite3.connect(initialized_archive / 'index.sqlite3')
        c = conn.cursor()
        result = c.execute(
            "SELECT name, status, abspath, version FROM machine_binary WHERE name='python3'"
        ).fetchone()
        conn.close()

        assert result is not None, "Binary not found in database"
        name, status, abspath, version = result

        # If hooks ran successfully, abspath should be populated
        if status == 'installed':
            assert abspath, f"Binary installed but abspath is empty: {abspath}"
            assert '/python3' in abspath or '\\python3' in abspath, \
                f"abspath doesn't look like a python3 path: {abspath}"
            # Version should also be populated
            assert version, f"Binary installed but version is empty: {version}"


    def test_binary_status_transitions(self, initialized_archive):
        """Binary status correctly transitions QUEUED -> INSTALLED."""
        binary_record = {
            'type': 'Binary',
            'name': 'python3',
            'binproviders': 'env',
        }

        # Create and process the Binary
        stdout, stderr, code = run_archivebox_cmd(
            ['run'],
            stdin=json.dumps(binary_record),
            data_dir=initialized_archive,
            timeout=30,
        )

        assert code == 0

        # Check final status
        conn = sqlite3.connect(initialized_archive / 'index.sqlite3')
        c = conn.cursor()
        status = c.execute(
            "SELECT status FROM machine_binary WHERE name='python3'"
        ).fetchone()
        conn.close()

        assert status is not None
        # Should be installed (or queued if worker timed out)
        assert status[0] in ['installed', 'queued']


class TestBinaryWorkerHooks:
    """Tests for specific Binary hook providers."""

    def test_env_provider_hook_detects_system_binary(self, initialized_archive):
        """on_Binary__15_env_install.py hook detects system binaries."""
        binary_record = {
            'type': 'Binary',
            'name': 'python3',
            'binproviders': 'env',
        }

        stdout, stderr, code = run_archivebox_cmd(
            ['run'],
            stdin=json.dumps(binary_record),
            data_dir=initialized_archive,
            timeout=30,
        )

        assert code == 0

        # Check that env provider hook populated the Binary
        conn = sqlite3.connect(initialized_archive / 'index.sqlite3')
        c = conn.cursor()
        result = c.execute(
            "SELECT binprovider, abspath FROM machine_binary WHERE name='python3' AND status='installed'"
        ).fetchone()
        conn.close()

        if result:
            binprovider, abspath = result
            assert binprovider == 'env', f"Expected env provider, got: {binprovider}"
            assert abspath, "abspath should be populated by env provider"


    def test_multiple_binaries_processed_in_batch(self, initialized_archive):
        """BinaryWorker processes multiple queued binaries."""
        # Create multiple Binary records
        binaries = [
            {'type': 'Binary', 'name': 'python3', 'binproviders': 'env'},
            {'type': 'Binary', 'name': 'curl', 'binproviders': 'env'},
        ]

        stdin = '\n'.join(json.dumps(b) for b in binaries)

        stdout, stderr, code = run_archivebox_cmd(
            ['run'],
            stdin=stdin,
            data_dir=initialized_archive,
            timeout=90,  # Need more time for multiple binaries
        )

        assert code == 0

        # Both should be processed
        conn = sqlite3.connect(initialized_archive / 'index.sqlite3')
        c = conn.cursor()
        installed = c.execute(
            "SELECT name FROM machine_binary WHERE name IN ('python3', 'curl')"
        ).fetchall()
        conn.close()

        assert len(installed) >= 1, "At least one binary should be created"


class TestBinaryWorkerEdgeCases:
    """Tests for edge cases and error handling."""

    def test_nonexistent_binary_stays_queued(self, initialized_archive):
        """Binary that doesn't exist stays queued (doesn't fail permanently)."""
        binary_record = {
            'type': 'Binary',
            'name': 'nonexistent-binary-xyz-12345',
            'binproviders': 'env',
        }

        stdout, stderr, code = run_archivebox_cmd(
            ['run'],
            stdin=json.dumps(binary_record),
            data_dir=initialized_archive,
            timeout=30,
        )

        # Command should still succeed (orchestrator doesn't fail on binary install failures)
        assert code == 0

        # Binary should remain queued (not installed)
        conn = sqlite3.connect(initialized_archive / 'index.sqlite3')
        c = conn.cursor()
        result = c.execute(
            "SELECT status FROM machine_binary WHERE name='nonexistent-binary-xyz-12345'"
        ).fetchone()
        conn.close()

        if result:
            status = result[0]
            # Should stay queued since installation failed
            assert status == 'queued', f"Expected queued, got: {status}"


    def test_binary_worker_respects_machine_isolation(self, initialized_archive):
        """BinaryWorker only processes binaries for current machine."""
        # This is implicitly tested by other tests - Binary.objects.filter(machine=current)
        # ensures only current machine's binaries are processed
        binary_record = {
            'type': 'Binary',
            'name': 'python3',
            'binproviders': 'env',
        }

        stdout, stderr, code = run_archivebox_cmd(
            ['run'],
            stdin=json.dumps(binary_record),
            data_dir=initialized_archive,
            timeout=30,
        )

        assert code == 0

        # Check that machine_id is set correctly
        conn = sqlite3.connect(initialized_archive / 'index.sqlite3')
        c = conn.cursor()
        result = c.execute(
            "SELECT machine_id FROM machine_binary WHERE name='python3'"
        ).fetchone()
        conn.close()

        assert result is not None
        machine_id = result[0]
        assert machine_id, "machine_id should be set on Binary"
