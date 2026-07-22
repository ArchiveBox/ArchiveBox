"""Generate the code reference pages and navigation."""

from pathlib import Path

import mkdocs_gen_files

nav = mkdocs_gen_files.Nav()
mod_symbol = '<code class="doc-symbol doc-symbol-nav doc-symbol-module"></code>'

packages_dir = Path(__file__).parent
doc_root = packages_dir / "docs"

for path in sorted((packages_dir / "archivebox").rglob("*.py")):
    module_path = path.relative_to(packages_dir).with_suffix("")
    doc_path = path.relative_to(packages_dir).with_suffix(".md")
    full_doc_path = doc_root / "reference" / doc_path

    if (
        "management" in str(module_path)
        or "vendor" in str(module_path)
        or "machine" in str(module_path)
        or "migrations" in str(module_path)
        or "plugins" in str(module_path)
    ):
        continue

    parts = tuple(module_path.parts)

    if parts[-1] == "__init__":
        parts = parts[:-1]
        doc_path = doc_path.with_name("index.md")
        full_doc_path = full_doc_path.with_name("index.md")
    elif parts[-1].startswith("_"):
        continue

    full_doc_path = full_doc_path.relative_to(packages_dir)

    nav_parts = [f"{mod_symbol} {part}" for part in parts]
    nav[tuple(nav_parts)] = doc_path.as_posix()

    with mkdocs_gen_files.open(full_doc_path, "w") as fd:
        ident = ".".join(parts)
        fd.write(f"---\ntitle: {ident}\n---\n\n::: {ident}")

    mkdocs_gen_files.set_edit_path(full_doc_path, path.relative_to(packages_dir))

with mkdocs_gen_files.open(doc_root / "reference" / "SUMMARY.md", "w") as nav_file:
    nav_file.writelines(nav.build_literate_nav())
