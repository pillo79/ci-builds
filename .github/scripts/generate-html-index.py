"""Generate pages/index.html listing all CI package indexes."""

import argparse
import collections
import datetime
import json
import semver
import subprocess

from packaging_legacy.version import parse as legacy_parse
from pathlib import Path

# Assumptions on directory structure:
OUTPUT_DIR = Path("pages") # contains JSON and srcmap files, index.html will be generated here
SNIPPETS_DIR = Path("snippets") # contains owner/repo/branch/ directories with snippets
SCRIPTS_DIR = Path("package_index/scripts") # contains last_modified.sh


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
            if len(file_parts) > 5 and file_parts[0] == "snippets":
                owner, repo, branch, version = file_parts[1:5]
                src_stem = '/'.join(file_parts[:5])
                dst_stem = f'{get_index_name(owner, repo, branch)}/{owner}'
                filepath = filepath.replace(src_stem, dst_stem)
                ts[filepath] = date_str
    return ts
    #except Exception:
    #    return {}


def load_srcmap(index_name: str) -> dict | None:
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
        # list of versions strings
        try:
            return sorted(l, key=lambda x: semver.Version.parse(x), reverse=True)
        except:
            return sorted(l, key=lambda x: legacy_parse(x), reverse=True)
    else:
        # list of tuples, version is the first element
        try:
            return sorted(l, key=lambda x: semver.Version.parse(x[0]), reverse=True)
        except:
            return sorted(l, key=lambda x: legacy_parse(x[0]), reverse=True)


def collect_entries() -> dict:
    last_timestamps = load_timestamps()
    data: dict = {}
    for branch_dir in sorted(SNIPPETS_DIR.glob("*/*/*/")):
        parts = branch_dir.relative_to(SNIPPETS_DIR).parts
        if len(parts) != 3:
            continue
        owner, repo, branch = parts
        index_name = f"{get_index_name(owner, repo, branch)}.json"
        raw_srcmap = load_srcmap(index_name)
        items = collections.defaultdict(list)
        plat_versions = set()
        last_ts = ""
        for kind in "platforms", "tools":
            for what, srcfile in raw_srcmap.get(kind, {}).items():
                packager, name, version = what.split(":", 2)
                ts = last_timestamps.get(srcfile.replace("pillo79","arduino"), "")
                items[(kind, packager, name)].append((version, ts))
                last_ts = max(last_ts, ts)
                if kind == "platforms":
                    plat_versions.add(version)

        data[(owner, repo, branch)] = {
            "file": index_name,
            "plat_vers": sort_by_version(list(plat_versions)),
            "link": f"{index_name}.json",
            "mtime": last_ts,
            "items": items,
        }
    return data


def fmt_ts(ts: str) -> str:
    """Format ISO8601 UTC timestamp as 'YYYY-MM-DD (age)'."""
    try:
        dt = datetime.datetime.fromisoformat(ts.replace("Z", "+00:00"))
        today = datetime.datetime.now(datetime.timezone.utc)
        delta = (today - dt).days
        if delta == 0:
            hours = (today - dt).seconds // 3600
            if hours < 1:
                age = "just now"
            else:
                age = f"{hours} hour{'s' if hours > 1 else ''} ago"
        elif delta < 7:
            age = f"{delta} day{'s' if delta > 1 else ''} ago"
        elif delta < 30:
            weeks = delta // 7
            age = f"{weeks} week{'s' if weeks > 1 else ''} ago"
        elif delta < 365:
            months = delta // 30
            age = f"{months} month{'s' if months > 1 else ''} ago"
        else:
            years = delta // 365
            age = "over {'a' if years == 1 else years} year{'s' if years > 1 else ''} ago"
        return f"{ts}<br>({age})"
    except Exception:
        return ts


def fmt_versions(v: list) -> str:
    if v:
        last_version = v[0]
        if isinstance(last_version, tuple):
            last_version = last_version[0]
        older_versions = len(v)
        return f"{last_version}<br>and {older_versions} more" if older_versions > 1 else last_version
    else:
        return "unknown"


def build_inner_html(data, url_prefix):
    """Generates only the list elements, not the whole page."""
    html_output = ""

    for (owner, repo, branch), index in data.items():
        # Main item block
        html_output += f"""
            <details class="file-item">
                <summary class="grid-row summary-row">
                    <span><span class="badge badge-branch">branch</span></span>
                    <span><a href="{url_prefix + index['file']}">{owner}/{repo}<br>&nbsp;@ {branch}</a></span>
                    <span>{fmt_versions(index['plat_vers'])}</span>
                    <span>{fmt_ts(index['mtime'])}</span>
                </summary>"""

        # Sub-groups
        for (kind, packager, name), versions in sorted(index['items'].items()):
            kind = kind[:-1] # drop plural 's'
            versions = sort_by_version(versions)
            label = f"{packager}:<b>{name}</b>"
            badge = f'<span class="badge badge-{kind}">{kind}</span>'
            html_output += f"""
                <details class="sub-group">
                    <summary class="grid-row sub-summary-row">
                        <span>{badge}</span>
                        <span><span class="tree-branch">↳</span> {label}</span>
                        <span>{fmt_versions(versions)}</span>
                        <span>{fmt_ts(versions[0][1])}</span>
                    </summary>"""

            # Detail rows
            for v in versions:
                html_output += f"""
                    <div class="grid-row detail-row">
                        <span></span>
                        <span>{packager}:{name}</span>
                        <span>{v[0]}</span>
                        <span>{fmt_ts(v[1])}</span>
                    </div>"""
            html_output += "</details>\n"

        html_output += "</details>\n"

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

    data = collect_entries()
    dynamic_content = build_inner_html(data, url_prefix)
    generated_at = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    template_path = Path(__file__).with_suffix(".template.html")
    with open(template_path, "r", encoding="utf-8") as template_file:
        template_content = template_file.read()

    final_html = (template_content
                  .replace("{{ FILE_LIST_CONTENT }}", dynamic_content)
                  .replace("{{ GENERATED_AT }}", generated_at))
    with open(OUTPUT_DIR / "index.html", "w", encoding="utf-8") as output_file:
        output_file.write(final_html)
