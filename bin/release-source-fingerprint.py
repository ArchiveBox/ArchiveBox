#!/usr/bin/env python3
"""Fingerprint a Git tree while ignoring only ArchiveBox's own release version."""

from __future__ import annotations

import hashlib
import re
import subprocess
import sys


VERSION_MARKER = b"<ARCHIVEBOX_PROJECT_VERSION>"


def git(*args: str) -> bytes:
    return subprocess.run(
        ["git", *args],
        check=True,
        capture_output=True,
    ).stdout


def normalize_file(path: bytes, content: bytes) -> bytes:
    """Replace exact own-version values while preserving all other file bytes."""
    if path == b"pyproject.toml":
        lines = content.splitlines(keepends=True)
        section = b""
        replacements = {b"project": 0, b"tool.bumpver": 0}
        normalized = []
        for line in lines:
            stripped = line.strip()
            if stripped.startswith(b"[") and stripped.endswith(b"]"):
                section = stripped[1:-1]
            key = b"version" if section == b"project" else b"current_version" if section == b"tool.bumpver" else None
            if key is not None:
                match = re.fullmatch(rb"(\s*" + key + rb"\s*=\s*)\"[^\"\r\n]+(\"\s*(?:#.*)?\r?\n?)", line)
                if match:
                    replacements[section] += 1
                    line = match.group(1) + b'"' + VERSION_MARKER + match.group(2)
            normalized.append(line)
        if replacements != {b"project": 1, b"tool.bumpver": 1}:
            raise ValueError("pyproject.toml must contain exactly one project.version and tool.bumpver.current_version")
        return b"".join(normalized)

    if path == b"uv.lock":
        blocks = re.split(rb"(?m)(?=^\[\[package\]\]\s*$)", content)
        found = 0
        for index, block in enumerate(blocks):
            if not re.search(rb'(?m)^name = "archivebox"\s*$', block):
                continue
            updated, count = re.subn(
                rb'(?m)^(version = ")[^"\r\n]+("\s*)$',
                lambda match: match.group(1) + VERSION_MARKER + match.group(2),
                block,
                count=1,
            )
            if count != 1:
                raise ValueError("uv.lock ArchiveBox package must have exactly one version")
            blocks[index] = updated
            found += 1
        if found != 1:
            raise ValueError("uv.lock must contain exactly one ArchiveBox package")
        return b"".join(blocks)

    if path == b"etc/package.json":
        normalized, count = re.subn(
            rb'(?m)^(  "version": ")[^"\r\n]+("[,]?\s*)$',
            lambda match: match.group(1) + VERSION_MARKER + match.group(2),
            content,
            count=1,
        )
        if count != 1:
            raise ValueError("etc/package.json must contain exactly one top-level version")
        return normalized

    return content


def fingerprint(revision: str) -> str:
    entries = git("ls-tree", "-rz", "--full-tree", "-r", revision).split(b"\0")
    digest = hashlib.sha256()
    for entry in entries:
        if not entry:
            continue
        metadata, path = entry.split(b"\t", 1)
        mode, object_type, object_id = metadata.split(b" ")
        if object_type == b"blob":
            content = normalize_file(path, git("cat-file", "blob", object_id.decode("ascii")))
        elif mode == b"160000" and object_type == b"commit":
            content = object_id
        else:
            raise ValueError(f"unsupported Git tree entry: {metadata!r}")
        for value in (path, mode, object_type, content):
            digest.update(len(value).to_bytes(8, "big"))
            digest.update(value)
    return digest.hexdigest()


if __name__ == "__main__":
    print(fingerprint(sys.argv[1] if len(sys.argv) > 1 else "HEAD"))
