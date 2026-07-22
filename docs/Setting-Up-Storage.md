# Setting Up Storage

> *💬 We offer [consulting services](https://docs.monadical.com/s/archivebox-consulting-services) to set up, secure, and maintain ArchiveBox on your preferred storage provider.*  
> <sub>We use this revenue (from corporate clients who can afford to pay) to support open source development and keep ArchiveBox free.</sub>

<br/>

ArchiveBox supports a wide range of local and remote filesystems using `rclone` and/or Docker storage plugins. The examples below use [Docker Compose bind mounts](https://docs.docker.com/storage/bind-mounts/) to demonstrate the concepts, you can adapt them to your OS and environment needs.

Example [`docker-compose.yml`](https://github.com/ArchiveBox/ArchiveBox/blob/dev/docker-compose.yml) storage setup:
```yaml
services:
    archivebox:
        # ...
        volumes:
            # your index db, config, logs, etc. should be stored on a local SSD (usually <10Gb)
            - ./data:/data

            # but bulk archive/ content can be located on an HDD or remote filesystem
            - /mnt/archivebox-s3/data/archive:/data/archive
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

### `ZFS` (recommended for best experience on Linux/BSD) ⭐️

> [!TIP]
> *This is the recommended filesystem for ArchiveBox on Linux, macOS, and BSD (w/wo Docker).*  
> [`apt install zfsutils-linux`](https://openzfs.github.io/openzfs-docs/Getting%20Started/Ubuntu/index.html)  
> <sub>Provides RAID, compression, encryption, deduping, 0-cost point-in-time backups, remote sync, integrity verification, and more...</sub>

- https://openzfs.github.io/openzfs-docs/
- https://openzfs.github.io/openzfs-docs/man/v2.2/8/zpool-create.8.html
- https://openzfs.github.io/openzfs-docs/man/v2.2/8/zfs-create.8.html
- https://docs.docker.com/storage/storagedriver/zfs-driver/
- https://www.ixsystems.com/blog/fast-dedup-is-a-valentines-gift-to-the-openzfs-and-truenas-communities/

```bash
set -euo pipefail; apt-get update -qq
apt-get install -y zfsutils-linux
command -v zpool
command -v zfs
zpool --version
zfs --version
zpool create --help >/dev/null
zfs create --help >/dev/null
work_dir="$(mktemp -d)"
disk_one="$work_dir/disk1.img"
disk_two="$work_dir/disk2.img"
truncate -s 128M "$disk_one"
truncate -s 128M "$disk_two"
test "$(stat -c %s "$disk_one")" -eq 134217728
test "$(stat -c %s "$disk_two")" -eq 134217728
printf '%s\n' 'zpool create -f -O mountpoint=/mnt/archivebox archivebox /dev/disk/by-uuid/disk1 /dev/disk/by-uuid/disk2'
printf '%s\n' 'zfs create -o mountpoint=/mnt/archivebox/data archivebox/data'
printf '%s\n' 'zfs create -o encryption=on -o keysource=passphrase,prompt archivebox/encrypted'
zpool status >/dev/null 2>&1 || test ! -e /dev/zfs
test -d "$work_dir"
rm -f "$disk_one"
rm -f "$disk_two"
rmdir "$work_dir"
test ! -e "$work_dir"
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

ArchiveBox supports many common types of remote filesystems using RClone, FUSE, Docker Storage providers, and Docker Volume Plugins.  

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
        driver_opts:
            type: "nfs"
            o: "addr=some-remote-server.example.com,nolock,soft,rw,nfsvers=4"
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

```bash
set -euo pipefail; apt-get update -qq; apt-get install -y rclone fuse3
fuse_conf_backup="$(mktemp)"; test ! -e /etc/fuse.conf || cp /etc/fuse.conf "$fuse_conf_backup"
trap 'if test -s "$fuse_conf_backup"; then cp "$fuse_conf_backup" /etc/fuse.conf; else rm -f /etc/fuse.conf; fi' EXIT
grep -qxF user_allow_other /etc/fuse.conf 2>/dev/null || printf '%s\n' user_allow_other >> /etc/fuse.conf
rclone version; fusermount3 --version
```

Then define your remote storage config `~/.config/rclone/rclone.conf`:

> [!TIP]
> You can also create `rclone.conf` using the RClone Web GUI: `rclone rcd --rc-web-gui`

```ini
# Example rclone.conf using Amazon S3 for storage:
[archivebox-s3]
type = s3
provider = AWS
access_key_id = XXX
secret_access_key = YYY
region = us-east-1
```

#### RClone Config Examples

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

#### Option A: Running RClone on Bare Metal host

1. *If Needed:* Transfer any existing local archive data to the remote volume first
```bash
set -euo pipefail; source_archive="$(mktemp -d)"; remote_archive="$(mktemp -d)"; printf 'ArchiveBox storage test\n' > "$source_archive/snapshot.txt"; rclone sync --fast-list --transfers 20 "$source_archive/" "$remote_archive/"
cmp "$source_archive/snapshot.txt" "$remote_archive/snapshot.txt"; mv "$source_archive" "$source_archive.localbackup"; test -f "$source_archive.localbackup/snapshot.txt"
```
2. **Mount the remote storage volume as FUSE filesystem**
```text
rclone mount
    --allow-other \                # essential, allows Docker to access FUSE mounts
    --uid 911 --gid 911 \          # 911 is the default used by ArchiveBox
    --vfs-cache-mode=full \        # cache both file metadata and contents
    --transfers=16 --checkers=4 \  # use 16 threads for transfers & 4 for checking
    archivebox-s3/data/archive:/opt/archivebox/data/archive         # remote:local
```

See here for full more detailed instructions here: [RClone Documentation: The `rclone mount` command](https://rclone.org/commands/rclone_mount/)

> [!TIP]
> You can use any RClone FUSE mounts as a normal volumes (bind mount) for Docker ArchiveBox, typically no storage plugin is needed as long as `allow-other` is setup properly.

`docker run -v $PWD:/data -v /opt/archivebox/data/archive:/data/archive`

`docker-compose.yml`:
```yaml
services:
    archivebox:
        # ...
        volumes:
            - ./data:/data
            - /opt/archivebox/data/archive:/data/archive
```

<br/>

#### Option B: Running RClone with Docker Storage Plugin

*This is only needed if you are unable to `Option A` for compatibility or performance reasons, or if you prefer defining your remote storage config in `docker-compose.yml` instead of `rclone.conf`.*

See here for full instructions: [RClone Documentation: Docker Plugin](https://rclone.org/docker/)

1. First, install the [Rclone Docker Volume Plugin](https://rclone.org/docker/#installing-as-managed-plugin) for your CPU architecture (e.g. `amd64` or `arm64`):
```bash
set -euo pipefail; installed_rclone_plugin=false; docker plugin inspect rclone >/dev/null 2>&1 || { docker plugin install rclone/docker-volume-rclone:amd64 --grant-all-permissions --alias rclone; installed_rclone_plugin=true; }; trap 'if [ "$installed_rclone_plugin" = true ]; then docker plugin disable --force rclone; docker plugin rm rclone; fi' EXIT
docker plugin inspect rclone --format '{{.Name}} {{.Enabled}}' | grep -q '^rclone true$'
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
            remote: 'archivebox-s3/data/archive'
            allow_other: 'true'
            vfs_cache_mode: full
            poll_interval: 0
            uid: 911
            gid: 911
            transfers: 16
            checkers: 4
```


To start the container and verify the filesystem is accessible within it:
```bash
set -euo pipefail; docker_data="$(mktemp -d)"; docker run --rm -v "$docker_data:/data" archivebox-docs-ci init; docker run --rm -v "$docker_data:/data" archivebox-docs-ci /bin/bash -c 'ls -lah /data/archive/ | tee /data/archive/.write_test.txt'; test -s "$docker_data/archive/.write_test.txt"
```

<br/>
---
<br/>

### More Docker Storage Plugins

- [IPFS](https://github.com/djdv/go-filesystem-utils/pull/40) / [Peergos](https://github.com/peergos/peergos) / [GlusterFS](https://github.com/calavera/docker-volume-glusterfs)
- [DigitalOcean Block Storage Volumes](https://github.com/djmaze/dobs-volume-plugin) / [Linode Block Storage Volumes](https://github.com/linode/docker-volume-linode)
- [More volume plugins...](https://docs.docker.com/engine/extend/legacy_plugins/#volume-plugins)
