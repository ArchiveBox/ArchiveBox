#!/usr/bin/env python3

__package__ = 'archivebox.cli'
__command__ = 'archivebox ipfs'

import sys
from pathlib import Path

import rich_click as click

from archivebox.misc.util import enforce_types, docstring
from archivebox.config.common import STORAGE_CONFIG


@click.group()
@click.pass_context
def ipfs(ctx):
    """Manage IPFS storage backend for ArchiveBox"""
    pass


@ipfs.command()
@click.pass_context
@enforce_types
def test(ctx):
    """Test IPFS connectivity and configuration"""
    try:
        from archivebox.storage import IPFSStorageBackend
        
        print("[*] Testing IPFS connectivity...")
        
        # Check if IPFS is enabled
        if not STORAGE_CONFIG.USE_IPFS:
            print("[!] IPFS is not enabled. Enable it with: archivebox config --set USE_IPFS=True")
            return
        
        # Test connection
        ipfs_backend = IPFSStorageBackend()
        if ipfs_backend.test_connection():
            print(f"[+] IPFS connection successful!")
            print(f"    API URL: {STORAGE_CONFIG.IPFS_API_URL}")
            print(f"    Gateway URL: {STORAGE_CONFIG.IPFS_GATEWAY_URL}")
            print(f"    Timeout: {STORAGE_CONFIG.IPFS_TIMEOUT}s")
            print(f"    Pin files: {STORAGE_CONFIG.IPFS_PIN_FILES}")
            print(f"    Fallback to local: {STORAGE_CONFIG.IPFS_FALLBACK_TO_LOCAL}")
        else:
            print(f"[X] IPFS connection failed!")
            print(f"    API URL: {STORAGE_CONFIG.IPFS_API_URL}")
            print(f"    Make sure IPFS daemon is running and accessible")
            
    except ImportError:
        print("[X] IPFS storage module not available")
    except Exception as e:
        print(f"[X] Error testing IPFS: {e}")


@ipfs.command()
@click.argument('file_path', type=click.Path(exists=True))
@click.pass_context
@enforce_types
def add(ctx, file_path):
    """Add a file to IPFS"""
    try:
        from archivebox.storage import IPFSStorageBackend
        
        if not STORAGE_CONFIG.USE_IPFS:
            print("[!] IPFS is not enabled. Enable it with: archivebox config --set USE_IPFS=True")
            return
        
        print(f"[*] Adding file to IPFS: {file_path}")
        
        ipfs_backend = IPFSStorageBackend()
        if not ipfs_backend.test_connection():
            print("[X] IPFS connection failed!")
            return
        
        ipfs_hash = ipfs_backend.add_file(file_path)
        ipfs_url = ipfs_backend.get_file_url(ipfs_hash)
        
        print(f"[+] File added to IPFS successfully!")
        print(f"    Hash: {ipfs_hash}")
        print(f"    URL: {ipfs_url}")
        
    except ImportError:
        print("[X] IPFS storage module not available")
    except Exception as e:
        print(f"[X] Error adding file to IPFS: {e}")


@ipfs.command()
@click.pass_context
@enforce_types
def status(ctx):
    """Show IPFS configuration status"""
    print("[*] IPFS Configuration Status:")
    print(f"    Enabled: {STORAGE_CONFIG.USE_IPFS}")
    
    if STORAGE_CONFIG.USE_IPFS:
        print(f"    API URL: {STORAGE_CONFIG.IPFS_API_URL}")
        print(f"    Gateway URL: {STORAGE_CONFIG.IPFS_GATEWAY_URL}")
        print(f"    Timeout: {STORAGE_CONFIG.IPFS_TIMEOUT}s")
        print(f"    Pin files: {STORAGE_CONFIG.IPFS_PIN_FILES}")
        print(f"    Fallback to local: {STORAGE_CONFIG.IPFS_FALLBACK_TO_LOCAL}")
        
        # Test connection
        try:
            from archivebox.storage import IPFSStorageBackend
            ipfs_backend = IPFSStorageBackend()
            if ipfs_backend.test_connection():
                print(f"    Connection: [green]OK[/green]")
            else:
                print(f"    Connection: [red]FAILED[/red]")
        except Exception as e:
            print(f"    Connection: [red]ERROR - {e}[/red]")
    else:
        print("    [yellow]IPFS is disabled. Enable it with: archivebox config --set USE_IPFS=True[/yellow]")


@ipfs.command()
@click.pass_context
@enforce_types
def enable(ctx):
    """Enable IPFS storage backend"""
    try:
        from archivebox.cli.archivebox_config import set_config
        
        print("[*] Enabling IPFS storage backend...")
        set_config({'USE_IPFS': 'True'})
        print("[+] IPFS storage backend enabled!")
        print("    Run 'archivebox ipfs test' to verify connectivity")
        
    except Exception as e:
        print(f"[X] Error enabling IPFS: {e}")


@ipfs.command()
@click.pass_context
@enforce_types
def disable(ctx):
    """Disable IPFS storage backend"""
    try:
        from archivebox.cli.archivebox_config import set_config
        
        print("[*] Disabling IPFS storage backend...")
        set_config({'USE_IPFS': 'False'})
        print("[+] IPFS storage backend disabled!")
        
    except Exception as e:
        print(f"[X] Error disabling IPFS: {e}")


if __name__ == '__main__':
    ipfs() 