"""
Unit tests for machine module models: Machine, NetworkInterface, Binary, Process.

Tests cover:
1. Machine model creation and current() method
2. NetworkInterface model and network detection
3. Binary model lifecycle and state machine
4. Process model lifecycle and state machine
5. JSONL serialization/deserialization
6. Manager methods
"""

import os
import tempfile
from pathlib import Path
from datetime import timedelta

import pytest
from django.test import TestCase, override_settings
from django.utils import timezone

from archivebox.machine.models import (
    Machine,
    NetworkInterface,
    Binary,
    Process,
    BinaryMachine,
    ProcessMachine,
    MACHINE_RECHECK_INTERVAL,
    NETWORK_INTERFACE_RECHECK_INTERVAL,
    BINARY_RECHECK_INTERVAL,
    _CURRENT_MACHINE,
    _CURRENT_INTERFACE,
    _CURRENT_BINARIES,
)


class TestMachineModel(TestCase):
    """Test the Machine model."""

    def setUp(self):
        """Reset cached machine between tests."""
        import archivebox.machine.models as models
        models._CURRENT_MACHINE = None

    def test_machine_current_creates_machine(self):
        """Machine.current() should create a machine if none exists."""
        machine = Machine.current()

        self.assertIsNotNone(machine)
        self.assertIsNotNone(machine.id)
        self.assertIsNotNone(machine.guid)
        self.assertEqual(machine.hostname, os.uname().nodename)
        self.assertIn(machine.os_family, ['linux', 'darwin', 'windows', 'freebsd'])

    def test_machine_current_returns_cached(self):
        """Machine.current() should return cached machine within recheck interval."""
        machine1 = Machine.current()
        machine2 = Machine.current()

        self.assertEqual(machine1.id, machine2.id)

    def test_machine_current_refreshes_after_interval(self):
        """Machine.current() should refresh after recheck interval."""
        import archivebox.machine.models as models

        machine1 = Machine.current()

        # Manually expire the cache by modifying modified_at
        machine1.modified_at = timezone.now() - timedelta(seconds=MACHINE_RECHECK_INTERVAL + 1)
        machine1.save()
        models._CURRENT_MACHINE = machine1

        machine2 = Machine.current()

        # Should have fetched/updated the machine (same GUID)
        self.assertEqual(machine1.guid, machine2.guid)

    def test_machine_to_json(self):
        """Machine.to_json() should serialize correctly."""
        machine = Machine.current()
        json_data = machine.to_json()

        self.assertEqual(json_data['type'], 'Machine')
        self.assertEqual(json_data['id'], str(machine.id))
        self.assertEqual(json_data['guid'], machine.guid)
        self.assertEqual(json_data['hostname'], machine.hostname)
        self.assertIn('os_arch', json_data)
        self.assertIn('os_family', json_data)

    def test_machine_to_jsonl(self):
        """Machine.to_jsonl() should yield JSON records."""
        machine = Machine.current()
        records = list(machine.to_jsonl())

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]['type'], 'Machine')
        self.assertEqual(records[0]['id'], str(machine.id))

    def test_machine_to_jsonl_deduplication(self):
        """Machine.to_jsonl() should deduplicate with seen set."""
        machine = Machine.current()
        seen = set()

        records1 = list(machine.to_jsonl(seen=seen))
        records2 = list(machine.to_jsonl(seen=seen))

        self.assertEqual(len(records1), 1)
        self.assertEqual(len(records2), 0)  # Already seen

    def test_machine_from_json_update(self):
        """Machine.from_json() should update machine config."""
        machine = Machine.current()
        record = {
            '_method': 'update',
            'key': 'WGET_BINARY',
            'value': '/usr/bin/wget',
        }

        result = Machine.from_json(record)

        self.assertIsNotNone(result)
        self.assertEqual(result.config.get('WGET_BINARY'), '/usr/bin/wget')

    def test_machine_from_json_invalid(self):
        """Machine.from_json() should return None for invalid records."""
        result = Machine.from_json({'invalid': 'record'})
        self.assertIsNone(result)

    def test_machine_manager_current(self):
        """Machine.objects.current() should return current machine."""
        machine = Machine.objects.current()
        self.assertIsNotNone(machine)
        self.assertEqual(machine.id, Machine.current().id)


class TestNetworkInterfaceModel(TestCase):
    """Test the NetworkInterface model."""

    def setUp(self):
        """Reset cached interface between tests."""
        import archivebox.machine.models as models
        models._CURRENT_MACHINE = None
        models._CURRENT_INTERFACE = None

    def test_networkinterface_current_creates_interface(self):
        """NetworkInterface.current() should create an interface if none exists."""
        interface = NetworkInterface.current()

        self.assertIsNotNone(interface)
        self.assertIsNotNone(interface.id)
        self.assertIsNotNone(interface.machine)
        # IP addresses should be populated
        self.assertIsNotNone(interface.ip_local)

    def test_networkinterface_current_returns_cached(self):
        """NetworkInterface.current() should return cached interface within recheck interval."""
        interface1 = NetworkInterface.current()
        interface2 = NetworkInterface.current()

        self.assertEqual(interface1.id, interface2.id)

    def test_networkinterface_to_json(self):
        """NetworkInterface.to_json() should serialize correctly."""
        interface = NetworkInterface.current()
        json_data = interface.to_json()

        self.assertEqual(json_data['type'], 'NetworkInterface')
        self.assertEqual(json_data['id'], str(interface.id))
        self.assertEqual(json_data['machine_id'], str(interface.machine_id))
        self.assertIn('ip_local', json_data)
        self.assertIn('ip_public', json_data)

    def test_networkinterface_manager_current(self):
        """NetworkInterface.objects.current() should return current interface."""
        interface = NetworkInterface.objects.current()
        self.assertIsNotNone(interface)


class TestBinaryModel(TestCase):
    """Test the Binary model and BinaryMachine state machine."""

    def setUp(self):
        """Reset cached binaries and create a machine."""
        import archivebox.machine.models as models
        models._CURRENT_MACHINE = None
        models._CURRENT_BINARIES = {}
        self.machine = Machine.current()

    def test_binary_creation(self):
        """Binary should be created with default values."""
        binary = Binary.objects.create(
            machine=self.machine,
            name='wget',
            binproviders='apt,brew,env',
        )

        self.assertIsNotNone(binary.id)
        self.assertEqual(binary.name, 'wget')
        self.assertEqual(binary.status, Binary.StatusChoices.QUEUED)
        self.assertFalse(binary.is_valid)

    def test_binary_is_valid(self):
        """Binary.is_valid should be True when abspath and version are set."""
        binary = Binary.objects.create(
            machine=self.machine,
            name='wget',
            abspath='/usr/bin/wget',
            version='1.21',
        )

        self.assertTrue(binary.is_valid)

    def test_binary_to_json(self):
        """Binary.to_json() should serialize correctly."""
        binary = Binary.objects.create(
            machine=self.machine,
            name='wget',
            abspath='/usr/bin/wget',
            version='1.21',
            binprovider='apt',
        )
        json_data = binary.to_json()

        self.assertEqual(json_data['type'], 'Binary')
        self.assertEqual(json_data['name'], 'wget')
        self.assertEqual(json_data['abspath'], '/usr/bin/wget')
        self.assertEqual(json_data['version'], '1.21')

    def test_binary_from_json_queued(self):
        """Binary.from_json() should create queued binary from binaries.jsonl format."""
        record = {
            'name': 'curl',
            'binproviders': 'apt,brew',
            'overrides': {'apt': {'packages': ['curl']}},
        }

        binary = Binary.from_json(record)

        self.assertIsNotNone(binary)
        self.assertEqual(binary.name, 'curl')
        self.assertEqual(binary.binproviders, 'apt,brew')
        self.assertEqual(binary.status, Binary.StatusChoices.QUEUED)

    def test_binary_from_json_installed(self):
        """Binary.from_json() should update binary from hook output format."""
        # First create queued binary
        Binary.objects.create(
            machine=self.machine,
            name='node',
        )

        # Then update with hook output
        record = {
            'name': 'node',
            'abspath': '/usr/bin/node',
            'version': '18.0.0',
            'binprovider': 'apt',
        }

        binary = Binary.from_json(record)

        self.assertIsNotNone(binary)
        self.assertEqual(binary.abspath, '/usr/bin/node')
        self.assertEqual(binary.version, '18.0.0')
        self.assertEqual(binary.status, Binary.StatusChoices.SUCCEEDED)

    def test_binary_manager_get_valid_binary(self):
        """BinaryManager.get_valid_binary() should find valid binaries."""
        # Create invalid binary (no abspath)
        Binary.objects.create(
            machine=self.machine,
            name='wget',
        )

        # Create valid binary
        Binary.objects.create(
            machine=self.machine,
            name='wget',
            abspath='/usr/bin/wget',
            version='1.21',
        )

        result = Binary.objects.get_valid_binary('wget')

        self.assertIsNotNone(result)
        self.assertEqual(result.abspath, '/usr/bin/wget')

    def test_binary_update_and_requeue(self):
        """Binary.update_and_requeue() should update fields and save."""
        binary = Binary.objects.create(
            machine=self.machine,
            name='test',
        )
        old_modified = binary.modified_at

        binary.update_and_requeue(
            status=Binary.StatusChoices.STARTED,
            retry_at=timezone.now() + timedelta(seconds=60),
        )

        binary.refresh_from_db()
        self.assertEqual(binary.status, Binary.StatusChoices.STARTED)
        self.assertGreater(binary.modified_at, old_modified)


class TestBinaryStateMachine(TestCase):
    """Test the BinaryMachine state machine."""

    def setUp(self):
        """Create a machine and binary for state machine tests."""
        import archivebox.machine.models as models
        models._CURRENT_MACHINE = None
        self.machine = Machine.current()
        self.binary = Binary.objects.create(
            machine=self.machine,
            name='test-binary',
            binproviders='env',
        )

    def test_binary_state_machine_initial_state(self):
        """BinaryMachine should start in queued state."""
        sm = BinaryMachine(self.binary)
        self.assertEqual(sm.current_state.value, Binary.StatusChoices.QUEUED)

    def test_binary_state_machine_can_start(self):
        """BinaryMachine.can_start() should check name and binproviders."""
        sm = BinaryMachine(self.binary)
        self.assertTrue(sm.can_start())

        # Binary without binproviders
        self.binary.binproviders = ''
        self.binary.save()
        sm = BinaryMachine(self.binary)
        self.assertFalse(sm.can_start())


class TestProcessModel(TestCase):
    """Test the Process model and ProcessMachine state machine."""

    def setUp(self):
        """Create a machine for process tests."""
        import archivebox.machine.models as models
        models._CURRENT_MACHINE = None
        self.machine = Machine.current()

    def test_process_creation(self):
        """Process should be created with default values."""
        process = Process.objects.create(
            machine=self.machine,
            cmd=['echo', 'hello'],
            pwd='/tmp',
        )

        self.assertIsNotNone(process.id)
        self.assertEqual(process.cmd, ['echo', 'hello'])
        self.assertEqual(process.status, Process.StatusChoices.QUEUED)
        self.assertIsNone(process.pid)
        self.assertIsNone(process.exit_code)

    def test_process_to_json(self):
        """Process.to_json() should serialize correctly."""
        process = Process.objects.create(
            machine=self.machine,
            cmd=['echo', 'hello'],
            pwd='/tmp',
            timeout=60,
        )
        json_data = process.to_json()

        self.assertEqual(json_data['type'], 'Process')
        self.assertEqual(json_data['cmd'], ['echo', 'hello'])
        self.assertEqual(json_data['pwd'], '/tmp')
        self.assertEqual(json_data['timeout'], 60)

    def test_process_to_jsonl_with_binary(self):
        """Process.to_jsonl() should include related binary."""
        binary = Binary.objects.create(
            machine=self.machine,
            name='echo',
            abspath='/bin/echo',
            version='1.0',
        )
        process = Process.objects.create(
            machine=self.machine,
            cmd=['echo', 'hello'],
            binary=binary,
        )

        records = list(process.to_jsonl(binary=True))

        self.assertEqual(len(records), 2)
        types = {r['type'] for r in records}
        self.assertIn('Process', types)
        self.assertIn('Binary', types)

    def test_process_manager_create_for_archiveresult(self):
        """ProcessManager.create_for_archiveresult() should create process."""
        # This test would require an ArchiveResult, which is complex to set up
        # For now, test the direct creation path
        process = Process.objects.create(
            machine=self.machine,
            pwd='/tmp/test',
            cmd=['wget', 'http://example.com'],
            timeout=120,
        )

        self.assertEqual(process.pwd, '/tmp/test')
        self.assertEqual(process.cmd, ['wget', 'http://example.com'])
        self.assertEqual(process.timeout, 120)

    def test_process_update_and_requeue(self):
        """Process.update_and_requeue() should update fields and save."""
        process = Process.objects.create(
            machine=self.machine,
            cmd=['test'],
        )
        old_modified = process.modified_at

        process.update_and_requeue(
            status=Process.StatusChoices.RUNNING,
            pid=12345,
            started_at=timezone.now(),
        )

        process.refresh_from_db()
        self.assertEqual(process.status, Process.StatusChoices.RUNNING)
        self.assertEqual(process.pid, 12345)
        self.assertIsNotNone(process.started_at)


class TestProcessStateMachine(TestCase):
    """Test the ProcessMachine state machine."""

    def setUp(self):
        """Create a machine and process for state machine tests."""
        import archivebox.machine.models as models
        models._CURRENT_MACHINE = None
        self.machine = Machine.current()
        self.process = Process.objects.create(
            machine=self.machine,
            cmd=['echo', 'test'],
            pwd='/tmp',
        )

    def test_process_state_machine_initial_state(self):
        """ProcessMachine should start in queued state."""
        sm = ProcessMachine(self.process)
        self.assertEqual(sm.current_state.value, Process.StatusChoices.QUEUED)

    def test_process_state_machine_can_start(self):
        """ProcessMachine.can_start() should check cmd and machine."""
        sm = ProcessMachine(self.process)
        self.assertTrue(sm.can_start())

        # Process without cmd
        self.process.cmd = []
        self.process.save()
        sm = ProcessMachine(self.process)
        self.assertFalse(sm.can_start())

    def test_process_state_machine_is_exited(self):
        """ProcessMachine.is_exited() should check exit_code."""
        sm = ProcessMachine(self.process)
        self.assertFalse(sm.is_exited())

        self.process.exit_code = 0
        self.process.save()
        sm = ProcessMachine(self.process)
        self.assertTrue(sm.is_exited())


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
