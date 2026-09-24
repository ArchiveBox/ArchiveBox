"""Print compact release notes from the preceding stable tag to a tested commit."""

import argparse
import os
import re
import subprocess
import tomllib


def git(*args):
    return subprocess.check_output([os.environ.get("GIT_BINARY", "git"), *args], text=True).strip()


def version(tag):
    match = re.fullmatch(r"v(\d+)\.(\d+)\.(\d+)", tag)
    return tuple(map(int, match.groups())) if match else None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tag")
    parser.add_argument("ref", help="Exact tested release commit; the new tag need not exist yet")
    parser.add_argument("--repo", default="ArchiveBox/ArchiveBox")
    args = parser.parse_args()
    current = version(args.tag)
    if current is None:
        parser.error("a stable vMAJOR.MINOR.PATCH tag is required")
    previous = max(
        (tag for tag in git("tag", "--merged", args.ref).splitlines() if version(tag) and version(tag) < current),
        key=version,
    )
    root = f"https://github.com/{args.repo}"
    print(f"## Changes since {previous}\n")
    seen = set()
    for line in git("log", "--reverse", "--no-merges", "--format=%H%x09%s", f"{previous}..{args.ref}").splitlines():
        sha, subject = line.split("\t", 1)
        if re.match(r"(?:Bump release version|chore\(release\)|chore\(deps\)|Update .* dependencies|Pin .* release)", subject, re.I):
            continue
        if subject not in seen:
            print(f"- {subject} ([{sha[:8]}]({root}/commit/{sha})).")
            seen.add(subject)
    old = tomllib.loads(git("show", f"{previous}:pyproject.toml"))["project"]["dependencies"]
    new = tomllib.loads(git("show", f"{args.ref}:pyproject.toml"))["project"]["dependencies"]
    updates = [dependency for dependency in new if dependency not in old]
    if updates:
        print("- ⬆️ Updated dependencies: " + ", ".join(f"`{dependency}`" for dependency in updates) + ".")
    print(f"\n[Full changelog]({root}/compare/{previous}...{args.tag}) · [0.9 announcement]({root}/releases/tag/v0.9.36)")


if __name__ == "__main__":
    main()
