# Copyright (c) Arduino s.r.l. and/or its affiliated companies
# SPDX-License-Identifier: MPL-2.0

"""Generate pages/index.html listing all CI package indexes."""

import argparse
import collections
import datetime
import json
import re
import semver
import subprocess

from packaging_legacy.version import parse as legacy_parse
from pathlib import Path

# Assumptions on directory structure:
OUTPUT_DIR = Path("pages") # contains JSON and srcmap files, index.html will be generated here
SNIPPETS_DIR = Path("snippets") # contains owner/repo/branch/ directories with snippets
SCRIPTS_DIR = Path("package_index/scripts") # contains last_modified.sh
GROUP_PATTERNS_FILE = Path(__file__).parent / "group-patterns.json"


def load_group_patterns() -> list:
    """Load compiled regex patterns from group-patterns.json."""
    if not GROUP_PATTERNS_FILE.exists():
        return []
    with open(GROUP_PATTERNS_FILE) as f:
        return [re.compile(f"^{p}$") for p in json.load(f)]


def get_index_name(owner: str, repo: str, branch: str) -> str:
    """Construct index filename from owner/repo/branch."""
    short_repo = repo.removeprefix("ArduinoCore-")
    return f"{owner}_{short_repo}_{branch}_ci"


def load_timestamps() -> dict:
    """Run last_modified.sh and parse its output; return filepath → ISO8601 dict."""
    #try:
    ts: dict = {}
    output = subprocess.check_output([SCRIPTS_DIR / "last_modified.sh"], text=True)
    for line in output.splitlines():
        parts = line.split("\t", 1)
        if len(parts) == 2:
            date_str, filepath = parts
            file_parts = filepath.split("/")
            print(file_parts)
            if len(file_parts) > 5 and file_parts[0] == "snippets":
                owner, repo, branch, version = file_parts[1:5]
                src_stem = '/'.join(file_parts[:5])
                dst_stem = f'{get_index_name(owner, repo, branch)}/{owner}'
                filepath = filepath.replace(src_stem, dst_stem)
                filepath = filepath.replace("pillo79", "arduino") # FIXME REMOVEME
                ts[filepath] = date_str
    return ts
    #except Exception:
    #    return {}


def load_srcmap(index_name: str) -> dict:
    """Load pages/<index_name>.srcmap if it exists, return {"platforms":{}, "tools":{}}."""
    srcmap_path = OUTPUT_DIR / (index_name + ".srcmap")
    if not srcmap_path.exists():
        return {}
    try:
        with open(srcmap_path) as f:
            return json.load(f)
    except Exception:
        return {}


def sort_by_version(l: list) -> list:
    if not l:
        return l
    elif isinstance(l[0], str):
        # list of version strings, no timestamp available
        try:
            return sorted(l, key=lambda x: semver.Version.parse(x), reverse=True)
        except:
            return sorted(l, key=lambda x: legacy_parse(x), reverse=True)
    else:
        # list of (version, ts) tuples: tiebreak equal versions by timestamp (newer first)
        try:
            return sorted(l, key=lambda x: (semver.Version.parse(x[0]), x[1]), reverse=True)
        except:
            return sorted(l, key=lambda x: (legacy_parse(x[0]), x[1]), reverse=True)


def parse_srcmap_items(raw_srcmap: dict, timestamps: dict = {}) -> tuple:
    """Parse a srcmap dict into (items, plat_versions, last_ts).

    items is a defaultdict mapping (kind, packager, name) → [(version, ts), ...]
    timestamps maps srcfile path → ISO8601 string; absent entries yield "".
    """
    items = collections.defaultdict(list)
    plat_versions = set()
    last_ts = ""
    for kind in "platforms", "tools":
        for what, srcfile in raw_srcmap.get(kind, {}).items():
            packager, name, version = what.split(":", 2)
            ts = timestamps.get(srcfile, "")
            items[(kind, packager, name)].append((version, ts))
            last_ts = max(last_ts, ts)
            if kind == "platforms":
                plat_versions.add(version)
    return items, plat_versions, last_ts


def collect_ci_entries() -> dict:
    last_timestamps = load_timestamps()
    print(f"Loaded timestamps: {last_timestamps}")
    data: dict = {}
    for branch_dir in sorted(SNIPPETS_DIR.glob("*/*/*/")):
        parts = branch_dir.relative_to(SNIPPETS_DIR).parts
        if len(parts) != 3:
            continue
        owner, repo, branch = parts
        owner="arduino" # FIXME REMOVEME
        index_name = f"{get_index_name(owner, repo, branch)}.json"
        raw_srcmap = load_srcmap(index_name)
        print(f"Processing {index_name} with srcmap: {raw_srcmap}")
        items, plat_versions, last_ts = parse_srcmap_items(raw_srcmap, last_timestamps)

        data[(owner, repo, branch)] = {
            "file": index_name,
            "plat_vers": sort_by_version(list(plat_versions)),
            "link": f"{index_name}.json",
            "mtime": last_ts,
            "items": items,
        }
    print(f"Collected data: {data}")
    return data


def collect_prod_entry() -> dict:
    """Load prod.json.srcmap from OUTPUT_DIR and build an entry dict (no timestamps)."""
    raw_srcmap = load_srcmap("prod.json")
    if not raw_srcmap:
        return {}
    items, _, _ = parse_srcmap_items(raw_srcmap)
    return {
        "file": None,
        "plat_vers": [""], # empty column
        "link": None,
        "mtime": None,
        "items": items,
    }


def fmt_ts(ts: str) -> str:
    """Emit a timestamp span; age is computed client-side by JS."""
    return f'<span class="ts" data-ts="{ts}">{ts}</span>' if ts else ""


def fmt_version_link(version: str, owner: str = "", repo: str = "") -> str:
    """Wrap version in a GitHub tree link. +suffix → SHA, otherwise tag."""
    if not owner or not repo:
        return version
    if "+" in version:
        ref = version.split("+", 1)[1]
    else:
        ref = version
    url = f"https://github.com/{owner}/{repo}/tree/{ref}"
    return f'<a href="{url}">{version}</a>'


def fmt_versions(v: list) -> str:
    if v:
        last_version = v[0]
        if isinstance(last_version, tuple):
            last_version = last_version[0]
        num_versions = len(v)
        return f"{last_version}<br>and {num_versions-1} more" if num_versions > 1 else last_version
    else:
        return "unknown"


def group_items(items: dict) -> list:
    """Group items by regex patterns from group-patterns.json.

    Items whose 'packager:name' matches the same pattern (and same kind)
    are merged. The group's version list is the union of all members.
    Returns a list of ([(kind, packager, name), ...], {(kind,packager,name): [(ver,ts),...]}) tuples.
    """
    patterns = load_group_patterns()

    # Assign each item to a group key: (kind, pattern_index) or (kind, packager, name) for unmatched
    group_map = collections.defaultdict(list)
    for key in items:
        kind, packager, name = key
        pn = f"{packager}:{name}"
        matched = False
        for i, pat in enumerate(patterns):
            if pat.match(pn):
                group_map[(kind, i)].append(key)
                matched = True
                break
        if not matched:
            group_map[key].append(key)

    # Build output preserving sort order (by first member in each group)
    result = []
    seen = set()
    for key in sorted(items.keys()):
        if key in seen:
            continue
        # Find which group this key belongs to
        for gk, members in group_map.items():
            if key in members:
                sorted_members = sorted(members)
                # Build per-member version map
                member_versions = {m: sort_by_version(items[m]) for m in sorted_members}
                for m in sorted_members:
                    seen.add(m)
                result.append((sorted_members, member_versions))
                break
    return result


def build_inner_html(index, key = None, url_prefix = ""):
    """Render <details> blocks for a single index entry."""
    # Main item block
    if key: # all CI branch entries
        owner, repo, branch = key
        details = 'file-item'
        badge = '<span class="badge badge-branch">branch</span>'
        title = f'<a href="{url_prefix + index['file']}">{owner}/{repo}<br>&nbsp;@ {branch}</a>'
    else: # prod entry
        owner, repo = "", ""
        details = 'file-item official-item'
        badge = '<span class="badge badge-official">official</span>'
        title = 'package_index.json'

    html = f"""
        <details class="{details}">
            <summary class="grid-row summary-row">
                <span>{title} {badge}</span>
                <span>{fmt_versions(index['plat_vers'])}</span>
                <span>{fmt_ts(index['mtime'])}</span>
            </summary>"""

    # Sub-groups (merged by regex pattern match)
    for members, member_versions in group_items(index['items']):
        kind = members[0][0][:-1]  # drop plural 's'
        label = ", ".join(f"{p}:<b>{n}</b>" for _, p, n in members)
        badge = f'<span class="badge badge-{kind}">{kind}</span>'

        # Union of all versions across members, sorted
        all_versions_set = {}
        for m, vers in member_versions.items():
            for v, ts in vers:
                if v not in all_versions_set or ts > all_versions_set[v]:
                    all_versions_set[v] = ts
        all_versions = sort_by_version([(v, ts) for v, ts in all_versions_set.items()])

        html += f"""
            <details class="sub-group">
                <summary class="grid-row sub-summary-row">
                    <span><span class="tree-branch">↳</span> {label} {badge}</span>
                    <span>{fmt_versions(all_versions)}</span>
                    <span>{fmt_ts(all_versions[0][1]) if all_versions else ""}</span>
                </summary>"""
        # Build per-member version lookup for quick membership check
        member_ver_sets = {m: {v for v, _ in vers} for m, vers in member_versions.items()}
        for v, ts in all_versions:
            present = [m for m in members if v in member_ver_sets[m]]
            names_str = ", ".join(f"{p}:{n}" for _, p, n in present)
            html += f"""
                <div class="grid-row detail-row">
                    <span>{names_str}</span>
                    <span>{fmt_version_link(v, owner, repo)}</span>
                    <span>{fmt_ts(ts)}</span>
                </div>"""
        html += "</details>\n"

    html += "</details>\n"
    return html


def build_table_html(data: dict, prod: dict, url_prefix: str) -> str:
    """Render all table entries as file-item blocks."""
    html_output = ""
    for key, index in data.items():
        html_output += build_inner_html(index, key, url_prefix)
    html_output += build_inner_html(prod, "")
    return html_output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Generate index.html listing all CI package indexes."
    )
    parser.add_argument("--output-dir", help="Path to directory with generated files")
    parser.add_argument("--owner-repo", help="GitHub owner/repo for base URL (e.g. arduino/core-ci-builds)")
    args = parser.parse_args()
    if args.output_dir:
        OUTPUT_DIR = Path(args.output_dir)
    if args.owner_repo:
        if "/" not in args.owner_repo:
            parser.error(f"Invalid owner/repo format: {args.owner_repo}")
        owner, repo = args.owner_repo.split("/", 1)
        url_prefix = f"https://{owner}.github.io/{repo}/"
    else:
        url_prefix = ""

    if not OUTPUT_DIR.exists():
        print(f"Error: Output directory '{OUTPUT_DIR}' does not exist.")
        exit(1)

    data = collect_ci_entries()
    prod = collect_prod_entry()
    dynamic_content = build_table_html(data, prod, url_prefix)
    generated_at = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    template_path = Path(__file__).with_suffix(".template.html")
    with open(template_path, "r", encoding="utf-8") as template_file:
        template_content = template_file.read()

    final_html = (template_content
                  .replace("{{ FILE_LIST_CONTENT }}", dynamic_content)
                  .replace("{{ GENERATED_AT }}", generated_at))
    with open(OUTPUT_DIR / "index.html", "w", encoding="utf-8") as output_file:
        output_file.write(final_html)
