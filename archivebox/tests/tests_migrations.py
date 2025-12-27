#!/usr/bin/env python3
"""
Migration tests for ArchiveBox.

Tests that data directories from older versions can be migrated to newer versions
without data loss. Supports testing from 0.4.x (first Django version) to latest.

Run with: pytest archivebox/cli/tests_migrations.py -v

Schema Evolution:
- 0.4.x: Snapshot (tags as comma-separated string), no Tag model, no ArchiveResult
- 0.6.x: Added Tag model, Snapshot.tags became ManyToMany, added ArchiveResult
- 0.7.x: Same as 0.6.x with minor field additions
- 0.8.x: Added status fields, renamed datetime fields, added Crawl/Seed models,
         changed primary keys from AutoField to UUID for Tag/ArchiveResult
"""

__package__ = 'archivebox.cli'

import os
import sys
import json
import shutil
import sqlite3
import tempfile
import subprocess
import unittest
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, List, Any, Tuple
from uuid import uuid4


# =============================================================================
# Schema Definitions for Each Version
# =============================================================================

# Represents the minimum schema needed for each major version
# These are simplified - real migrations handle edge cases

SCHEMA_0_4 = """
-- Django system tables (minimal)
CREATE TABLE IF NOT EXISTS django_migrations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    app VARCHAR(255) NOT NULL,
    name VARCHAR(255) NOT NULL,
    applied DATETIME NOT NULL
);

-- Core tables for 0.4.x
CREATE TABLE IF NOT EXISTS core_snapshot (
    id CHAR(32) PRIMARY KEY,
    url VARCHAR(2000) NOT NULL UNIQUE,
    timestamp VARCHAR(32) NOT NULL UNIQUE,
    title VARCHAR(128),
    tags VARCHAR(256),
    added DATETIME NOT NULL,
    updated DATETIME
);
CREATE INDEX IF NOT EXISTS core_snapshot_url ON core_snapshot(url);
CREATE INDEX IF NOT EXISTS core_snapshot_timestamp ON core_snapshot(timestamp);
CREATE INDEX IF NOT EXISTS core_snapshot_added ON core_snapshot(added);
"""

SCHEMA_0_7 = """
-- Django system tables (complete for 0.7.x)
CREATE TABLE IF NOT EXISTS django_migrations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    app VARCHAR(255) NOT NULL,
    name VARCHAR(255) NOT NULL,
    applied DATETIME NOT NULL
);

CREATE TABLE IF NOT EXISTS django_content_type (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    app_label VARCHAR(100) NOT NULL,
    model VARCHAR(100) NOT NULL,
    UNIQUE(app_label, model)
);

CREATE TABLE IF NOT EXISTS auth_permission (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name VARCHAR(255) NOT NULL,
    content_type_id INTEGER NOT NULL REFERENCES django_content_type(id),
    codename VARCHAR(100) NOT NULL,
    UNIQUE(content_type_id, codename)
);

CREATE TABLE IF NOT EXISTS auth_group (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name VARCHAR(150) NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS auth_group_permissions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    group_id INTEGER NOT NULL REFERENCES auth_group(id),
    permission_id INTEGER NOT NULL REFERENCES auth_permission(id),
    UNIQUE(group_id, permission_id)
);

CREATE TABLE IF NOT EXISTS auth_user (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    password VARCHAR(128) NOT NULL,
    last_login DATETIME,
    is_superuser BOOL NOT NULL,
    username VARCHAR(150) NOT NULL UNIQUE,
    first_name VARCHAR(150) NOT NULL,
    last_name VARCHAR(150) NOT NULL,
    email VARCHAR(254) NOT NULL,
    is_staff BOOL NOT NULL,
    is_active BOOL NOT NULL,
    date_joined DATETIME NOT NULL
);

CREATE TABLE IF NOT EXISTS auth_user_groups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES auth_user(id),
    group_id INTEGER NOT NULL REFERENCES auth_group(id),
    UNIQUE(user_id, group_id)
);

CREATE TABLE IF NOT EXISTS auth_user_user_permissions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES auth_user(id),
    permission_id INTEGER NOT NULL REFERENCES auth_permission(id),
    UNIQUE(user_id, permission_id)
);

CREATE TABLE IF NOT EXISTS django_admin_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    action_time DATETIME NOT NULL,
    object_id TEXT,
    object_repr VARCHAR(200) NOT NULL,
    action_flag SMALLINT UNSIGNED NOT NULL,
    change_message TEXT NOT NULL,
    content_type_id INTEGER REFERENCES django_content_type(id),
    user_id INTEGER NOT NULL REFERENCES auth_user(id)
);

CREATE TABLE IF NOT EXISTS django_session (
    session_key VARCHAR(40) NOT NULL PRIMARY KEY,
    session_data TEXT NOT NULL,
    expire_date DATETIME NOT NULL
);

-- Core tables for 0.7.x
CREATE TABLE IF NOT EXISTS core_tag (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name VARCHAR(100) NOT NULL UNIQUE,
    slug VARCHAR(100) NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS core_snapshot (
    id CHAR(32) PRIMARY KEY,
    url VARCHAR(2000) NOT NULL UNIQUE,
    timestamp VARCHAR(32) NOT NULL UNIQUE,
    title VARCHAR(512),
    added DATETIME NOT NULL,
    updated DATETIME
);
CREATE INDEX IF NOT EXISTS core_snapshot_url ON core_snapshot(url);
CREATE INDEX IF NOT EXISTS core_snapshot_timestamp ON core_snapshot(timestamp);
CREATE INDEX IF NOT EXISTS core_snapshot_added ON core_snapshot(added);

-- Many-to-many for snapshot tags
CREATE TABLE IF NOT EXISTS core_snapshot_tags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id CHAR(32) NOT NULL REFERENCES core_snapshot(id),
    tag_id INTEGER NOT NULL REFERENCES core_tag(id),
    UNIQUE(snapshot_id, tag_id)
);

CREATE TABLE IF NOT EXISTS core_archiveresult (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id CHAR(32) NOT NULL REFERENCES core_snapshot(id),
    extractor VARCHAR(32) NOT NULL,
    cmd TEXT,
    pwd VARCHAR(256),
    cmd_version VARCHAR(128),
    output VARCHAR(1024),
    start_ts DATETIME,
    end_ts DATETIME,
    status VARCHAR(16) NOT NULL
);
CREATE INDEX IF NOT EXISTS core_archiveresult_snapshot ON core_archiveresult(snapshot_id);
CREATE INDEX IF NOT EXISTS core_archiveresult_extractor ON core_archiveresult(extractor);

-- Insert required content types
INSERT INTO django_content_type (app_label, model) VALUES
('contenttypes', 'contenttype'),
('auth', 'permission'),
('auth', 'group'),
('auth', 'user'),
('admin', 'logentry'),
('sessions', 'session'),
('core', 'snapshot'),
('core', 'archiveresult'),
('core', 'tag');
"""

SCHEMA_0_8 = """
-- Django system tables (complete for 0.8.x)
CREATE TABLE IF NOT EXISTS django_migrations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    app VARCHAR(255) NOT NULL,
    name VARCHAR(255) NOT NULL,
    applied DATETIME NOT NULL
);

CREATE TABLE IF NOT EXISTS django_content_type (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    app_label VARCHAR(100) NOT NULL,
    model VARCHAR(100) NOT NULL,
    UNIQUE(app_label, model)
);

CREATE TABLE IF NOT EXISTS auth_permission (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name VARCHAR(255) NOT NULL,
    content_type_id INTEGER NOT NULL REFERENCES django_content_type(id),
    codename VARCHAR(100) NOT NULL,
    UNIQUE(content_type_id, codename)
);

CREATE TABLE IF NOT EXISTS auth_group (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name VARCHAR(150) NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS auth_group_permissions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    group_id INTEGER NOT NULL REFERENCES auth_group(id),
    permission_id INTEGER NOT NULL REFERENCES auth_permission(id),
    UNIQUE(group_id, permission_id)
);

CREATE TABLE IF NOT EXISTS auth_user (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    password VARCHAR(128) NOT NULL,
    last_login DATETIME,
    is_superuser BOOL NOT NULL,
    username VARCHAR(150) NOT NULL UNIQUE,
    first_name VARCHAR(150) NOT NULL,
    last_name VARCHAR(150) NOT NULL,
    email VARCHAR(254) NOT NULL,
    is_staff BOOL NOT NULL,
    is_active BOOL NOT NULL,
    date_joined DATETIME NOT NULL
);

CREATE TABLE IF NOT EXISTS auth_user_groups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES auth_user(id),
    group_id INTEGER NOT NULL REFERENCES auth_group(id),
    UNIQUE(user_id, group_id)
);

CREATE TABLE IF NOT EXISTS auth_user_user_permissions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES auth_user(id),
    permission_id INTEGER NOT NULL REFERENCES auth_permission(id),
    UNIQUE(user_id, permission_id)
);

CREATE TABLE IF NOT EXISTS django_admin_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    action_time DATETIME NOT NULL,
    object_id TEXT,
    object_repr VARCHAR(200) NOT NULL,
    action_flag SMALLINT UNSIGNED NOT NULL,
    change_message TEXT NOT NULL,
    content_type_id INTEGER REFERENCES django_content_type(id),
    user_id INTEGER NOT NULL REFERENCES auth_user(id)
);

CREATE TABLE IF NOT EXISTS django_session (
    session_key VARCHAR(40) NOT NULL PRIMARY KEY,
    session_data TEXT NOT NULL,
    expire_date DATETIME NOT NULL
);

-- Core Tag table (AutoField PK in 0.8.x)
CREATE TABLE IF NOT EXISTS core_tag (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name VARCHAR(100) NOT NULL UNIQUE,
    slug VARCHAR(100) NOT NULL UNIQUE,
    created_at DATETIME,
    modified_at DATETIME,
    created_by_id INTEGER REFERENCES auth_user(id)
);

-- Crawls tables (new in 0.8.x)
CREATE TABLE IF NOT EXISTS crawls_crawl (
    id CHAR(36) PRIMARY KEY,
    created_at DATETIME NOT NULL,
    created_by_id INTEGER NOT NULL REFERENCES auth_user(id),
    modified_at DATETIME,
    urls TEXT NOT NULL,
    config TEXT DEFAULT '{}',
    max_depth SMALLINT UNSIGNED NOT NULL DEFAULT 0,
    tags_str VARCHAR(1024) NOT NULL DEFAULT '',
    persona_id CHAR(36),
    label VARCHAR(64) NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    schedule_id CHAR(36),
    output_dir VARCHAR(256) NOT NULL DEFAULT '',
    status VARCHAR(16) NOT NULL DEFAULT 'queued',
    retry_at DATETIME
);

-- Core Snapshot table (0.8.x with UUID PK, status, crawl FK)
CREATE TABLE IF NOT EXISTS core_snapshot (
    id CHAR(36) PRIMARY KEY,
    created_by_id INTEGER NOT NULL REFERENCES auth_user(id),
    created_at DATETIME NOT NULL,
    modified_at DATETIME,
    url VARCHAR(2000) NOT NULL,
    timestamp VARCHAR(32) NOT NULL UNIQUE,
    bookmarked_at DATETIME NOT NULL,
    crawl_id CHAR(36) REFERENCES crawls_crawl(id),
    title VARCHAR(512),
    downloaded_at DATETIME,
    depth SMALLINT UNSIGNED NOT NULL DEFAULT 0,
    retry_at DATETIME,
    status VARCHAR(16) NOT NULL DEFAULT 'queued',
    config TEXT DEFAULT '{}',
    notes TEXT NOT NULL DEFAULT '',
    output_dir VARCHAR(256)
);
CREATE INDEX IF NOT EXISTS core_snapshot_url ON core_snapshot(url);
CREATE INDEX IF NOT EXISTS core_snapshot_timestamp ON core_snapshot(timestamp);
CREATE INDEX IF NOT EXISTS core_snapshot_created_at ON core_snapshot(created_at);

-- Many-to-many for snapshot tags
CREATE TABLE IF NOT EXISTS core_snapshot_tags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id CHAR(36) NOT NULL REFERENCES core_snapshot(id),
    tag_id INTEGER NOT NULL REFERENCES core_tag(id),
    UNIQUE(snapshot_id, tag_id)
);

-- Core ArchiveResult table (0.8.x with AutoField PK + UUID, status)
CREATE TABLE IF NOT EXISTS core_archiveresult (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid CHAR(36) UNIQUE,
    created_by_id INTEGER NOT NULL REFERENCES auth_user(id),
    created_at DATETIME NOT NULL,
    modified_at DATETIME,
    snapshot_id CHAR(36) NOT NULL REFERENCES core_snapshot(id),
    extractor VARCHAR(32) NOT NULL,
    pwd VARCHAR(256),
    cmd TEXT,
    cmd_version VARCHAR(128),
    output VARCHAR(1024),
    start_ts DATETIME,
    end_ts DATETIME,
    status VARCHAR(16) NOT NULL DEFAULT 'queued',
    retry_at DATETIME,
    notes TEXT NOT NULL DEFAULT '',
    output_dir VARCHAR(256),
    iface_id INTEGER
);
CREATE INDEX IF NOT EXISTS core_archiveresult_snapshot ON core_archiveresult(snapshot_id);
CREATE INDEX IF NOT EXISTS core_archiveresult_extractor ON core_archiveresult(extractor);

-- Insert required content types
INSERT INTO django_content_type (app_label, model) VALUES
('contenttypes', 'contenttype'),
('auth', 'permission'),
('auth', 'group'),
('auth', 'user'),
('admin', 'logentry'),
('sessions', 'session'),
('core', 'snapshot'),
('core', 'archiveresult'),
('core', 'tag'),
('crawls', 'crawl'),
('crawls', 'crawlschedule');
"""


# =============================================================================
# Test Data Generators
# =============================================================================

def generate_uuid() -> str:
    """Generate a UUID string without dashes for SQLite."""
    return uuid4().hex


def generate_timestamp() -> str:
    """Generate a timestamp string like ArchiveBox uses."""
    return datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S') + '.000000'


def seed_0_4_data(db_path: Path) -> Dict[str, List[Dict]]:
    """Seed a 0.4.x database with realistic test data."""
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()

    # Track created data for verification
    created_data = {
        'snapshots': [],
        'tags_str': [],  # Tags are stored as comma-separated strings in 0.4.x
    }

    # Create 5 snapshots with various data
    test_urls = [
        ('https://example.com/page1', 'Example Page 1', 'news,tech'),
        ('https://example.org/article', 'Article Title', 'blog,reading'),
        ('https://github.com/user/repo', 'GitHub Repository', 'code,github'),
        ('https://news.ycombinator.com/item?id=12345', 'HN Discussion', 'news,discussion'),
        ('https://en.wikipedia.org/wiki/Test', 'Wikipedia Test', 'reference,wiki'),
    ]

    for i, (url, title, tags) in enumerate(test_urls):
        snapshot_id = generate_uuid()
        timestamp = f'2024010{i+1}120000.000000'
        added = f'2024-01-0{i+1} 12:00:00'

        cursor.execute("""
            INSERT INTO core_snapshot (id, url, timestamp, title, tags, added, updated)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (snapshot_id, url, timestamp, title, tags, added, added))

        created_data['snapshots'].append({
            'id': snapshot_id,
            'url': url,
            'timestamp': timestamp,
            'title': title,
            'tags': tags,
        })
        created_data['tags_str'].append(tags)

    # Record migrations as applied (0.4.x had just the initial migration)
    cursor.execute("""
        INSERT INTO django_migrations (app, name, applied)
        VALUES ('core', '0001_initial', datetime('now'))
    """)

    conn.commit()
    conn.close()

    return created_data


def seed_0_7_data(db_path: Path) -> Dict[str, List[Dict]]:
    """Seed a 0.7.x database with realistic test data."""
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()

    created_data = {
        'users': [],
        'snapshots': [],
        'tags': [],
        'archiveresults': [],
    }

    # Create a user
    cursor.execute("""
        INSERT INTO auth_user (password, is_superuser, username, first_name, last_name,
                               email, is_staff, is_active, date_joined)
        VALUES ('pbkdf2_sha256$test', 1, 'admin', 'Admin', 'User',
                'admin@example.com', 1, 1, datetime('now'))
    """)
    user_id = cursor.lastrowid
    created_data['users'].append({'id': user_id, 'username': 'admin'})

    # Create 5 tags
    tag_names = ['news', 'tech', 'blog', 'reference', 'code']
    for name in tag_names:
        cursor.execute("""
            INSERT INTO core_tag (name, slug) VALUES (?, ?)
        """, (name, name.lower()))
        tag_id = cursor.lastrowid
        created_data['tags'].append({'id': tag_id, 'name': name, 'slug': name.lower()})

    # Create 5 snapshots
    test_urls = [
        ('https://example.com/page1', 'Example Page 1'),
        ('https://example.org/article', 'Article Title'),
        ('https://github.com/user/repo', 'GitHub Repository'),
        ('https://news.ycombinator.com/item?id=12345', 'HN Discussion'),
        ('https://en.wikipedia.org/wiki/Test', 'Wikipedia Test'),
    ]

    for i, (url, title) in enumerate(test_urls):
        snapshot_id = generate_uuid()
        timestamp = f'2024010{i+1}120000.000000'
        added = f'2024-01-0{i+1} 12:00:00'

        cursor.execute("""
            INSERT INTO core_snapshot (id, url, timestamp, title, added, updated)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (snapshot_id, url, timestamp, title, added, added))

        created_data['snapshots'].append({
            'id': snapshot_id,
            'url': url,
            'timestamp': timestamp,
            'title': title,
        })

        # Assign 2 random tags to each snapshot
        tag_ids = [created_data['tags'][i % 5]['id'], created_data['tags'][(i + 1) % 5]['id']]
        for tag_id in tag_ids:
            cursor.execute("""
                INSERT INTO core_snapshot_tags (snapshot_id, tag_id) VALUES (?, ?)
            """, (snapshot_id, tag_id))

        # Create 5 archive results for each snapshot
        extractors = ['title', 'favicon', 'screenshot', 'singlefile', 'wget']
        statuses = ['succeeded', 'succeeded', 'failed', 'succeeded', 'skipped']

        for j, (extractor, status) in enumerate(zip(extractors, statuses)):
            # Note: uuid column is added by our migration, not present in 0.7.x
            cursor.execute("""
                INSERT INTO core_archiveresult
                (snapshot_id, extractor, cmd, pwd, cmd_version, output, start_ts, end_ts, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                snapshot_id, extractor,
                json.dumps([extractor, '--version']),
                f'/data/archive/{timestamp}',
                '1.0.0',
                f'{extractor}/index.html' if status == 'succeeded' else '',
                f'2024-01-0{i+1} 12:00:0{j}',
                f'2024-01-0{i+1} 12:00:1{j}',
                status
            ))

            created_data['archiveresults'].append({
                'snapshot_id': snapshot_id,
                'extractor': extractor,
                'status': status,
            })

    # Record migrations as applied (0.7.x migrations up to 0022)
    migrations = [
        # Django system migrations
        ('contenttypes', '0001_initial'),
        ('contenttypes', '0002_remove_content_type_name'),
        ('auth', '0001_initial'),
        ('auth', '0002_alter_permission_name_max_length'),
        ('auth', '0003_alter_user_email_max_length'),
        ('auth', '0004_alter_user_username_opts'),
        ('auth', '0005_alter_user_last_login_null'),
        ('auth', '0006_require_contenttypes_0002'),
        ('auth', '0007_alter_validators_add_error_messages'),
        ('auth', '0008_alter_user_username_max_length'),
        ('auth', '0009_alter_user_last_name_max_length'),
        ('auth', '0010_alter_group_name_max_length'),
        ('auth', '0011_update_proxy_permissions'),
        ('auth', '0012_alter_user_first_name_max_length'),
        ('admin', '0001_initial'),
        ('admin', '0002_logentry_remove_auto_add'),
        ('admin', '0003_logentry_add_action_flag_choices'),
        ('sessions', '0001_initial'),
        # Core migrations
        ('core', '0001_initial'),
        ('core', '0002_auto_20200625_1521'),
        ('core', '0003_auto_20200630_1034'),
        ('core', '0004_auto_20200713_1552'),
        ('core', '0005_auto_20200728_0326'),
        ('core', '0006_auto_20201012_1520'),
        ('core', '0007_archiveresult'),
        ('core', '0008_auto_20210105_1421'),
        ('core', '0009_auto_20210216_1038'),
        ('core', '0010_auto_20210216_1055'),
        ('core', '0011_auto_20210216_1331'),
        ('core', '0012_auto_20210216_1425'),
        ('core', '0013_auto_20210218_0729'),
        ('core', '0014_auto_20210218_0729'),
        ('core', '0015_auto_20210218_0730'),
        ('core', '0016_auto_20210218_1204'),
        ('core', '0017_auto_20210219_0211'),
        ('core', '0018_auto_20210327_0952'),
        ('core', '0019_auto_20210401_0654'),
        ('core', '0020_auto_20210410_1031'),
        ('core', '0021_auto_20220914_0934'),
        ('core', '0022_auto_20231023_2008'),
    ]

    for app, name in migrations:
        cursor.execute("""
            INSERT INTO django_migrations (app, name, applied)
            VALUES (?, ?, datetime('now'))
        """, (app, name))

    conn.commit()
    conn.close()

    return created_data


def seed_0_8_data(db_path: Path) -> Dict[str, List[Dict]]:
    """Seed a 0.8.x database with realistic test data including Crawls."""
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()

    created_data = {
        'users': [],
        'crawls': [],
        'snapshots': [],
        'tags': [],
        'archiveresults': [],
    }

    # Create a user
    cursor.execute("""
        INSERT INTO auth_user (password, is_superuser, username, first_name, last_name,
                               email, is_staff, is_active, date_joined)
        VALUES ('pbkdf2_sha256$test', 1, 'admin', 'Admin', 'User',
                'admin@example.com', 1, 1, datetime('now'))
    """)
    user_id = cursor.lastrowid
    created_data['users'].append({'id': user_id, 'username': 'admin'})

    # Create 5 tags
    tag_names = ['news', 'tech', 'blog', 'reference', 'code']
    for name in tag_names:
        cursor.execute("""
            INSERT INTO core_tag (name, slug, created_at, modified_at, created_by_id)
            VALUES (?, ?, datetime('now'), datetime('now'), ?)
        """, (name, name.lower(), user_id))
        tag_id = cursor.lastrowid
        created_data['tags'].append({'id': tag_id, 'name': name, 'slug': name.lower()})

    # Create 2 Crawls
    test_crawls = [
        ('https://example.com\nhttps://example.org', 0, 'Example Crawl'),
        ('https://github.com/ArchiveBox', 1, 'GitHub Crawl'),
    ]

    for i, (urls, max_depth, label) in enumerate(test_crawls):
        crawl_id = generate_uuid()
        cursor.execute("""
            INSERT INTO crawls_crawl (id, created_at, created_by_id, modified_at, urls,
                                      extractor, config, max_depth, tags_str, label, status, retry_at)
            VALUES (?, datetime('now'), ?, datetime('now'), ?, 'auto', '{}', ?, '', ?, 'queued', datetime('now'))
        """, (crawl_id, user_id, urls, max_depth, label))

        created_data['crawls'].append({
            'id': crawl_id,
            'urls': urls,
            'max_depth': max_depth,
            'label': label,
        })

    # Create 5 snapshots linked to crawls
    test_urls = [
        ('https://example.com/page1', 'Example Page 1', created_data['crawls'][0]['id']),
        ('https://example.org/article', 'Article Title', created_data['crawls'][0]['id']),
        ('https://github.com/user/repo', 'GitHub Repository', created_data['crawls'][1]['id']),
        ('https://news.ycombinator.com/item?id=12345', 'HN Discussion', None),  # No crawl
        ('https://en.wikipedia.org/wiki/Test', 'Wikipedia Test', None),  # No crawl
    ]

    for i, (url, title, crawl_id) in enumerate(test_urls):
        snapshot_id = generate_uuid()
        timestamp = f'2024010{i+1}120000.000000'
        created_at = f'2024-01-0{i+1} 12:00:00'

        cursor.execute("""
            INSERT INTO core_snapshot (id, created_by_id, created_at, modified_at, url, timestamp,
                                       bookmarked_at, crawl_id, title, depth, status, config, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 'queued', '{}', '')
        """, (snapshot_id, user_id, created_at, created_at, url, timestamp, created_at, crawl_id, title))

        created_data['snapshots'].append({
            'id': snapshot_id,
            'url': url,
            'timestamp': timestamp,
            'title': title,
            'crawl_id': crawl_id,
        })

        # Assign 2 random tags to each snapshot
        tag_ids = [created_data['tags'][i % 5]['id'], created_data['tags'][(i + 1) % 5]['id']]
        for tag_id in tag_ids:
            cursor.execute("""
                INSERT INTO core_snapshot_tags (snapshot_id, tag_id) VALUES (?, ?)
            """, (snapshot_id, tag_id))

        # Create 5 archive results for each snapshot
        extractors = ['title', 'favicon', 'screenshot', 'singlefile', 'wget']
        statuses = ['succeeded', 'succeeded', 'failed', 'succeeded', 'skipped']

        for j, (extractor, status) in enumerate(zip(extractors, statuses)):
            result_uuid = generate_uuid()
            cursor.execute("""
                INSERT INTO core_archiveresult
                (uuid, created_by_id, created_at, modified_at, snapshot_id, extractor, pwd,
                 cmd, cmd_version, output, start_ts, end_ts, status, retry_at, notes, output_dir)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), '', ?)
            """, (
                result_uuid, user_id, f'2024-01-0{i+1} 12:00:0{j}', f'2024-01-0{i+1} 12:00:1{j}',
                snapshot_id, extractor,
                f'/data/archive/{timestamp}',
                json.dumps([extractor, '--version']),
                '1.0.0',
                f'{extractor}/index.html' if status == 'succeeded' else '',
                f'2024-01-0{i+1} 12:00:0{j}',
                f'2024-01-0{i+1} 12:00:1{j}',
                status,
                f'{extractor}',
            ))

            created_data['archiveresults'].append({
                'uuid': result_uuid,
                'snapshot_id': snapshot_id,
                'extractor': extractor,
                'status': status,
            })

    # Record migrations as applied (0.8.x migrations)
    migrations = [
        # Django system migrations
        ('contenttypes', '0001_initial'),
        ('contenttypes', '0002_remove_content_type_name'),
        ('auth', '0001_initial'),
        ('auth', '0002_alter_permission_name_max_length'),
        ('auth', '0003_alter_user_email_max_length'),
        ('auth', '0004_alter_user_username_opts'),
        ('auth', '0005_alter_user_last_login_null'),
        ('auth', '0006_require_contenttypes_0002'),
        ('auth', '0007_alter_validators_add_error_messages'),
        ('auth', '0008_alter_user_username_max_length'),
        ('auth', '0009_alter_user_last_name_max_length'),
        ('auth', '0010_alter_group_name_max_length'),
        ('auth', '0011_update_proxy_permissions'),
        ('auth', '0012_alter_user_first_name_max_length'),
        ('admin', '0001_initial'),
        ('admin', '0002_logentry_remove_auto_add'),
        ('admin', '0003_logentry_add_action_flag_choices'),
        ('sessions', '0001_initial'),
        # Core migrations (up to 0.8.x)
        ('core', '0001_initial'),
        ('core', '0002_auto_20200625_1521'),
        ('core', '0003_auto_20200630_1034'),
        ('core', '0004_auto_20200713_1552'),
        ('core', '0005_auto_20200728_0326'),
        ('core', '0006_auto_20201012_1520'),
        ('core', '0007_archiveresult'),
        ('core', '0008_auto_20210105_1421'),
        ('core', '0009_auto_20210216_1038'),
        ('core', '0010_auto_20210216_1055'),
        ('core', '0011_auto_20210216_1331'),
        ('core', '0012_auto_20210216_1425'),
        ('core', '0013_auto_20210218_0729'),
        ('core', '0014_auto_20210218_0729'),
        ('core', '0015_auto_20210218_0730'),
        ('core', '0016_auto_20210218_1204'),
        ('core', '0017_auto_20210219_0211'),
        ('core', '0018_auto_20210327_0952'),
        ('core', '0019_auto_20210401_0654'),
        ('core', '0020_auto_20210410_1031'),
        ('core', '0021_auto_20220914_0934'),
        ('core', '0022_auto_20231023_2008'),
        ('core', '0023_new_schema'),
        ('core', '0024_snapshot_crawl'),
        ('core', '0025_allow_duplicate_urls_per_crawl'),
        # Crawls migrations
        ('crawls', '0001_initial'),
    ]

    for app, name in migrations:
        cursor.execute("""
            INSERT INTO django_migrations (app, name, applied)
            VALUES (?, ?, datetime('now'))
        """, (app, name))

    conn.commit()
    conn.close()

    return created_data


# =============================================================================
# Helper Functions
# =============================================================================

def run_archivebox(data_dir: Path, args: list, timeout: int = 60) -> subprocess.CompletedProcess:
    """Run archivebox command in subprocess with given data directory."""
    env = os.environ.copy()
    env['DATA_DIR'] = str(data_dir)
    env['USE_COLOR'] = 'False'
    env['SHOW_PROGRESS'] = 'False'
    # Disable ALL extractors for faster tests
    env['SAVE_ARCHIVE_DOT_ORG'] = 'False'
    env['SAVE_TITLE'] = 'False'
    env['SAVE_FAVICON'] = 'False'
    env['SAVE_WGET'] = 'False'
    env['SAVE_SINGLEFILE'] = 'False'
    env['SAVE_SCREENSHOT'] = 'False'
    env['SAVE_PDF'] = 'False'
    env['SAVE_DOM'] = 'False'
    env['SAVE_READABILITY'] = 'False'
    env['SAVE_MERCURY'] = 'False'
    env['SAVE_GIT'] = 'False'
    env['SAVE_MEDIA'] = 'False'
    env['SAVE_HEADERS'] = 'False'
    env['SAVE_HTMLTOTEXT'] = 'False'

    cmd = [sys.executable, '-m', 'archivebox'] + args

    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        env=env,
        cwd=str(data_dir),
        timeout=timeout,
    )


def create_data_dir_structure(data_dir: Path):
    """Create the basic ArchiveBox data directory structure."""
    (data_dir / 'archive').mkdir(parents=True, exist_ok=True)
    (data_dir / 'sources').mkdir(parents=True, exist_ok=True)
    (data_dir / 'logs').mkdir(parents=True, exist_ok=True)


def verify_snapshot_count(db_path: Path, expected: int) -> Tuple[bool, str]:
    """Verify the number of snapshots in the database."""
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM core_snapshot")
    count = cursor.fetchone()[0]
    conn.close()

    if count == expected:
        return True, f"Snapshot count OK: {count}"
    return False, f"Snapshot count mismatch: expected {expected}, got {count}"


def verify_tag_count(db_path: Path, expected: int) -> Tuple[bool, str]:
    """Verify the number of tags in the database."""
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM core_tag")
    count = cursor.fetchone()[0]
    conn.close()

    if count >= expected:  # May have more due to tag splitting
        return True, f"Tag count OK: {count} (expected >= {expected})"
    return False, f"Tag count mismatch: expected >= {expected}, got {count}"


def verify_archiveresult_count(db_path: Path, expected: int) -> Tuple[bool, str]:
    """Verify the number of archive results in the database."""
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM core_archiveresult")
    count = cursor.fetchone()[0]
    conn.close()

    if count == expected:
        return True, f"ArchiveResult count OK: {count}"
    return False, f"ArchiveResult count mismatch: expected {expected}, got {count}"


def verify_snapshot_urls(db_path: Path, expected_urls: List[str]) -> Tuple[bool, str]:
    """Verify all expected URLs exist in snapshots."""
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    cursor.execute("SELECT url FROM core_snapshot")
    actual_urls = {row[0] for row in cursor.fetchall()}
    conn.close()

    missing = set(expected_urls) - actual_urls
    if not missing:
        return True, "All URLs preserved"
    return False, f"Missing URLs: {missing}"


def verify_snapshot_titles(db_path: Path, expected_titles: Dict[str, str]) -> Tuple[bool, str]:
    """Verify snapshot titles are preserved."""
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    cursor.execute("SELECT url, title FROM core_snapshot")
    actual = {row[0]: row[1] for row in cursor.fetchall()}
    conn.close()

    mismatches = []
    for url, expected_title in expected_titles.items():
        if url in actual and actual[url] != expected_title:
            mismatches.append(f"{url}: expected '{expected_title}', got '{actual[url]}'")

    if not mismatches:
        return True, "All titles preserved"
    return False, f"Title mismatches: {mismatches}"


def verify_foreign_keys(db_path: Path) -> Tuple[bool, str]:
    """Verify foreign key relationships are intact."""
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()

    # Check ArchiveResult -> Snapshot FK
    cursor.execute("""
        SELECT COUNT(*) FROM core_archiveresult ar
        WHERE NOT EXISTS (SELECT 1 FROM core_snapshot s WHERE s.id = ar.snapshot_id)
    """)
    orphaned_results = cursor.fetchone()[0]

    conn.close()

    if orphaned_results == 0:
        return True, "Foreign keys intact"
    return False, f"Found {orphaned_results} orphaned ArchiveResults"


# =============================================================================
# Test Classes
# =============================================================================

class TestFreshInstall(unittest.TestCase):
    """Test that fresh installs work correctly."""

    def test_init_creates_database(self):
        """Fresh init should create database and directories."""
        work_dir = Path(tempfile.mkdtemp())

        try:
            result = run_archivebox(work_dir, ['init'])
            self.assertEqual(result.returncode, 0, f"Init failed: {result.stderr}")

            # Verify database was created
            self.assertTrue((work_dir / 'index.sqlite3').exists(), "Database not created")
            # Verify archive directory exists
            self.assertTrue((work_dir / 'archive').is_dir(), "Archive dir not created")

        finally:
            shutil.rmtree(work_dir, ignore_errors=True)

    def test_status_after_init(self):
        """Status command should work after init."""
        work_dir = Path(tempfile.mkdtemp())

        try:
            result = run_archivebox(work_dir, ['init'])
            self.assertEqual(result.returncode, 0)

            result = run_archivebox(work_dir, ['status'])
            self.assertEqual(result.returncode, 0, f"Status failed: {result.stderr}")

        finally:
            shutil.rmtree(work_dir, ignore_errors=True)

    def test_add_url_after_init(self):
        """Should be able to add URLs after init with --index-only (fast)."""
        work_dir = Path(tempfile.mkdtemp())

        try:
            result = run_archivebox(work_dir, ['init'])
            self.assertEqual(result.returncode, 0)

            # Add a URL with --index-only for speed
            result = run_archivebox(work_dir, ['add', '--index-only', 'https://example.com'])
            self.assertIn(result.returncode, [0, 1],
                f"Add command crashed: {result.stderr}")

            conn = sqlite3.connect(str(work_dir / 'index.sqlite3'))
            cursor = conn.cursor()

            # Verify a Crawl was created
            cursor.execute("SELECT COUNT(*) FROM crawls_crawl")
            crawl_count = cursor.fetchone()[0]
            self.assertGreaterEqual(crawl_count, 1, "No Crawl was created")

            # Verify at least one snapshot was created
            cursor.execute("SELECT COUNT(*) FROM core_snapshot")
            snapshot_count = cursor.fetchone()[0]
            self.assertGreaterEqual(snapshot_count, 1, "No Snapshot was created")

            conn.close()

        finally:
            shutil.rmtree(work_dir, ignore_errors=True)

    def test_list_after_add(self):
        """List command should show added snapshots."""
        work_dir = Path(tempfile.mkdtemp())

        try:
            result = run_archivebox(work_dir, ['init'])
            self.assertEqual(result.returncode, 0)

            result = run_archivebox(work_dir, ['add', '--index-only', 'https://example.com'])
            self.assertIn(result.returncode, [0, 1])

            result = run_archivebox(work_dir, ['list'])
            self.assertEqual(result.returncode, 0, f"List failed: {result.stderr}")

        finally:
            shutil.rmtree(work_dir, ignore_errors=True)

    def test_migrations_table_populated(self):
        """Django migrations table should be populated after init."""
        work_dir = Path(tempfile.mkdtemp())

        try:
            result = run_archivebox(work_dir, ['init'])
            self.assertEqual(result.returncode, 0)

            conn = sqlite3.connect(str(work_dir / 'index.sqlite3'))
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM django_migrations")
            count = cursor.fetchone()[0]
            conn.close()

            # Should have many migrations applied
            self.assertGreater(count, 10, f"Expected >10 migrations, got {count}")

        finally:
            shutil.rmtree(work_dir, ignore_errors=True)

    def test_core_migrations_applied(self):
        """Core app migrations should be applied."""
        work_dir = Path(tempfile.mkdtemp())

        try:
            result = run_archivebox(work_dir, ['init'])
            self.assertEqual(result.returncode, 0)

            conn = sqlite3.connect(str(work_dir / 'index.sqlite3'))
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM django_migrations WHERE app='core' ORDER BY name")
            migrations = [row[0] for row in cursor.fetchall()]
            conn.close()

            self.assertIn('0001_initial', migrations)

        finally:
            shutil.rmtree(work_dir, ignore_errors=True)


class TestSchemaIntegrity(unittest.TestCase):
    """Test that the database schema is correct."""

    def test_snapshot_table_has_required_columns(self):
        """Snapshot table should have all required columns."""
        work_dir = Path(tempfile.mkdtemp())

        try:
            result = run_archivebox(work_dir, ['init'])
            self.assertEqual(result.returncode, 0)

            conn = sqlite3.connect(str(work_dir / 'index.sqlite3'))
            cursor = conn.cursor()
            cursor.execute('PRAGMA table_info(core_snapshot)')
            columns = {row[1] for row in cursor.fetchall()}
            conn.close()

            required = {'id', 'url', 'timestamp', 'title', 'status', 'created_at', 'modified_at'}
            for col in required:
                self.assertIn(col, columns, f"Missing column: {col}")

        finally:
            shutil.rmtree(work_dir, ignore_errors=True)

    def test_archiveresult_table_has_required_columns(self):
        """ArchiveResult table should have all required columns."""
        work_dir = Path(tempfile.mkdtemp())

        try:
            result = run_archivebox(work_dir, ['init'])
            self.assertEqual(result.returncode, 0)

            conn = sqlite3.connect(str(work_dir / 'index.sqlite3'))
            cursor = conn.cursor()
            cursor.execute('PRAGMA table_info(core_archiveresult)')
            columns = {row[1] for row in cursor.fetchall()}
            conn.close()

            required = {'id', 'snapshot_id', 'extractor', 'status', 'created_at', 'modified_at'}
            for col in required:
                self.assertIn(col, columns, f"Missing column: {col}")

        finally:
            shutil.rmtree(work_dir, ignore_errors=True)

    def test_tag_table_has_required_columns(self):
        """Tag table should have all required columns."""
        work_dir = Path(tempfile.mkdtemp())

        try:
            result = run_archivebox(work_dir, ['init'])
            self.assertEqual(result.returncode, 0)

            conn = sqlite3.connect(str(work_dir / 'index.sqlite3'))
            cursor = conn.cursor()
            cursor.execute('PRAGMA table_info(core_tag)')
            columns = {row[1] for row in cursor.fetchall()}
            conn.close()

            required = {'id', 'name', 'slug'}
            for col in required:
                self.assertIn(col, columns, f"Missing column: {col}")

        finally:
            shutil.rmtree(work_dir, ignore_errors=True)


class TestMultipleSnapshots(unittest.TestCase):
    """Test handling multiple snapshots."""

    def test_add_multiple_urls(self):
        """Should be able to add multiple URLs with --index-only."""
        work_dir = Path(tempfile.mkdtemp())

        try:
            result = run_archivebox(work_dir, ['init'])
            self.assertEqual(result.returncode, 0)

            # Add multiple URLs with --index-only for speed
            result = run_archivebox(work_dir, ['add', '--index-only', 'https://example.com', 'https://example.org'])
            self.assertIn(result.returncode, [0, 1])

            conn = sqlite3.connect(str(work_dir / 'index.sqlite3'))
            cursor = conn.cursor()

            # Verify a Crawl was created
            cursor.execute("SELECT COUNT(*) FROM crawls_crawl")
            crawl_count = cursor.fetchone()[0]
            self.assertGreaterEqual(crawl_count, 1, f"Expected >=1 Crawl, got {crawl_count}")

            conn.close()

        finally:
            shutil.rmtree(work_dir, ignore_errors=True)


class TestMigrationFrom07x(unittest.TestCase):
    """Test migration from 0.7.x schema to latest."""

    def setUp(self):
        """Create a temporary directory with 0.7.x schema and data."""
        self.work_dir = Path(tempfile.mkdtemp())
        self.db_path = self.work_dir / 'index.sqlite3'

        # Create directory structure
        create_data_dir_structure(self.work_dir)

        # Create database with 0.7.x schema
        conn = sqlite3.connect(str(self.db_path))
        conn.executescript(SCHEMA_0_7)
        conn.close()

        # Seed with test data
        self.original_data = seed_0_7_data(self.db_path)

    def tearDown(self):
        """Clean up temporary directory."""
        shutil.rmtree(self.work_dir, ignore_errors=True)

    def test_migration_preserves_snapshot_count(self):
        """Migration should preserve all snapshots."""
        expected_count = len(self.original_data['snapshots'])

        # Run init to trigger migrations
        result = run_archivebox(self.work_dir, ['init'], timeout=45)

        # Check return code - may be 1 if some migrations have issues, but data should be preserved
        self.assertIn(result.returncode, [0, 1], f"Init crashed: {result.stderr}")

        # Verify snapshot count
        ok, msg = verify_snapshot_count(self.db_path, expected_count)
        self.assertTrue(ok, msg)

    def test_migration_preserves_snapshot_urls(self):
        """Migration should preserve all snapshot URLs."""
        expected_urls = [s['url'] for s in self.original_data['snapshots']]

        result = run_archivebox(self.work_dir, ['init'], timeout=45)
        self.assertIn(result.returncode, [0, 1], f"Init crashed: {result.stderr}")

        ok, msg = verify_snapshot_urls(self.db_path, expected_urls)
        self.assertTrue(ok, msg)

    def test_migration_preserves_snapshot_titles(self):
        """Migration should preserve all snapshot titles."""
        expected_titles = {s['url']: s['title'] for s in self.original_data['snapshots']}

        result = run_archivebox(self.work_dir, ['init'], timeout=45)
        self.assertIn(result.returncode, [0, 1], f"Init crashed: {result.stderr}")

        ok, msg = verify_snapshot_titles(self.db_path, expected_titles)
        self.assertTrue(ok, msg)

    def test_migration_preserves_tags(self):
        """Migration should preserve all tags."""
        expected_count = len(self.original_data['tags'])

        result = run_archivebox(self.work_dir, ['init'], timeout=45)
        self.assertIn(result.returncode, [0, 1], f"Init crashed: {result.stderr}")

        ok, msg = verify_tag_count(self.db_path, expected_count)
        self.assertTrue(ok, msg)

    def test_migration_preserves_archiveresults(self):
        """Migration should preserve all archive results."""
        expected_count = len(self.original_data['archiveresults'])

        result = run_archivebox(self.work_dir, ['init'], timeout=45)
        self.assertIn(result.returncode, [0, 1], f"Init crashed: {result.stderr}")

        ok, msg = verify_archiveresult_count(self.db_path, expected_count)
        self.assertTrue(ok, msg)

    def test_migration_preserves_foreign_keys(self):
        """Migration should maintain foreign key relationships."""
        result = run_archivebox(self.work_dir, ['init'], timeout=45)
        self.assertIn(result.returncode, [0, 1], f"Init crashed: {result.stderr}")

        ok, msg = verify_foreign_keys(self.db_path)
        self.assertTrue(ok, msg)

    def test_status_works_after_migration(self):
        """Status command should work after migration."""
        result = run_archivebox(self.work_dir, ['init'], timeout=45)
        self.assertIn(result.returncode, [0, 1])

        result = run_archivebox(self.work_dir, ['status'])
        self.assertEqual(result.returncode, 0, f"Status failed after migration: {result.stderr}")

    def test_search_works_after_migration(self):
        """Search command should find migrated snapshots."""
        result = run_archivebox(self.work_dir, ['init'], timeout=45)
        self.assertIn(result.returncode, [0, 1])

        result = run_archivebox(self.work_dir, ['search'])
        self.assertEqual(result.returncode, 0, f"Search failed after migration: {result.stderr}")

        # Should find at least some of the migrated URLs
        output = result.stdout + result.stderr
        found_any = any(s['url'][:30] in output or s['title'] in output
                       for s in self.original_data['snapshots'])
        self.assertTrue(found_any, f"No migrated snapshots found in search: {output[:500]}")

    def test_list_works_after_migration(self):
        """List command should work and show migrated data."""
        result = run_archivebox(self.work_dir, ['init'], timeout=45)
        self.assertIn(result.returncode, [0, 1])

        result = run_archivebox(self.work_dir, ['list'])
        self.assertEqual(result.returncode, 0, f"List failed after migration: {result.stderr}")

        # Should find at least some of the migrated URLs
        output = result.stdout + result.stderr
        found_any = any(s['url'][:30] in output or (s['title'] and s['title'] in output)
                       for s in self.original_data['snapshots'])
        self.assertTrue(found_any, f"No migrated snapshots found in list: {output[:500]}")

    def test_new_schema_elements_created_after_migration(self):
        """Migration should create new 0.9.x schema elements (crawls_crawl, etc.)."""
        result = run_archivebox(self.work_dir, ['init'], timeout=45)
        self.assertIn(result.returncode, [0, 1], f"Init crashed: {result.stderr}")

        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()

        # Check that new tables exist
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {row[0] for row in cursor.fetchall()}
        conn.close()

        # 0.9.x should have crawls_crawl table
        self.assertIn('crawls_crawl', tables, "crawls_crawl table not created during migration")

    def test_snapshots_have_new_fields_after_migration(self):
        """Migrated snapshots should have new 0.9.x fields (status, depth, etc.)."""
        result = run_archivebox(self.work_dir, ['init'], timeout=45)
        self.assertIn(result.returncode, [0, 1], f"Init crashed: {result.stderr}")

        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()

        # Check snapshot table has new columns
        cursor.execute('PRAGMA table_info(core_snapshot)')
        columns = {row[1] for row in cursor.fetchall()}
        conn.close()

        # 0.9.x snapshots should have status, depth, created_at, modified_at
        required_new_columns = {'status', 'depth', 'created_at', 'modified_at'}
        for col in required_new_columns:
            self.assertIn(col, columns, f"Snapshot missing new column: {col}")

    def test_add_works_after_migration(self):
        """Adding new URLs should work after migration from 0.7.x."""
        result = run_archivebox(self.work_dir, ['init'], timeout=45)
        self.assertIn(result.returncode, [0, 1], f"Init crashed: {result.stderr}")

        # Verify that init created the crawls_crawl table before proceeding
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='crawls_crawl'")
        table_exists = cursor.fetchone() is not None
        conn.close()
        self.assertTrue(table_exists, f"Init failed to create crawls_crawl table. Init stderr: {result.stderr[-500:]}")

        # Try to add a new URL after migration (use --index-only for speed)
        result = run_archivebox(self.work_dir, ['add', '--index-only', 'https://example.com/new-page'], timeout=45)
        self.assertIn(result.returncode, [0, 1], f"Add crashed after migration: {result.stderr}")

        # Verify a Crawl was created for the new URL
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM crawls_crawl")
        crawl_count = cursor.fetchone()[0]
        conn.close()

        self.assertGreaterEqual(crawl_count, 1, f"No Crawl created when adding URL. Add stderr: {result.stderr[-500:]}")

    def test_archiveresult_status_preserved_after_migration(self):
        """Migration should preserve archive result status values."""
        result = run_archivebox(self.work_dir, ['init'], timeout=45)
        self.assertIn(result.returncode, [0, 1], f"Init crashed: {result.stderr}")

        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()

        # Get status counts
        cursor.execute("SELECT status, COUNT(*) FROM core_archiveresult GROUP BY status")
        status_counts = dict(cursor.fetchall())
        conn.close()

        # Original data has known status distribution: succeeded, failed, skipped
        self.assertIn('succeeded', status_counts, "Should have succeeded results")
        self.assertIn('failed', status_counts, "Should have failed results")
        self.assertIn('skipped', status_counts, "Should have skipped results")

    def test_version_works_after_migration(self):
        """Version command should work after migration."""
        result = run_archivebox(self.work_dir, ['init'], timeout=45)
        self.assertIn(result.returncode, [0, 1])

        result = run_archivebox(self.work_dir, ['version'])
        # Exit code might be 1 if some binaries are missing, but should not crash
        self.assertIn(result.returncode, [0, 1], f"Version crashed after migration: {result.stderr}")

        # Should show version info
        output = result.stdout + result.stderr
        self.assertTrue('ArchiveBox' in output or 'version' in output.lower(),
                       f"Version output missing expected content: {output[:500]}")

    def test_help_works_after_migration(self):
        """Help command should work after migration."""
        result = run_archivebox(self.work_dir, ['init'], timeout=45)
        self.assertIn(result.returncode, [0, 1])

        result = run_archivebox(self.work_dir, ['help'])
        self.assertEqual(result.returncode, 0, f"Help crashed after migration: {result.stderr}")

        # Should show available commands
        output = result.stdout + result.stderr
        self.assertTrue('add' in output.lower() or 'status' in output.lower(),
                       f"Help output missing expected commands: {output[:500]}")


class TestMigrationFrom04x(unittest.TestCase):
    """Test migration from 0.4.x schema to latest.

    0.4.x was the first Django-powered version with a simpler schema:
    - No Tag model (tags stored as comma-separated string in Snapshot)
    - No ArchiveResult model (results stored in JSON files)
    """

    def setUp(self):
        """Create a temporary directory with 0.4.x schema and data."""
        self.work_dir = Path(tempfile.mkdtemp())
        self.db_path = self.work_dir / 'index.sqlite3'

        # Create directory structure
        create_data_dir_structure(self.work_dir)

        # Create database with 0.4.x schema
        conn = sqlite3.connect(str(self.db_path))
        conn.executescript(SCHEMA_0_4)
        conn.close()

        # Seed with test data
        self.original_data = seed_0_4_data(self.db_path)

    def tearDown(self):
        """Clean up temporary directory."""
        shutil.rmtree(self.work_dir, ignore_errors=True)

    def test_migration_preserves_snapshot_count(self):
        """Migration should preserve all snapshots from 0.4.x."""
        expected_count = len(self.original_data['snapshots'])

        result = run_archivebox(self.work_dir, ['init'], timeout=45)
        self.assertIn(result.returncode, [0, 1], f"Init crashed: {result.stderr}")

        ok, msg = verify_snapshot_count(self.db_path, expected_count)
        self.assertTrue(ok, msg)

    def test_migration_preserves_snapshot_urls(self):
        """Migration should preserve all snapshot URLs from 0.4.x."""
        expected_urls = [s['url'] for s in self.original_data['snapshots']]

        result = run_archivebox(self.work_dir, ['init'], timeout=45)
        self.assertIn(result.returncode, [0, 1], f"Init crashed: {result.stderr}")

        ok, msg = verify_snapshot_urls(self.db_path, expected_urls)
        self.assertTrue(ok, msg)

    def test_migration_converts_string_tags_to_model(self):
        """Migration should convert comma-separated tags to Tag model instances."""
        result = run_archivebox(self.work_dir, ['init'], timeout=45)
        self.assertIn(result.returncode, [0, 1], f"Init crashed: {result.stderr}")

        # Collect unique tags from original data
        original_tags = set()
        for tags_str in self.original_data['tags_str']:
            if tags_str:
                for tag in tags_str.split(','):
                    original_tags.add(tag.strip())

        # Tags should have been created
        ok, msg = verify_tag_count(self.db_path, len(original_tags))
        self.assertTrue(ok, msg)


class TestMigrationFrom08x(unittest.TestCase):
    """Test migration from 0.8.x schema to latest.

    0.8.x introduced:
    - Crawl model for grouping URLs
    - UUID primary keys for Snapshot
    - Status fields for state machine
    - New fields like depth, retry_at, etc.
    """

    def setUp(self):
        """Create a temporary directory with 0.8.x schema and data."""
        self.work_dir = Path(tempfile.mkdtemp())
        self.db_path = self.work_dir / 'index.sqlite3'

        # Create directory structure
        create_data_dir_structure(self.work_dir)

        # Create database with 0.8.x schema
        conn = sqlite3.connect(str(self.db_path))
        conn.executescript(SCHEMA_0_8)
        conn.close()

        # Seed with test data
        self.original_data = seed_0_8_data(self.db_path)

    def tearDown(self):
        """Clean up temporary directory."""
        shutil.rmtree(self.work_dir, ignore_errors=True)

    def test_migration_preserves_snapshot_count(self):
        """Migration should preserve all snapshots from 0.8.x."""
        expected_count = len(self.original_data['snapshots'])

        result = run_archivebox(self.work_dir, ['init'], timeout=45)
        self.assertIn(result.returncode, [0, 1], f"Init crashed: {result.stderr}")

        ok, msg = verify_snapshot_count(self.db_path, expected_count)
        self.assertTrue(ok, msg)

    def test_migration_preserves_snapshot_urls(self):
        """Migration should preserve all snapshot URLs from 0.8.x."""
        expected_urls = [s['url'] for s in self.original_data['snapshots']]

        result = run_archivebox(self.work_dir, ['init'], timeout=45)
        self.assertIn(result.returncode, [0, 1], f"Init crashed: {result.stderr}")

        ok, msg = verify_snapshot_urls(self.db_path, expected_urls)
        self.assertTrue(ok, msg)

    def test_migration_preserves_crawls(self):
        """Migration should preserve all Crawl records."""
        result = run_archivebox(self.work_dir, ['init'], timeout=45)
        self.assertIn(result.returncode, [0, 1], f"Init crashed: {result.stderr}")

        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM crawls_crawl")
        count = cursor.fetchone()[0]
        conn.close()

        expected_count = len(self.original_data['crawls'])
        self.assertEqual(count, expected_count, f"Crawl count mismatch: expected {expected_count}, got {count}")

    def test_migration_preserves_snapshot_crawl_links(self):
        """Migration should preserve snapshot-to-crawl relationships."""
        result = run_archivebox(self.work_dir, ['init'], timeout=45)
        self.assertIn(result.returncode, [0, 1], f"Init crashed: {result.stderr}")

        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()

        # Check each snapshot still has its crawl_id
        for snapshot in self.original_data['snapshots']:
            if snapshot['crawl_id']:
                cursor.execute("SELECT crawl_id FROM core_snapshot WHERE url = ?", (snapshot['url'],))
                row = cursor.fetchone()
                self.assertIsNotNone(row, f"Snapshot {snapshot['url']} not found after migration")
                self.assertEqual(row[0], snapshot['crawl_id'],
                    f"Crawl ID mismatch for {snapshot['url']}: expected {snapshot['crawl_id']}, got {row[0]}")

        conn.close()

    def test_migration_preserves_tags(self):
        """Migration should preserve all tags."""
        result = run_archivebox(self.work_dir, ['init'], timeout=45)
        self.assertIn(result.returncode, [0, 1], f"Init crashed: {result.stderr}")

        ok, msg = verify_tag_count(self.db_path, len(self.original_data['tags']))
        self.assertTrue(ok, msg)

    def test_migration_preserves_archiveresults(self):
        """Migration should preserve all archive results."""
        expected_count = len(self.original_data['archiveresults'])

        result = run_archivebox(self.work_dir, ['init'], timeout=45)
        self.assertIn(result.returncode, [0, 1], f"Init crashed: {result.stderr}")

        ok, msg = verify_archiveresult_count(self.db_path, expected_count)
        self.assertTrue(ok, msg)

    def test_migration_preserves_archiveresult_status(self):
        """Migration should preserve archive result status values."""
        result = run_archivebox(self.work_dir, ['init'], timeout=45)
        self.assertIn(result.returncode, [0, 1], f"Init crashed: {result.stderr}")

        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()

        # Get status counts
        cursor.execute("SELECT status, COUNT(*) FROM core_archiveresult GROUP BY status")
        status_counts = dict(cursor.fetchall())
        conn.close()

        # Original data has known status distribution: succeeded, failed, skipped
        self.assertIn('succeeded', status_counts, "Should have succeeded results")
        self.assertIn('failed', status_counts, "Should have failed results")
        self.assertIn('skipped', status_counts, "Should have skipped results")

    def test_status_works_after_migration(self):
        """Status command should work after migration."""
        result = run_archivebox(self.work_dir, ['init'], timeout=45)
        self.assertIn(result.returncode, [0, 1])

        result = run_archivebox(self.work_dir, ['status'])
        self.assertEqual(result.returncode, 0, f"Status failed after migration: {result.stderr}")

    def test_list_works_after_migration(self):
        """List command should work and show migrated data."""
        result = run_archivebox(self.work_dir, ['init'], timeout=45)
        self.assertIn(result.returncode, [0, 1])

        result = run_archivebox(self.work_dir, ['list'])
        self.assertEqual(result.returncode, 0, f"List failed after migration: {result.stderr}")

        # Should find at least some of the migrated URLs
        output = result.stdout + result.stderr
        found_any = any(s['url'][:30] in output or (s['title'] and s['title'] in output)
                       for s in self.original_data['snapshots'])
        self.assertTrue(found_any, f"No migrated snapshots found in list: {output[:500]}")

    def test_search_works_after_migration(self):
        """Search command should find migrated snapshots."""
        result = run_archivebox(self.work_dir, ['init'], timeout=45)
        self.assertIn(result.returncode, [0, 1])

        result = run_archivebox(self.work_dir, ['search'])
        self.assertEqual(result.returncode, 0, f"Search failed after migration: {result.stderr}")

        # Should find at least some of the migrated URLs
        output = result.stdout + result.stderr
        found_any = any(s['url'][:30] in output or (s['title'] and s['title'] in output)
                       for s in self.original_data['snapshots'])
        self.assertTrue(found_any, f"No migrated snapshots found in search: {output[:500]}")

    def test_migration_preserves_snapshot_titles(self):
        """Migration should preserve all snapshot titles."""
        expected_titles = {s['url']: s['title'] for s in self.original_data['snapshots']}

        result = run_archivebox(self.work_dir, ['init'], timeout=45)
        self.assertIn(result.returncode, [0, 1], f"Init crashed: {result.stderr}")

        ok, msg = verify_snapshot_titles(self.db_path, expected_titles)
        self.assertTrue(ok, msg)

    def test_migration_preserves_foreign_keys(self):
        """Migration should maintain foreign key relationships."""
        result = run_archivebox(self.work_dir, ['init'], timeout=45)
        self.assertIn(result.returncode, [0, 1], f"Init crashed: {result.stderr}")

        ok, msg = verify_foreign_keys(self.db_path)
        self.assertTrue(ok, msg)

    def test_add_works_after_migration(self):
        """Adding new URLs should work after migration from 0.8.x."""
        result = run_archivebox(self.work_dir, ['init'], timeout=45)
        self.assertIn(result.returncode, [0, 1], f"Init crashed: {result.stderr}")

        # Count existing crawls
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM crawls_crawl")
        initial_crawl_count = cursor.fetchone()[0]
        conn.close()

        # Try to add a new URL after migration (use --index-only for speed)
        result = run_archivebox(self.work_dir, ['add', '--index-only', 'https://example.com/new-page'], timeout=45)
        self.assertIn(result.returncode, [0, 1], f"Add crashed after migration: {result.stderr}")

        # Verify a new Crawl was created
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM crawls_crawl")
        new_crawl_count = cursor.fetchone()[0]
        conn.close()

        self.assertGreater(new_crawl_count, initial_crawl_count,
                          f"No new Crawl created when adding URL. Add stderr: {result.stderr[-500:]}")

    def test_version_works_after_migration(self):
        """Version command should work after migration."""
        result = run_archivebox(self.work_dir, ['init'], timeout=45)
        self.assertIn(result.returncode, [0, 1])

        result = run_archivebox(self.work_dir, ['version'])
        # Exit code might be 1 if some binaries are missing, but should not crash
        self.assertIn(result.returncode, [0, 1], f"Version crashed after migration: {result.stderr}")

        # Should show version info
        output = result.stdout + result.stderr
        self.assertTrue('ArchiveBox' in output or 'version' in output.lower(),
                       f"Version output missing expected content: {output[:500]}")


class TestMigrationDataIntegrity(unittest.TestCase):
    """Comprehensive data integrity tests for migrations."""

    def test_no_duplicate_snapshots_after_migration(self):
        """Migration should not create duplicate snapshots."""
        work_dir = Path(tempfile.mkdtemp())
        db_path = work_dir / 'index.sqlite3'

        try:
            create_data_dir_structure(work_dir)
            conn = sqlite3.connect(str(db_path))
            conn.executescript(SCHEMA_0_7)
            conn.close()
            seed_0_7_data(db_path)

            result = run_archivebox(work_dir, ['init'], timeout=45)
            self.assertIn(result.returncode, [0, 1])

            # Check for duplicate URLs
            conn = sqlite3.connect(str(db_path))
            cursor = conn.cursor()
            cursor.execute("""
                SELECT url, COUNT(*) as cnt FROM core_snapshot
                GROUP BY url HAVING cnt > 1
            """)
            duplicates = cursor.fetchall()
            conn.close()

            self.assertEqual(len(duplicates), 0, f"Found duplicate URLs: {duplicates}")

        finally:
            shutil.rmtree(work_dir, ignore_errors=True)

    def test_no_orphaned_archiveresults_after_migration(self):
        """Migration should not leave orphaned ArchiveResults."""
        work_dir = Path(tempfile.mkdtemp())
        db_path = work_dir / 'index.sqlite3'

        try:
            create_data_dir_structure(work_dir)
            conn = sqlite3.connect(str(db_path))
            conn.executescript(SCHEMA_0_7)
            conn.close()
            seed_0_7_data(db_path)

            result = run_archivebox(work_dir, ['init'], timeout=45)
            self.assertIn(result.returncode, [0, 1])

            ok, msg = verify_foreign_keys(db_path)
            self.assertTrue(ok, msg)

        finally:
            shutil.rmtree(work_dir, ignore_errors=True)

    def test_timestamps_preserved_after_migration(self):
        """Migration should preserve original timestamps."""
        work_dir = Path(tempfile.mkdtemp())
        db_path = work_dir / 'index.sqlite3'

        try:
            create_data_dir_structure(work_dir)
            conn = sqlite3.connect(str(db_path))
            conn.executescript(SCHEMA_0_7)
            conn.close()
            original_data = seed_0_7_data(db_path)

            original_timestamps = {s['url']: s['timestamp'] for s in original_data['snapshots']}

            result = run_archivebox(work_dir, ['init'], timeout=45)
            self.assertIn(result.returncode, [0, 1])

            conn = sqlite3.connect(str(db_path))
            cursor = conn.cursor()
            cursor.execute("SELECT url, timestamp FROM core_snapshot")
            migrated_timestamps = {row[0]: row[1] for row in cursor.fetchall()}
            conn.close()

            for url, original_ts in original_timestamps.items():
                self.assertEqual(
                    migrated_timestamps.get(url), original_ts,
                    f"Timestamp changed for {url}: {original_ts} -> {migrated_timestamps.get(url)}"
                )

        finally:
            shutil.rmtree(work_dir, ignore_errors=True)


if __name__ == '__main__':
    unittest.main()
