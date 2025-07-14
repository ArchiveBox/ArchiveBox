__package__ = 'archivebox.storage'

from pathlib import Path
from typing import Union, Optional, Dict, Any
import json
import requests
from urllib.parse import urljoin

from archivebox.config.common import STORAGE_CONFIG
from archivebox.misc.system import atomic_write
from archivebox.misc.util import enforce_types


class IPFSStorageBackend:
    """IPFS storage backend for ArchiveBox files"""
    
    def __init__(self, api_url: str = None, gateway_url: str = None, timeout: int = None):
        self.api_url = api_url or STORAGE_CONFIG.IPFS_API_URL
        self.gateway_url = gateway_url or STORAGE_CONFIG.IPFS_GATEWAY_URL
        self.timeout = timeout or STORAGE_CONFIG.IPFS_TIMEOUT
        
    def _make_api_request(self, endpoint: str, method: str = 'GET', data: Any = None, files: Any = None) -> Dict[str, Any]:
        """Make a request to the IPFS API"""
        url = urljoin(self.api_url, endpoint)
        
        try:
            if method == 'GET':
                response = requests.get(url, timeout=self.timeout)
            elif method == 'POST':
                response = requests.post(url, data=data, files=files, timeout=self.timeout)
            else:
                raise ValueError(f"Unsupported HTTP method: {method}")
                
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            raise IPFSError(f"IPFS API request failed: {e}")
    
    def add_file(self, file_path: Union[str, Path], pin: bool = None) -> str:
        """Add a file to IPFS and return its hash"""
        pin = pin if pin is not None else STORAGE_CONFIG.IPFS_PIN_FILES
        
        with open(file_path, 'rb') as f:
            files = {'file': f}
            data = {'pin': str(pin).lower()}
            
            result = self._make_api_request('/api/v0/add', method='POST', data=data, files=files)
            
        return result['Hash']
    
    def add_data(self, data: Union[str, bytes], pin: bool = None) -> str:
        """Add data to IPFS and return its hash"""
        pin = pin if pin is not None else STORAGE_CONFIG.IPFS_PIN_FILES
        
        if isinstance(data, str):
            data = data.encode('utf-8')
            
        files = {'file': ('data', data)}
        api_data = {'pin': str(pin).lower()}
        
        result = self._make_api_request('/api/v0/add', method='POST', data=api_data, files=files)
        
        return result['Hash']
    
    def get_file_url(self, ipfs_hash: str) -> str:
        """Get the gateway URL for an IPFS hash"""
        return urljoin(self.gateway_url, ipfs_hash)
    
    def test_connection(self) -> bool:
        """Test if IPFS API is accessible"""
        try:
            result = self._make_api_request('/api/v0/version')
            return 'Version' in result
        except Exception:
            return False


class IPFSError(Exception):
    """Exception raised for IPFS-related errors"""
    pass


class HybridStorageBackend:
    """Hybrid storage backend that can use IPFS or fallback to local storage"""
    
    def __init__(self):
        self.ipfs_backend = IPFSStorageBackend() if STORAGE_CONFIG.USE_IPFS else None
        self.use_ipfs = STORAGE_CONFIG.USE_IPFS
        self.fallback_to_local = STORAGE_CONFIG.IPFS_FALLBACK_TO_LOCAL
    
    def write_file(self, path: Union[str, Path], contents: Union[dict, str, bytes], 
                   overwrite: bool = True) -> Dict[str, Any]:
        """Write a file using IPFS if enabled, otherwise use local storage"""
        result = {
            'storage_type': 'local',
            'local_path': str(path),
            'ipfs_hash': None,
            'success': False
        }
        
        # Always write to local storage first (for compatibility and fallback)
        try:
            atomic_write(path, contents, overwrite=overwrite)
            result['success'] = True
        except Exception as e:
            if not self.fallback_to_local:
                raise e
            result['error'] = f"Local write failed: {e}"
            return result
        
        # If IPFS is enabled, also add to IPFS
        if self.use_ipfs and self.ipfs_backend:
            try:
                if self.ipfs_backend.test_connection():
                    ipfs_hash = self.ipfs_backend.add_file(path)
                    result['storage_type'] = 'hybrid'
                    result['ipfs_hash'] = ipfs_hash
                else:
                    result['ipfs_error'] = "IPFS API not accessible"
            except Exception as e:
                result['ipfs_error'] = f"IPFS upload failed: {e}"
        
        return result
    
    def write_data(self, path: Union[str, Path], contents: Union[dict, str, bytes], 
                   overwrite: bool = True) -> Dict[str, Any]:
        """Write data directly to IPFS if enabled, otherwise use local storage"""
        result = {
            'storage_type': 'local',
            'local_path': str(path),
            'ipfs_hash': None,
            'success': False
        }
        
        # Always write to local storage first
        try:
            atomic_write(path, contents, overwrite=overwrite)
            result['success'] = True
        except Exception as e:
            if not self.fallback_to_local:
                raise e
            result['error'] = f"Local write failed: {e}"
            return result
        
        # If IPFS is enabled, also add data to IPFS
        if self.use_ipfs and self.ipfs_backend:
            try:
                if self.ipfs_backend.test_connection():
                    ipfs_hash = self.ipfs_backend.add_data(contents)
                    result['storage_type'] = 'hybrid'
                    result['ipfs_hash'] = ipfs_hash
                else:
                    result['ipfs_error'] = "IPFS API not accessible"
            except Exception as e:
                result['ipfs_error'] = f"IPFS upload failed: {e}"
        
        return result
    
    def get_ipfs_url(self, ipfs_hash: str) -> str:
        """Get the IPFS gateway URL for a hash using global configuration"""
        if self.ipfs_backend:
            return self.ipfs_backend.get_file_url(ipfs_hash)
        return f"{STORAGE_CONFIG.IPFS_GATEWAY_URL}{ipfs_hash}"


# Global storage backend instance
storage_backend = HybridStorageBackend()


@enforce_types
def write_file_with_ipfs(path: Union[str, Path], contents: Union[dict, str, bytes], 
                         overwrite: bool = True) -> Dict[str, Any]:
    """Write a file using the hybrid storage backend (IPFS + local)"""
    return storage_backend.write_file(path, contents, overwrite)


@enforce_types
def write_data_with_ipfs(path: Union[str, Path], contents: Union[dict, str, bytes], 
                         overwrite: bool = True) -> Dict[str, Any]:
    """Write data using the hybrid storage backend (IPFS + local)"""
    return storage_backend.write_data(path, contents, overwrite)


@enforce_types
def update_archiveresult_with_ipfs(archiveresult, storage_result: Dict[str, Any]) -> None:
    """Update an ArchiveResult object with IPFS information from storage operation"""
    if not storage_result.get('success'):
        return
        
    # Update storage type
    archiveresult.storage_type = storage_result.get('storage_type', 'local')
    
    # Update IPFS hash if available
    if storage_result.get('ipfs_hash'):
        archiveresult.ipfs_hash = storage_result['ipfs_hash']
    
    # Save the updated ArchiveResult
    archiveresult.save(update_fields=['storage_type', 'ipfs_hash']) 