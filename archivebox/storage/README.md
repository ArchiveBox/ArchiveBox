# IPFS Storage Backend for ArchiveBox

This module provides optional IPFS (InterPlanetary File System) storage support for ArchiveBox. When enabled, archived files are automatically uploaded to IPFS in addition to being saved locally, providing decentralized storage and access.

## Features

- **Hybrid Storage**: Files are saved both locally and to IPFS for redundancy
- **Fallback Support**: If IPFS is unavailable, files are still saved locally
- **Configurable**: Easy to enable/disable and configure IPFS settings
- **Hash Tracking**: IPFS hashes are stored in the database for easy access
- **Gateway URLs**: Automatic generation of IPFS gateway URLs for file access

## Configuration

### Enable IPFS Storage

```bash
# Enable IPFS storage
archivebox config --set USE_IPFS=True

# Configure IPFS settings
archivebox config --set IPFS_API_URL=http://localhost:5001
archivebox config --set IPFS_GATEWAY_URL=https://ipfs.io/ipfs/
archivebox config --set IPFS_TIMEOUT=30
archivebox config --set IPFS_PIN_FILES=True
archivebox config --set IPFS_FALLBACK_TO_LOCAL=True
```

### Configuration Options

| Setting                  | Default                 | Description                                      |
| ------------------------ | ----------------------- | ------------------------------------------------ |
| `USE_IPFS`               | `False`                 | Enable IPFS storage backend                      |
| `IPFS_API_URL`           | `http://localhost:5001` | IPFS API endpoint URL                            |
| `IPFS_GATEWAY_URL`       | `https://ipfs.io/ipfs/` | IPFS gateway URL for accessing files             |
| `IPFS_TIMEOUT`           | `30`                    | Timeout for IPFS API calls in seconds            |
| `IPFS_PIN_FILES`         | `True`                  | Pin files in IPFS to prevent garbage collection  |
| `IPFS_FALLBACK_TO_LOCAL` | `True`                  | Fallback to local storage if IPFS is unavailable |

## Usage

### CLI Commands

```bash
# Test IPFS connectivity
archivebox ipfs test

# Show IPFS status
archivebox ipfs status

# Enable IPFS storage
archivebox ipfs enable

# Disable IPFS storage
archivebox ipfs disable

# Add a file to IPFS manually
archivebox ipfs add /path/to/file
```

### Programmatic Usage

```python
from archivebox.storage import write_file_with_ipfs, IPFSStorageBackend

# Write a file with IPFS support
result = write_file_with_ipfs('/path/to/file.txt', 'Hello, IPFS!')
if result.get('ipfs_hash'):
    print(f"File saved to IPFS: {result['ipfs_hash']}")
    print(f"Gateway URL: {result['ipfs_url']}")

# Use IPFS backend directly
ipfs_backend = IPFSStorageBackend()
if ipfs_backend.test_connection():
    ipfs_hash = ipfs_backend.add_file('/path/to/file.txt')
    print(f"IPFS hash: {ipfs_hash}")
```

## Database Schema

The `ArchiveResult` model has been extended with IPFS fields:

- `ipfs_hash`: The IPFS hash of the archived file
- `storage_type`: Type of storage used ('local', 'ipfs', or 'hybrid')
- `ipfs_url` (property): Dynamically generated IPFS gateway URL using global configuration

## Setup Requirements

### 1. Install IPFS

Install and run an IPFS daemon:

```bash
# Install IPFS (example for Ubuntu)
wget https://dist.ipfs.io/go-ipfs/v0.20.0/go-ipfs_v0.20.0_linux-amd64.tar.gz
tar -xvzf go-ipfs_v0.20.0_linux-amd64.tar.gz
cd go-ipfs
sudo bash install.sh

# Initialize IPFS
ipfs init

# Start IPFS daemon
ipfs daemon
```

### 2. Install Python Dependencies

The IPFS storage backend requires the `requests` library (already included in ArchiveBox dependencies).

### 3. Configure ArchiveBox

```bash
# Enable IPFS storage
archivebox config --set USE_IPFS=True

# Test connectivity
archivebox ipfs test
```

## How It Works

1. **File Writing**: When `atomic_write()` is called with `use_ipfs=True`, the file is written locally first, then uploaded to IPFS
2. **Hash Storage**: The IPFS hash and gateway URL are stored in the `ArchiveResult` model
3. **Fallback**: If IPFS is unavailable, files are still saved locally
4. **Access**: Files can be accessed via local path or IPFS gateway URL

## Benefits

- **Decentralized Storage**: Files are distributed across the IPFS network
- **Permanent URLs**: IPFS hashes provide permanent, content-addressed URLs
- **Redundancy**: Files are stored both locally and on IPFS
- **Accessibility**: Files can be accessed via any IPFS gateway
- **No Vendor Lock-in**: IPFS is an open protocol

## Limitations

- **Network Dependency**: Requires IPFS daemon to be running
- **Upload Time**: Files take additional time to upload to IPFS
- **Storage Costs**: Files are stored both locally and on IPFS
- **Gateway Reliability**: Depends on IPFS gateway availability

## Troubleshooting

### IPFS Connection Issues

```bash
# Check if IPFS daemon is running
ipfs id

# Test API connectivity
curl http://localhost:5001/api/v0/version

# Check ArchiveBox IPFS status
archivebox ipfs status
```

### Common Issues

1. **IPFS daemon not running**: Start with `ipfs daemon`
2. **Wrong API URL**: Check `IPFS_API_URL` configuration
3. **Network issues**: Ensure IPFS daemon is accessible
4. **Permission issues**: Check IPFS daemon permissions

## Migration

Existing ArchiveBox installations can enable IPFS storage without affecting current data. New files will be uploaded to IPFS, while existing files remain local-only.

To migrate existing files to IPFS:

```bash
# This would require a custom migration script
# Not currently implemented
```
