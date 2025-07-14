#!/usr/bin/env python3
"""
Test script for IPFS integration with ArchiveBox
"""

import os
import sys
import tempfile
from pathlib import Path

# Add the archivebox directory to the Python path
sys.path.insert(0, str(Path(__file__).parent.parent / 'archivebox'))

def test_ipfs_storage():
    """Test the IPFS storage backend"""
    print("Testing IPFS Storage Backend...")
    
    try:
        from archivebox.storage import IPFSStorageBackend, HybridStorageBackend
        from archivebox.config.common import STORAGE_CONFIG
        
        print(f"IPFS Enabled: {STORAGE_CONFIG.USE_IPFS}")
        print(f"API URL: {STORAGE_CONFIG.IPFS_API_URL}")
        
        # Test IPFS backend
        ipfs_backend = IPFSStorageBackend()
        
        # Test connection
        print("\n[*] Testing IPFS connection...")
        if ipfs_backend.test_connection():
            print("[+] IPFS connection successful!")
            
            # Test adding a file
            print("\n[*] Testing file upload...")
            with tempfile.NamedTemporaryFile(mode='w', delete=False) as f:
                f.write("Hello, IPFS! This is a test file from ArchiveBox.")
                temp_file = f.name
            
            try:
                ipfs_hash = ipfs_backend.add_file(temp_file)
                ipfs_url = ipfs_backend.get_file_url(ipfs_hash)
                
                print(f"[+] File uploaded successfully!")
                print(f"    Hash: {ipfs_hash}")
                print(f"    URL: {ipfs_url}")
                
            finally:
                os.unlink(temp_file)
        else:
            print("[!] IPFS connection failed. Make sure IPFS daemon is running.")
            
        # Test hybrid storage backend
        print("\n[*] Testing hybrid storage backend...")
        hybrid_backend = HybridStorageBackend()
        
        test_content = "Test content for hybrid storage"
        test_path = tempfile.mktemp()
        
        try:
            result = hybrid_backend.write_data(test_path, test_content)
            print(f"[+] Hybrid storage result: {result}")
            
            if result.get('ipfs_hash'):
                print(f"    IPFS Hash: {result['ipfs_hash']}")
                ipfs_url = hybrid_backend.get_ipfs_url(result['ipfs_hash'])
                print(f"    IPFS URL: {ipfs_url}")
            
        finally:
            if os.path.exists(test_path):
                os.unlink(test_path)
                
    except ImportError as e:
        print(f"[!] Import error: {e}")
    except Exception as e:
        print(f"[!] Error: {e}")


def test_configuration():
    """Test IPFS configuration"""
    print("\nTesting IPFS Configuration...")
    
    try:
        from archivebox.config.common import STORAGE_CONFIG
        
        print(f"USE_IPFS: {STORAGE_CONFIG.USE_IPFS}")
        print(f"IPFS_API_URL: {STORAGE_CONFIG.IPFS_API_URL}")
        print(f"IPFS_GATEWAY_URL: {STORAGE_CONFIG.IPFS_GATEWAY_URL}")
        print(f"IPFS_TIMEOUT: {STORAGE_CONFIG.IPFS_TIMEOUT}")
        print(f"IPFS_PIN_FILES: {STORAGE_CONFIG.IPFS_PIN_FILES}")
        print(f"IPFS_FALLBACK_TO_LOCAL: {STORAGE_CONFIG.IPFS_FALLBACK_TO_LOCAL}")
        
    except Exception as e:
        print(f"[!] Error: {e}")


def test_atomic_write_with_ipfs():
    """Test atomic_write with IPFS support"""
    print("\nTesting atomic_write with IPFS...")
    
    try:
        from archivebox.misc.system import atomic_write
        
        test_content = "Test content for atomic_write with IPFS"
        test_path = tempfile.mktemp()
        
        try:
            # Test with IPFS enabled
            print("[*] Testing atomic_write with IPFS enabled...")
            atomic_write(test_path, test_content, use_ipfs=True)
            
            # Verify file was written locally
            if os.path.exists(test_path):
                with open(test_path, 'r') as f:
                    content = f.read()
                if content == test_content:
                    print("[+] File written successfully with IPFS support")
                else:
                    print("[!] File content mismatch")
            else:
                print("[!] File was not written locally")
                
        finally:
            if os.path.exists(test_path):
                os.unlink(test_path)
                
    except Exception as e:
        print(f"[!] Error: {e}")


if __name__ == '__main__':
    print("ArchiveBox IPFS Integration Test")
    print("=" * 40)
    
    test_configuration()
    test_ipfs_storage()
    test_atomic_write_with_ipfs()
    
    print("\nTest completed!") 