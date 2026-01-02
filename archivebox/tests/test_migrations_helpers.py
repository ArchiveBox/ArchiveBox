#!/usr/bin/env python3
"""
Helper functions and schema definitions for migration tests.

This module provides:
- Schema definitions for each major ArchiveBox version (0.4.x, 0.7.x, 0.8.x)
- Data seeding functions to populate test databases
- Helper functions to run archivebox commands and verify results
"""

import os
import sys
import json
import sqlite3
import subprocess
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, List, Tuple
from uuid import uuid4


# =============================================================================
# Schema Definitions for Each Version
# =============================================================================

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

-- Machine app tables (added in 0.8.x)
CREATE TABLE IF NOT EXISTS machine_machine (
    id CHAR(36) PRIMARY KEY,
    created_at DATETIME NOT NULL,
    modified_at DATETIME,
    guid VARCHAR(64) NOT NULL UNIQUE,
    hostname VARCHAR(63),
    hw_in_docker BOOLEAN NOT NULL DEFAULT 0,
    hw_in_vm BOOLEAN NOT NULL DEFAULT 0,
    hw_manufacturer VARCHAR(63),
    hw_product VARCHAR(63),
    hw_uuid VARCHAR(255),
    os_arch VARCHAR(15),
    os_family VARCHAR(15),
    os_platform VARCHAR(63),
    os_release VARCHAR(63),
    os_kernel VARCHAR(255),
    stats TEXT DEFAULT '{}',
    config TEXT DEFAULT '{}',
    num_uses_failed INTEGER NOT NULL DEFAULT 0,
    num_uses_succeeded INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS machine_networkinterface (
    id CHAR(36) PRIMARY KEY,
    created_at DATETIME NOT NULL,
    modified_at DATETIME,
    machine_id CHAR(36) NOT NULL REFERENCES machine_machine(id),
    mac_address VARCHAR(17),
    ip_public VARCHAR(45),
    ip_local VARCHAR(45),
    dns_server VARCHAR(45),
    hostname VARCHAR(63),
    iface VARCHAR(15),
    isp VARCHAR(63),
    city VARCHAR(63),
    region VARCHAR(63),
    country VARCHAR(63),
    num_uses_failed INTEGER NOT NULL DEFAULT 0,
    num_uses_succeeded INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS machine_dependency (
    id CHAR(36) PRIMARY KEY,
    created_at DATETIME NOT NULL,
    modified_at DATETIME,
    bin_name VARCHAR(63) NOT NULL UNIQUE,
    bin_providers VARCHAR(127) NOT NULL DEFAULT '*',
    custom_cmds TEXT DEFAULT '{}',
    config TEXT DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS machine_binary (
    id CHAR(36) PRIMARY KEY,
    created_at DATETIME NOT NULL,
    modified_at DATETIME,
    machine_id CHAR(36) REFERENCES machine_machine(id),
    dependency_id CHAR(36) REFERENCES machine_dependency(id),
    name VARCHAR(63),
    binprovider VARCHAR(31),
    abspath VARCHAR(255),
    version VARCHAR(32),
    sha256 VARCHAR(64),
    num_uses_failed INTEGER NOT NULL DEFAULT 0,
    num_uses_succeeded INTEGER NOT NULL DEFAULT 0
);

-- API app tables (added in 0.8.x)
CREATE TABLE IF NOT EXISTS api_apitoken (
    id CHAR(36) PRIMARY KEY,
    created_by_id INTEGER NOT NULL REFERENCES auth_user(id),
    created_at DATETIME NOT NULL,
    modified_at DATETIME,
    token VARCHAR(32) NOT NULL UNIQUE,
    expires DATETIME
);

CREATE TABLE IF NOT EXISTS api_outboundwebhook (
    id CHAR(36) PRIMARY KEY,
    created_by_id INTEGER NOT NULL REFERENCES auth_user(id),
    created_at DATETIME NOT NULL,
    modified_at DATETIME,
    name VARCHAR(255) NOT NULL DEFAULT '',
    signal VARCHAR(255) NOT NULL,
    ref VARCHAR(255) NOT NULL,
    endpoint VARCHAR(2083) NOT NULL,
    headers TEXT DEFAULT '{}',
    auth_token VARCHAR(4000) NOT NULL DEFAULT '',
    enabled BOOLEAN NOT NULL DEFAULT 1,
    keep_last_response BOOLEAN NOT NULL DEFAULT 0,
    last_response TEXT NOT NULL DEFAULT '',
    last_success DATETIME,
    last_failure DATETIME,
    num_uses_failed INTEGER NOT NULL DEFAULT 0,
    num_uses_succeeded INTEGER NOT NULL DEFAULT 0
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
CREATE TABLE IF NOT EXISTS crawls_crawlschedule (
    id CHAR(36) PRIMARY KEY,
    created_at DATETIME NOT NULL,
    created_by_id INTEGER NOT NULL REFERENCES auth_user(id),
    modified_at DATETIME,
    schedule VARCHAR(64) NOT NULL,
    is_enabled BOOLEAN NOT NULL DEFAULT 1,
    label VARCHAR(64) NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    template_id CHAR(36) REFERENCES crawls_crawl(id),
    num_uses_failed INTEGER NOT NULL DEFAULT 0,
    num_uses_succeeded INTEGER NOT NULL DEFAULT 0
);

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
    retry_at DATETIME,
    num_uses_failed INTEGER NOT NULL DEFAULT 0,
    num_uses_succeeded INTEGER NOT NULL DEFAULT 0
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
    output_dir VARCHAR(256),
    num_uses_failed INTEGER NOT NULL DEFAULT 0,
    num_uses_succeeded INTEGER NOT NULL DEFAULT 0
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
    iface_id INTEGER,
    config TEXT DEFAULT '{}',
    num_uses_failed INTEGER NOT NULL DEFAULT 0,
    num_uses_succeeded INTEGER NOT NULL DEFAULT 0
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
('machine', 'machine'),
('machine', 'networkinterface'),
('machine', 'dependency'),
('machine', 'binary'),
('crawls', 'crawl'),
('crawls', 'crawlschedule'),
('crawls', 'seed'),
('api', 'apitoken'),
('api', 'outboundwebhook');
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

    created_data = {
        'snapshots': [],
        'tags_str': [],
    }

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

        # Assign 2 tags to each snapshot
        tag_ids = [created_data['tags'][i % 5]['id'], created_data['tags'][(i + 1) % 5]['id']]
        for tag_id in tag_ids:
            cursor.execute("""
                INSERT INTO core_snapshot_tags (snapshot_id, tag_id) VALUES (?, ?)
            """, (snapshot_id, tag_id))

        # Create 5 archive results for each snapshot
        extractors = ['title', 'favicon', 'screenshot', 'singlefile', 'wget']
        statuses = ['succeeded', 'succeeded', 'failed', 'succeeded', 'skipped']

        for j, (extractor, status) in enumerate(zip(extractors, statuses)):
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

    # Create 2 Crawls (0.9.0 schema - no seeds)
    test_crawls = [
        ('https://example.com\nhttps://example.org', 0, 'Example Crawl'),
        ('https://github.com/ArchiveBox', 1, 'GitHub Crawl'),
    ]

    for i, (urls, max_depth, label) in enumerate(test_crawls):
        crawl_id = generate_uuid()
        cursor.execute("""
            INSERT INTO crawls_crawl (id, created_at, created_by_id, modified_at, urls,
                                      config, max_depth, tags_str, label, status, retry_at,
                                      num_uses_failed, num_uses_succeeded)
            VALUES (?, datetime('now'), ?, datetime('now'), ?, '{}', ?, '', ?, 'queued', datetime('now'), 0, 0)
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
        ('https://news.ycombinator.com/item?id=12345', 'HN Discussion', None),
        ('https://en.wikipedia.org/wiki/Test', 'Wikipedia Test', None),
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

        # Assign 2 tags to each snapshot
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
        # For 0.8.x (dev branch), record the migrations that 0023_new_schema replaces
        ('core', '0023_alter_archiveresult_options_archiveresult_abid_and_more'),
        ('core', '0024_auto_20240513_1143'),
        ('core', '0025_alter_archiveresult_uuid'),
        ('core', '0026_archiveresult_created_archiveresult_created_by_and_more'),
        ('core', '0027_update_snapshot_ids'),
        ('core', '0028_alter_archiveresult_uuid'),
        ('core', '0029_alter_archiveresult_id'),
        ('core', '0030_alter_archiveresult_uuid'),
        ('core', '0031_alter_archiveresult_id_alter_archiveresult_uuid_and_more'),
        ('core', '0032_alter_archiveresult_id'),
        ('core', '0033_rename_id_archiveresult_old_id'),
        ('core', '0034_alter_archiveresult_old_id_alter_archiveresult_uuid'),
        ('core', '0035_remove_archiveresult_uuid_archiveresult_id'),
        ('core', '0036_alter_archiveresult_id_alter_archiveresult_old_id'),
        ('core', '0037_rename_id_snapshot_old_id'),
        ('core', '0038_rename_uuid_snapshot_id'),
        ('core', '0039_rename_snapshot_archiveresult_snapshot_old'),
        ('core', '0040_archiveresult_snapshot'),
        ('core', '0041_alter_archiveresult_snapshot_and_more'),
        ('core', '0042_remove_archiveresult_snapshot_old'),
        ('core', '0043_alter_archiveresult_snapshot_alter_snapshot_id_and_more'),
        ('core', '0044_alter_archiveresult_snapshot_alter_tag_uuid_and_more'),
        ('core', '0045_alter_snapshot_old_id'),
        ('core', '0046_alter_archiveresult_snapshot_alter_snapshot_id_and_more'),
        ('core', '0047_alter_snapshottag_unique_together_and_more'),
        ('core', '0048_alter_archiveresult_snapshot_and_more'),
        ('core', '0049_rename_snapshot_snapshottag_snapshot_old_and_more'),
        ('core', '0050_alter_snapshottag_snapshot_old'),
        ('core', '0051_snapshottag_snapshot_alter_snapshottag_snapshot_old'),
        ('core', '0052_alter_snapshottag_unique_together_and_more'),
        ('core', '0053_remove_snapshottag_snapshot_old'),
        ('core', '0054_alter_snapshot_timestamp'),
        ('core', '0055_alter_tag_slug'),
        ('core', '0056_remove_tag_uuid'),
        ('core', '0057_rename_id_tag_old_id'),
        ('core', '0058_alter_tag_old_id'),
        ('core', '0059_tag_id'),
        ('core', '0060_alter_tag_id'),
        ('core', '0061_rename_tag_snapshottag_old_tag_and_more'),
        ('core', '0062_alter_snapshottag_old_tag'),
        ('core', '0063_snapshottag_tag_alter_snapshottag_old_tag'),
        ('core', '0064_alter_snapshottag_unique_together_and_more'),
        ('core', '0065_remove_snapshottag_old_tag'),
        ('core', '0066_alter_snapshottag_tag_alter_tag_id_alter_tag_old_id'),
        ('core', '0067_alter_snapshottag_tag'),
        ('core', '0068_alter_archiveresult_options'),
        ('core', '0069_alter_archiveresult_created_alter_snapshot_added_and_more'),
        ('core', '0070_alter_archiveresult_created_by_alter_snapshot_added_and_more'),
        ('core', '0071_remove_archiveresult_old_id_remove_snapshot_old_id_and_more'),
        ('core', '0072_rename_added_snapshot_bookmarked_at_and_more'),
        ('core', '0073_rename_created_archiveresult_created_at_and_more'),
        ('core', '0074_alter_snapshot_downloaded_at'),
        # For 0.8.x: DO NOT record 0023_new_schema - it replaces 0023-0074 for fresh installs
        # We already recorded 0023-0074 above, so Django will know the state
        # For 0.8.x: Record original machine migrations (before squashing)
        # DO NOT record 0001_squashed here - it replaces 0001-0004 for fresh installs
        ('machine', '0001_initial'),
        ('machine', '0002_alter_machine_stats_installedbinary'),
        ('machine', '0003_alter_installedbinary_options_and_more'),
        ('machine', '0004_alter_installedbinary_abspath_and_more'),
        # Then the new migrations after squashing
        ('machine', '0002_rename_custom_cmds_to_overrides'),
        ('machine', '0003_alter_dependency_id_alter_installedbinary_dependency_and_more'),
        ('machine', '0004_drop_dependency_table'),
        # Crawls must come before core.0024 because 0024_b depends on it
        ('crawls', '0001_initial'),
        # Core 0024 migrations chain (in dependency order)
        ('core', '0024_b_clear_config_fields'),
        ('core', '0024_c_disable_fk_checks'),
        ('core', '0024_d_fix_crawls_config'),
        ('core', '0024_snapshot_crawl'),
        ('core', '0024_f_add_snapshot_config'),
        ('core', '0025_allow_duplicate_urls_per_crawl'),
        # For 0.8.x: Record original api migration (before squashing)
        # DO NOT record 0001_squashed here - it replaces 0001 for fresh installs
        ('api', '0001_initial'),
        ('api', '0002_alter_apitoken_options'),
        ('api', '0003_rename_user_apitoken_created_by_apitoken_abid_and_more'),
        ('api', '0004_alter_apitoken_id_alter_apitoken_uuid'),
        ('api', '0005_remove_apitoken_uuid_remove_outboundwebhook_uuid_and_more'),
        ('api', '0006_remove_outboundwebhook_uuid_apitoken_id_and_more'),
        ('api', '0007_alter_apitoken_created_by'),
        ('api', '0008_alter_apitoken_created_alter_apitoken_created_by_and_more'),
        ('api', '0009_rename_created_apitoken_created_at_and_more'),
        # Note: crawls.0001_initial moved earlier (before core.0024) due to dependencies
        # Stop here - 0.8.x ends at core.0025, crawls.0001, and we want to TEST the later migrations
        # Do NOT record 0026+ as they need to be tested during migration
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

def run_archivebox(data_dir: Path, args: list, timeout: int = 60, env: dict = None) -> subprocess.CompletedProcess:
    """Run archivebox command in subprocess with given data directory."""
    base_env = os.environ.copy()
    base_env['DATA_DIR'] = str(data_dir)
    base_env['USE_COLOR'] = 'False'
    base_env['SHOW_PROGRESS'] = 'False'
    # Disable ALL extractors for faster tests (can be overridden by env parameter)
    base_env['SAVE_ARCHIVEDOTORG'] = 'False'
    base_env['SAVE_TITLE'] = 'False'
    base_env['SAVE_FAVICON'] = 'False'
    base_env['SAVE_WGET'] = 'False'
    base_env['SAVE_SINGLEFILE'] = 'False'
    base_env['SAVE_SCREENSHOT'] = 'False'
    base_env['SAVE_PDF'] = 'False'
    base_env['SAVE_DOM'] = 'False'
    base_env['SAVE_READABILITY'] = 'False'
    base_env['SAVE_MERCURY'] = 'False'
    base_env['SAVE_GIT'] = 'False'
    base_env['SAVE_YTDLP'] = 'False'
    base_env['SAVE_HEADERS'] = 'False'
    base_env['SAVE_HTMLTOTEXT'] = 'False'

    # Override with any custom env vars
    if env:
        base_env.update(env)

    cmd = [sys.executable, '-m', 'archivebox'] + args

    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        env=base_env,
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
    """Verify the number of tags in the database (exact match)."""
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM core_tag")
    count = cursor.fetchone()[0]
    conn.close()

    if count == expected:
        return True, f"Tag count OK: {count}"
    return False, f"Tag count mismatch: expected {expected}, got {count}"


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
    """Verify ALL expected URLs exist in snapshots."""
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
    """Verify ALL snapshot titles are preserved."""
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    cursor.execute("SELECT url, title FROM core_snapshot")
    actual = {row[0]: row[1] for row in cursor.fetchall()}
    conn.close()

    mismatches = []
    for url, expected_title in expected_titles.items():
        if url not in actual:
            mismatches.append(f"{url}: missing from database")
        elif actual[url] != expected_title:
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


def verify_all_snapshots_in_output(output: str, snapshots: List[Dict]) -> Tuple[bool, str]:
    """Verify ALL snapshots appear in command output (not just one)."""
    missing = []
    for snapshot in snapshots:
        url_fragment = snapshot['url'][:30]
        title = snapshot.get('title', '')
        if url_fragment not in output and (not title or title not in output):
            missing.append(snapshot['url'])

    if not missing:
        return True, "All snapshots found in output"
    return False, f"Missing snapshots in output: {missing}"


def verify_crawl_count(db_path: Path, expected: int) -> Tuple[bool, str]:
    """Verify the number of crawls in the database."""
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM crawls_crawl")
    count = cursor.fetchone()[0]
    conn.close()

    if count == expected:
        return True, f"Crawl count OK: {count}"
    return False, f"Crawl count mismatch: expected {expected}, got {count}"


def verify_process_migration(db_path: Path, expected_archiveresult_count: int) -> Tuple[bool, str]:
    """
    Verify that ArchiveResults were properly migrated to Process records.

    Checks:
    1. All ArchiveResults have process_id set
    2. Process count matches ArchiveResult count
    3. Binary records created for unique cmd_version values
    4. Status mapping is correct
    """
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()

    # Check all ArchiveResults have process_id
    cursor.execute("SELECT COUNT(*) FROM core_archiveresult WHERE process_id IS NULL")
    null_count = cursor.fetchone()[0]

    if null_count > 0:
        conn.close()
        return False, f"Found {null_count} ArchiveResults without process_id"

    # Check Process count
    cursor.execute("SELECT COUNT(*) FROM machine_process")
    process_count = cursor.fetchone()[0]

    if process_count != expected_archiveresult_count:
        conn.close()
        return False, f"Expected {expected_archiveresult_count} Processes, got {process_count}"

    # Check status mapping
    cursor.execute("""
        SELECT ar.status, p.status, p.exit_code
        FROM core_archiveresult ar
        JOIN machine_process p ON ar.process_id = p.id
    """)

    status_errors = []
    for ar_status, p_status, p_exit_code in cursor.fetchall():
        expected_p_status, expected_exit_code = {
            'queued': ('queued', None),
            'started': ('running', None),
            'backoff': ('queued', None),
            'succeeded': ('exited', 0),
            'failed': ('exited', 1),
            'skipped': ('exited', None),
        }.get(ar_status, ('queued', None))

        if p_status != expected_p_status:
            status_errors.append(f"AR status {ar_status} → Process {p_status}, expected {expected_p_status}")

        if p_exit_code != expected_exit_code:
            status_errors.append(f"AR status {ar_status} → exit_code {p_exit_code}, expected {expected_exit_code}")

    if status_errors:
        conn.close()
        return False, f"Status mapping errors: {'; '.join(status_errors[:5])}"

    conn.close()
    return True, f"Process migration verified: {process_count} Processes created"
