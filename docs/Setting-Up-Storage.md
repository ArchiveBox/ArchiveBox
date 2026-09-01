# Setting Up Storage

ArchiveBox supports a wide range of local and remote filesystems using `rclone` and/or Docker storage plugins. The examples below use [Docker Compose bind mounts](https://docs.docker.com/storage/bind-mounts/) to demonstrate the concepts; adapt the host paths, ownership, and provider settings to your environment.

Example [`docker-compose.yml`](https://github.com/ArchiveBox/ArchiveBox/blob/dev/docker-compose.yml) storage setup:
```yaml
services:
    archivebox:
        # ...other service settings...
        volumes:
            # your index db, config, logs, etc. should be stored on a local SSD (usually <10Gb)
            - ./data:/data

            # but bulk archive/ content can be located on an HDD or remote filesystem
            - /mnt/archivebox-archive:/data/archive
```

<h4>Related Docs</h4>
<ul>
<li><a href="https://github.com/ArchiveBox/ArchiveBox#archive-layout">README: Archive Layout</a></li>
<li><a href="https://github.com/ArchiveBox/ArchiveBox/wiki/Usage#Disk-Layout">Wiki: Usage (Disk Layout)</a></li>
<li><a href="https://github.com/ArchiveBox/ArchiveBox/wiki/Usage#large-archives">Wiki: Usage (Large Archives)</a></li>
<li><a href="https://github.com/ArchiveBox/ArchiveBox/wiki/Security-Overview#output-folder">Wiki: Security Overview (Output Folder)</a></li>
<li><a href="https://github.com/ArchiveBox/ArchiveBox/wiki/Publishing-Your-Archive">Wiki: Publishing Your Archive</a></li>
<li><a href="https://github.com/ArchiveBox/ArchiveBox/wiki/Upgrading-or-Merging-Archives">Wiki: Upgrading or Merging Archives</a></li>
<li><a href="https://github.com/ArchiveBox/ArchiveBox/wiki/Troubleshooting#other-database-or-filesystem-issues">Wiki: Troubleshooting Filesystem Issues</a></li>
</ul>

---

## Supported Local Filesystems

<img src="https://github.com/ArchiveBox/ArchiveBox/assets/511499/45abfe78-87c4-4c87-ab11-9dae2f3b2518" alt="local filesystem icon" width="80px" align="right"/>

<a name="ext4"></a><a name="apfs"></a>

### `EXT4` (default on Linux), `APFS` (default on macOS)

> [!TIP]
> These default filesystems are fully supported by ArchiveBox on Linux and macOS (w/wo Docker).

<a name="zfs"></a>

### `ZFS` (recommended for experienced Linux/BSD operators) ⭐️

> [!TIP]
> *ZFS is a good choice when you already operate OpenZFS and want checksumming, compression, snapshots, replication, and optional encryption or disk redundancy.*
> On Ubuntu, follow the official [OpenZFS installation guide](https://openzfs.github.io/openzfs-docs/Getting%20Started/Ubuntu/index.html). macOS and BSD installation and property support differ, so use the guide for your OS.

- https://openzfs.github.io/openzfs-docs/
- https://openzfs.github.io/openzfs-docs/man/v2.2/8/zpool-create.8.html
- https://openzfs.github.io/openzfs-docs/man/v2.2/8/zfs-create.8.html
- https://docs.docker.com/storage/storagedriver/zfs-driver/
- https://www.ixsystems.com/blog/fast-dedup-is-a-valentines-gift-to-the-openzfs-and-truenas-communities/

> [!CAUTION]
> Creating a pool erases the selected disks. The two-disk example below creates a mirror; replace both `/dev/disk/by-id/...` placeholders with the persistent IDs of empty disks you intend to erase.

```bash
# Create a mirrored pool without forcing ZFS's safety checks.
sudo zpool create \
    -O mountpoint=none \
    -O compression=lz4 \
    -O dnodesize=auto \
    -O atime=off \
    -O xattr=sa \
    -O acltype=posixacl \
    -O aclinherit=passthrough \
    archivebox mirror \
    /dev/disk/by-id/DISK_ONE \
    /dev/disk/by-id/DISK_TWO

# Create the unencrypted ArchiveBox data dataset.
sudo zfs create \
    -o mountpoint=/mnt/archivebox/data \
    archivebox/data
```

To encrypt a new dataset, use this command **instead of** the unencrypted `zfs create` command above. ZFS encryption must be selected when the dataset is created.

```bash
sudo zfs create \
    -o mountpoint=/mnt/archivebox/data \
    -o encryption=on \
    -o keyformat=passphrase \
    -o keylocation=prompt \
    archivebox/data
```

<a name="ntfs"></a><a name="hfs"></a><a name="btrfs"></a>

### `NTFS`, `HFS+`, `BTRFS`

> [!WARNING]
> These filesystems are likely supported, but are not officially tested.

<a name="ext2"></a><a name="ext3"></a><a name="fat32"></a><a name="exfat"></a>

### `EXT2`, `EXT3`, `FAT32`, `exFAT`

> [!CAUTION]
> Not recommended. Cannot store files >4GB or more than 31k ~ 65k Snapshot entries due to directory entry limits.

<br/>

---

<br/>
<a name="remote-filesystems"></a>

## Supported Remote Filesystems

<img src="https://github.com/ArchiveBox/ArchiveBox/assets/511499/6124b92a-df5a-47c4-b3c2-006ebd28785b" alt="local filesystem icon" width="80px" align="right"/>

ArchiveBox supports many common types of remote filesystems using Rclone, FUSE, Docker storage providers, and Docker volume plugins.

The `data/archive/` subfolder contains the bulk archived content, and it supports being stored on a slower remote server (SMB/NFS/SFTP/etc.) or object store (S3/B2/R2/etc.). For data integrity and performance reasons, the rest of the `data/` directory (`data/ArchiveBox.conf`, `data/logs`, etc.) must be stored locally while ArchiveBox is running.

> [!IMPORTANT]
> `data/index.sqlite3` is your main archive DB, *it must be on a fast, reliable, local filesystem* which supports [FSYNC](https://stackoverflow.com/questions/40849596/git-clone-fsync-input-output-error-in-linux#:~:text=Some%20filesystems%20%2D%20especially%20remote%20filesystems%20like%20NFS%2C%20sshfs%2C&text=do%20not%20support%20fsync()%20but%20git%20has%20no%20flag%20to%20disable%20these%20calls) (SSD/NVMe recommended for best experience).

> [!TIP]
> If you use a remote filesystem, you should switch ArchiveBox's search backend from [`ripgrep`](https://github.com/ArchiveBox/ArchiveBox/wiki/Setting-up-Search#ripgrep) to [`sonic`](https://github.com/ArchiveBox/ArchiveBox/wiki/Setting-up-Search#sonic) (or [`FTS5`](https://github.com/ArchiveBox/ArchiveBox/wiki/Setting-up-Search#fts5)).  
> <sub>(`ripgrep` scans over every byte in the archive to do each search, which is **slow and potentially costly** on remote cloud storage)</sub>

<a name="nfs"></a>

### `NFS` (Docker Driver)

`docker-compose.yml`:
```yaml
services:
    archivebox:
        volumes:
            - ./data:/data
            - archivebox-archive:/data/archive

volumes:
    archivebox-archive:
        driver: local
        driver_opts:
            type: "nfs"
            o: "addr=some-remote-server.example.com,rw,nfsvers=4"
            device: ":/archivebox-archive"
```

<a name="smb"></a><a name="ceph"></a>

### `SMB` / `Ceph` (Docker CIFS Driver)

`docker-compose.yml`:
```yaml
services:
    archivebox:
        volumes:
            - ./data:/data
            - archivebox-archive:/data/archive

volumes:
    archivebox-archive:
        driver: local
        driver_opts:
            type: cifs
            device: "//some-remote-server.example.com/archivebox-archive"
            o: "username=XXX,password=YYY,uid=911,gid=911"
```

<br/>

<img src="https://github.com/ArchiveBox/ArchiveBox/assets/511499/0a159c27-5d54-46b9-814b-480f239ed27e" alt="local filesystem icon" height="80px" align="right"/><img src="https://github.com/ArchiveBox/ArchiveBox/assets/511499/5ca561b4-4597-401f-84b6-d53042fd7359" alt="local filesystem icon" height="80px" align="right"/>

<a name="s3"></a><a name="b2"></a><a name="gdrive"></a><a name="rclone"></a>

### Amazon S3 / Backblaze B2 / Google Drive / etc. (RClone)

ArchiveBox stores snapshot content under `data/archive/users/<user>/snapshots/<date>/<domain>/<uuid>/` and keeps backwards-compatible `data/archive/<timestamp>` symlinks. Object-storage mounts must enable Rclone's VFS symlink translation so both parts of this layout work.

Install the `rclone` binary through `abxpkg`:

```bash
uv tool install abxpkg
abxpkg install rclone
abxpkg run rclone version
```

Then install the FUSE 3 system integration supplied by your OS. For example, on Ubuntu:

```bash
sudo apt-get install fuse3
grep -qxF user_allow_other /etc/fuse.conf ||
    printf '%s\n' user_allow_other | sudo tee -a /etc/fuse.conf
```

Then define your remote storage config `~/.config/rclone/rclone.conf`:

> [!TIP]
> You can also create `rclone.conf` using the Rclone Web GUI: `abxpkg run rclone rcd --rc-web-gui`

```ini
# Example rclone.conf using Amazon S3 for storage:
[archivebox-s3]
type = s3
provider = AWS
access_key_id = XXX
secret_access_key = YYY
region = us-east-1
```

#### Rclone Config Examples

- [SMB](https://rclone.org/smb/) / [Ceph](https://rclone.org/s3/#ceph) / [SFTP](https://rclone.org/sftp/) / [FTP](https://rclone.org/ftp/) / [WebDAV (e.g. Nextcloud)](https://rclone.org/webdav/)
- [Google Drive](https://rclone.org/drive/) / [Dropbox](https://rclone.org/dropbox/) / [OneDrive](https://rclone.org/onedrive/)
- [Amazon S3](https://rclone.org/s3/#configuration) / [Backblaze B2](https://rclone.org/b2/) / [Cloudflare R2](https://rclone.org/s3/#cloudflare-r2) / [DigitalOcean Spaces](https://rclone.org/s3/#digitalocean-spaces)
- [Google Cloud Storage](https://rclone.org/s3/#google-cloud-storage) / [Azure Blob](https://rclone.org/azureblob/) / [Azure Files](https://rclone.org/azurefiles/)
- [Storj](https://rclone.org/s3/#storj) / [Sia](https://rclone.org/sia/) / [Archive.org Storage](https://rclone.org/internetarchive/)
- And many more...
  - https://rclone.org/s3/
  - https://rclone.org/overview/

*Bonus:*
- Set up gzip compression: https://rclone.org/compress/
- Set up file encryption: https://rclone.org/crypt/
- Set up hashing engine: https://rclone.org/hasher/

<br/>

#### Option A: Running Rclone on a bare-metal host

1. *If Needed:* Transfer any existing local archive data to the remote volume first

> [!CAUTION]
> Stop ArchiveBox before migrating its archive directory. `rclone sync` makes the remote destination match the local source and can delete files already present at the destination. Run it with `--dry-run` first, make a separate backup, and do not move the local copy until `rclone check` succeeds.

```bash
abxpkg run rclone sync \
    --dry-run \
    --links \
    --fast-list \
    --transfers 20 \
    --progress \
    /opt/archivebox/data/archive/ \
    archivebox-s3:data/archive/

# Remove --dry-run only after reviewing the proposed changes, then verify them.
abxpkg run rclone sync \
    --links \
    --fast-list \
    --transfers 20 \
    --progress \
    /opt/archivebox/data/archive/ \
    archivebox-s3:data/archive/
abxpkg run rclone check --links /opt/archivebox/data/archive/ archivebox-s3:data/archive/

mv /opt/archivebox/data/archive /opt/archivebox/data/archive.localbackup
mkdir -p /opt/archivebox/data/archive
```
2. **Mount the remote storage volume as FUSE filesystem**

Run the mount as the numeric user that owns the local ArchiveBox collection. The command stays in the foreground so a service manager can supervise it.

```bash
abxpkg run rclone mount \
    archivebox-s3:data/archive/ \
    /opt/archivebox/data/archive/ \
    --allow-other \
    --vfs-cache-mode=full \
    --vfs-links \
    --transfers=16 \
    --checkers=4
```

See [Rclone's `rclone mount` documentation](https://rclone.org/commands/rclone_mount/) for service-manager and cache-size configuration.

> [!TIP]
> You can use an existing Rclone FUSE mount as a normal Docker bind mount. A separate storage plugin is usually unnecessary when `user_allow_other` and `--allow-other` are configured correctly.

```bash
docker run --rm \
    -v "$PWD:/data" \
    -v /opt/archivebox/data/archive:/data/archive \
    archivebox/archivebox:dev status
```

`docker-compose.yml`:
```yaml
services:
    archivebox:
        # ...other service settings...
        volumes:
            - ./data:/data
            - /opt/archivebox/data/archive:/data/archive
```

<br/>

#### Option B: Running Rclone with the Docker storage plugin

*This Linux Docker Engine option is only needed if you cannot use Option A for compatibility or performance reasons, or if you prefer defining your remote storage in `docker-compose.yml`.*

See here for full instructions: [Rclone Documentation: Docker Plugin](https://rclone.org/docker/)

1. First, install the [Rclone Docker Volume Plugin](https://rclone.org/docker/#installing-as-managed-plugin) for your CPU architecture (e.g. `amd64` or `arm64`):

```bash
sudo mkdir -p \
    /var/lib/docker-plugins/rclone/config \
    /var/lib/docker-plugins/rclone/cache
sudo install -m 600 \
    ~/.config/rclone/rclone.conf \
    /var/lib/docker-plugins/rclone/config/rclone.conf

# Replace amd64 with arm64 on ARM hosts.
docker plugin install rclone/docker-volume-rclone:amd64 --grant-all-permissions --alias rclone
```

2. Then, [create a volume using the Docker CLI](https://rclone.org/docker/#creating-volumes-via-cli) or [define one using Docker Compose / Swarm](https://rclone.org/docker/#using-with-swarm-or-compose):

`docker-compose.yml`:
```yaml
services:
    archivebox:
        volumes:
            - ./data:/data
            - archivebox-s3:/data/archive

volumes:
    archivebox-s3:
        driver: rclone
        driver_opts:
            remote: 'archivebox-s3:data/archive'
            allow_other: 'true'
            vfs_cache_mode: full
            vfs_links: 'true'
            # Match these to the numeric owner of ./data; 911:911 is the image default.
            uid: 911
            gid: 911
            transfers: 16
            checkers: 4
```


To start the container and verify the filesystem is accessible within it:
```bash
docker compose run --rm archivebox \
    /bin/bash -c 'touch /data/archive/.write_test && rm /data/archive/.write_test'
```

<br/>
---
<br/>

### More Docker Storage Plugins

- [IPFS](https://github.com/djdv/go-filesystem-utils/pull/40) / [Peergos](https://github.com/peergos/peergos) / [GlusterFS](https://github.com/calavera/docker-volume-glusterfs)
- [DigitalOcean Block Storage Volumes](https://github.com/djmaze/dobs-volume-plugin) / [Linode Block Storage Volumes](https://github.com/linode/docker-volume-linode)
- [More volume plugins...](https://docs.docker.com/engine/extend/legacy_plugins/#volume-plugins)
