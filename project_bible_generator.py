#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Project Bible Generator v3
Generic GUI-first utility to turn source projects into AI-readable Markdown bundles.

No project-specific presets or buttons.
No third-party dependencies.
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import queue
import re
import subprocess
import sys
import threading
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional

APP_NAME = "Project Bible Generator"
APP_VERSION = "3.0.0"
CONFIG_FILENAME = ".projectbible.json"
MANIFEST_FILENAME = "_projectbible_manifest.json"
DEFAULT_OUTPUT_DIRNAME = "ProjectBible"

DEFAULT_MAX_LINES = 10_000
DEFAULT_MAX_SOURCE_MB = 2.0

DEFAULT_EXTENSIONS = [
    ".c", ".cc", ".cpp", ".cxx", ".h", ".hh", ".hpp", ".hxx",
    ".cs",
    ".lua", ".otui", ".otmod",
    ".py",
    ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs",
    ".java", ".kt", ".kts",
    ".go", ".rs",
    ".php", ".rb", ".swift",
    ".html", ".htm", ".css", ".scss", ".sass", ".less",
    ".xml", ".json", ".jsonc",
    ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf",
    ".sql",
    ".md", ".txt", ".rst",
    ".sh", ".bash", ".zsh", ".ps1", ".bat", ".cmd",
    ".cmake", ".gradle", ".proto",
]

DEFAULT_SPECIAL_FILENAMES = [
    "CMakeLists.txt",
    "Dockerfile",
    "Makefile",
    "Gemfile",
    "Rakefile",
    "package.json",
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "requirements.txt",
    "pyproject.toml",
    "Cargo.toml",
    "go.mod",
    "go.sum",
    ".editorconfig",
    ".gitattributes",
    ".gitignore",
    ".dockerignore",
]

DEFAULT_IGNORE_DIRS = [
    ".git", ".svn", ".hg",
    ".idea", ".vs", ".vscode",
    "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    "node_modules",
    "Library", "Temp", "Logs", "UserSettings",
    "bin", "obj", "build", "Build", "dist", "out", "target",
    ".next", ".nuxt", ".cache",
    "vendor",
    DEFAULT_OUTPUT_DIRNAME,
    "ChatGPTProject",
]

DEFAULT_IGNORE_GLOBS = [
    "*.exe", "*.dll", "*.pdb", "*.so", "*.dylib", "*.a", "*.lib",
    "*.zip", "*.7z", "*.rar", "*.tar", "*.gz",
    "*.png", "*.jpg", "*.jpeg", "*.gif", "*.bmp", "*.webp", "*.ico",
    "*.mp3", "*.ogg", "*.wav", "*.flac",
    "*.mp4", "*.mov", "*.avi", "*.mkv",
    "*.otbm", "*.spr", "*.dat",
    "*.glb", "*.gltf", "*.fbx", "*.obj", "*.blend",
    "*.pdf", "*.doc", "*.docx", "*.xls", "*.xlsx", "*.ppt", "*.pptx",
    "*.db", "*.sqlite", "*.sqlite3",
    "*.lockb",
]

LANGUAGE_MAP = {
    ".c": "c", ".cc": "cpp", ".cpp": "cpp", ".cxx": "cpp",
    ".h": "cpp", ".hh": "cpp", ".hpp": "cpp", ".hxx": "cpp",
    ".cs": "csharp",
    ".lua": "lua", ".otui": "text", ".otmod": "text",
    ".py": "python",
    ".js": "javascript", ".jsx": "jsx", ".ts": "typescript", ".tsx": "tsx",
    ".mjs": "javascript", ".cjs": "javascript",
    ".java": "java", ".kt": "kotlin", ".kts": "kotlin",
    ".go": "go", ".rs": "rust",
    ".php": "php", ".rb": "ruby", ".swift": "swift",
    ".html": "html", ".htm": "html",
    ".css": "css", ".scss": "scss", ".sass": "sass", ".less": "less",
    ".xml": "xml", ".json": "json", ".jsonc": "json",
    ".yaml": "yaml", ".yml": "yaml", ".toml": "toml",
    ".ini": "ini", ".cfg": "text", ".conf": "text",
    ".sql": "sql",
    ".md": "markdown", ".txt": "text", ".rst": "rst",
    ".sh": "bash", ".bash": "bash", ".zsh": "bash",
    ".ps1": "powershell", ".bat": "bat", ".cmd": "bat",
    ".cmake": "cmake", ".gradle": "gradle", ".proto": "protobuf",
}


@dataclass
class ScanRow:
    path: str
    status: str
    reason: str
    size_bytes: int
    lines: int
    group: str
    sha256: str = ""


@dataclass
class SourceFile:
    path: str
    absolute_path: str
    group: str
    sha256: str
    lines: int
    bytes: int
    bundle: str = ""
    part_count: int = 1


@dataclass
class ExportResult:
    scanned: int
    exported: int
    ignored: int
    source_lines: int
    estimated_tokens: int
    bundles: int
    output_dir: str
    added: int
    modified: int
    removed: int
    folder_counts: dict[str, int]


def default_config() -> dict:
    return {
        "selected_roots": [],
        "extensions": list(DEFAULT_EXTENSIONS),
        "special_filenames": list(DEFAULT_SPECIAL_FILENAMES),
        "ignore_dirs": list(DEFAULT_IGNORE_DIRS),
        "ignore_globs": list(DEFAULT_IGNORE_GLOBS),
        "exclude_path_prefixes": [],
        "max_lines_per_bundle": DEFAULT_MAX_LINES,
        "max_source_file_mb": DEFAULT_MAX_SOURCE_MB,
        "include_root_files": True,
        "respect_gitignore": True,
        "include_git_diff": True,
        "git_diff_max_lines": 5000,
    }


def normalize_rel(path: Path) -> str:
    return path.as_posix()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_config(project_root: Path) -> dict:
    cfg = default_config()
    path = project_root / CONFIG_FILENAME
    if path.exists():
        try:
            user = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(user, dict):
                cfg.update(user)
        except Exception:
            pass
    return cfg


def save_config(project_root: Path, cfg: dict) -> Path:
    path = project_root / CONFIG_FILENAME
    path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def read_text_file(path: Path) -> tuple[str, str]:
    data = path.read_bytes()
    if b"\x00" in data:
        raise UnicodeError("binary/NUL")
    for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return data.decode(enc), enc
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace"), "utf-8-replace"


def count_lines(text: str) -> int:
    return len(text.splitlines()) if text else 0


class GitIgnoreMatcher:
    """Small .gitignore matcher covering common rules."""

    def __init__(self, root: Path):
        self.rules: list[tuple[str, bool, bool]] = []
        path = root / ".gitignore"
        if not path.exists():
            return
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return

        for raw in text.splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            negated = line.startswith("!")
            if negated:
                line = line[1:]
            directory_only = line.endswith("/")
            line = line.rstrip("/").replace("\\", "/")
            if line:
                self.rules.append((line, negated, directory_only))

    @staticmethod
    def _matches(rel: str, pattern: str) -> bool:
        rel = rel.lstrip("./")
        anchored = pattern.startswith("/")
        pat = pattern.lstrip("/")
        if anchored:
            return fnmatch.fnmatch(rel, pat)
        if "/" in pat:
            return fnmatch.fnmatch(rel, pat) or fnmatch.fnmatch(rel, f"*/{pat}")
        return any(fnmatch.fnmatch(part, pat) for part in rel.split("/"))

    def ignored(self, rel: str, is_dir: bool) -> bool:
        state = False
        rel = rel.replace("\\", "/").lstrip("./")
        for pattern, negated, directory_only in self.rules:
            matched = False
            if directory_only:
                segments = rel.split("/")
                parents = ["/".join(segments[:i + 1]) for i in range(len(segments))]
                matched = any(self._matches(parent, pattern) for parent in parents)
            else:
                matched = self._matches(rel, pattern)

            if matched:
                state = not negated
        return state


def top_group(rel: Path) -> str:
    return rel.parts[0] if len(rel.parts) > 1 else "ROOT"


def language_for(path: str) -> str:
    p = Path(path)
    if p.name == "CMakeLists.txt":
        return "cmake"
    if p.name in {"Dockerfile", "Makefile"}:
        return "text"
    return LANGUAGE_MAP.get(p.suffix.lower(), "text")


def matches_excluded_prefix(rel: str, prefixes: Iterable[str]) -> Optional[str]:
    normalized = rel.replace("\\", "/").strip("/")
    for raw in prefixes:
        prefix = str(raw).strip().replace("\\", "/").strip("/")
        if not prefix:
            continue
        if normalized == prefix or normalized.startswith(prefix + "/"):
            return prefix
    return None


def match_ignore_glob(rel: str, name: str, patterns: Iterable[str]) -> Optional[str]:
    rel_l = rel.lower()
    name_l = name.lower()
    for raw in patterns:
        pattern = str(raw).strip()
        if not pattern:
            continue
        p = pattern.lower()
        if fnmatch.fnmatch(name_l, p) or fnmatch.fnmatch(rel_l, p):
            return pattern
    return None


def classify_file(
    path: Path,
    root: Path,
    output_dir: Path,
    cfg: dict,
    gitignore: GitIgnoreMatcher,
) -> tuple[str, str]:
    rel = path.relative_to(root)
    rel_str = normalize_rel(rel)

    try:
        path.resolve().relative_to(output_dir.resolve())
        return "Ignored", "generated output"
    except ValueError:
        pass

    for part in rel.parts[:-1]:
        if part in set(cfg.get("ignore_dirs", [])):
            return "Ignored", f"ignored directory: {part}"

    selected_roots = set(cfg.get("selected_roots", []))
    if len(rel.parts) > 1 and selected_roots and rel.parts[0] not in selected_roots:
        return "Ignored", f"folder not selected: {rel.parts[0]}"

    if len(rel.parts) == 1 and not cfg.get("include_root_files", True):
        return "Ignored", "root files disabled"

    excluded = matches_excluded_prefix(rel_str, cfg.get("exclude_path_prefixes", []))
    if excluded:
        return "Ignored", f"excluded path: {excluded}"

    pattern = match_ignore_glob(rel_str, path.name, cfg.get("ignore_globs", []))
    if pattern:
        return "Ignored", f"ignored pattern: {pattern}"

    if cfg.get("respect_gitignore", True) and gitignore.ignored(rel_str, False):
        return "Ignored", ".gitignore"

    try:
        size = path.stat().st_size
    except Exception:
        return "Ignored", "cannot read metadata"

    max_bytes = int(float(cfg.get("max_source_file_mb", DEFAULT_MAX_SOURCE_MB)) * 1024 * 1024)
    if size > max_bytes:
        return "Ignored", f"larger than {cfg.get('max_source_file_mb')} MB"

    if path.name in set(cfg.get("special_filenames", [])):
        return "Included", "special filename"

    ext = path.suffix.lower()
    allowed = {str(x).lower() for x in cfg.get("extensions", [])}
    if ext not in allowed:
        return "Ignored", f"extension not included: {ext or '(none)'}"

    try:
        sample = path.read_bytes()[:4096]
        if b"\x00" in sample:
            return "Ignored", "binary file"
    except Exception:
        return "Ignored", "cannot read file"

    return "Included", "source file"


def scan_project(
    root: Path,
    output_dir: Path,
    cfg: dict,
    progress=None,
) -> list[ScanRow]:
    root = root.resolve()
    output_dir = output_dir.resolve()
    matcher = GitIgnoreMatcher(root)
    rows: list[ScanRow] = []
    seen = 0

    def emit(msg: str):
        if progress:
            progress(msg)

    # IMPORTANT:
    # We only prune known globally ignored folders / generated output.
    # We do NOT prune unselected top-level folders here. That lets Preview show
    # "folder not selected" instead of silently hiding them.
    ignore_dirs = set(cfg.get("ignore_dirs", []))

    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        current = Path(dirpath)

        kept = []
        for d in dirnames:
            candidate = current / d
            rel = candidate.relative_to(root)

            if d in ignore_dirs:
                continue

            try:
                candidate.resolve().relative_to(output_dir)
                continue
            except ValueError:
                pass

            excluded = matches_excluded_prefix(normalize_rel(rel), cfg.get("exclude_path_prefixes", []))
            if excluded:
                continue

            # Keep gitignored directories traversable only if needed? For speed,
            # prune them because the reason is already defined by .gitignore.
            if cfg.get("respect_gitignore", True) and matcher.ignored(normalize_rel(rel), True):
                continue

            kept.append(d)

        dirnames[:] = kept

        for filename in filenames:
            path = current / filename
            seen += 1
            status, reason = classify_file(path, root, output_dir, cfg, matcher)
            rel = path.relative_to(root)
            size = 0
            lines = 0
            sha = ""

            try:
                size = path.stat().st_size
            except Exception:
                pass

            if status == "Included":
                try:
                    data = path.read_bytes()
                    text, _ = read_text_file(path)
                    lines = count_lines(text)
                    sha = sha256_bytes(data)
                except Exception as exc:
                    status = "Ignored"
                    reason = f"read error: {exc}"

            rows.append(ScanRow(
                path=normalize_rel(rel),
                status=status,
                reason=reason,
                size_bytes=size,
                lines=lines,
                group=top_group(rel),
                sha256=sha,
            ))

            if seen % 300 == 0:
                emit(f"Scanning... {seen:,} files")

    rows.sort(key=lambda r: r.path.lower())
    return rows


def longest_backtick_run(text: str) -> int:
    runs = re.findall(r"`+", text)
    return max((len(x) for x in runs), default=0)


def markdown_fence(text: str) -> str:
    return "`" * max(3, longest_backtick_run(text) + 1)


def render_section(
    sf: SourceFile,
    source_lines: list[str],
    part: Optional[tuple[int, int]] = None,
) -> list[str]:
    label = sf.path
    if part:
        label += f" [PART {part[0]}/{part[1]}]"

    content = "\n".join(source_lines)
    fence = markdown_fence(content)
    lang = language_for(sf.path)

    result = [
        "",
        "---",
        f"## FROM: `{label}`",
        f"- SHA256: `{sf.sha256}`",
        f"- SOURCE_LINES: {sf.lines}",
        f"- SOURCE_BYTES: {sf.bytes}",
        "",
        f"{fence}{lang}",
    ]
    result.extend(source_lines)
    result += [fence, ""]
    return result


def split_source_sections(sf: SourceFile, text: str, usable_lines: int) -> list[list[str]]:
    lines = text.splitlines()
    section = render_section(sf, lines)
    if len(section) <= usable_lines:
        return [section]

    overhead = len(render_section(sf, [], part=(1, 999999)))
    capacity = usable_lines - overhead - 1
    if capacity < 1:
        raise RuntimeError("Bundle line limit is too small.")

    chunks = [lines[i:i + capacity] for i in range(0, len(lines), capacity)]
    sf.part_count = len(chunks)
    return [
        render_section(sf, chunk, part=(i, len(chunks)))
        for i, chunk in enumerate(chunks, 1)
    ]


def safe_group_name(group: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", group.strip()) or "ROOT"


def cleanup_generated_files(output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    exact = {
        "00_PROJECT_INDEX.md",
        "01_AI_INSTRUCTIONS.md",
        "02_CODE_MAP.md",
        "98_RECENT_CHANGES.md",
        "99_PROJECT_TREE.md",
    }
    for p in output_dir.iterdir():
        if not p.is_file():
            continue
        if p.name in exact or re.match(r"^\d{2}_.+_\d{3}\.md$", p.name):
            try:
                p.unlink()
            except OSError:
                pass


def write_bundle(path: Path, group: str, body: list[str], max_lines: int) -> None:
    prefix = [
        f"# {APP_NAME} — {group}",
        "",
        f"> Generated by {APP_NAME} v{APP_VERSION}. Do not edit manually.",
        f"> Hard maximum: {max_lines} lines.",
        "",
    ]
    lines = prefix + body
    if len(lines) > max_lines:
        raise RuntimeError(f"{path.name}: {len(lines)} lines > {max_lines}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def generate_bundles(
    sources: list[tuple[SourceFile, str]],
    output_dir: Path,
    max_lines: int,
) -> list[Path]:
    groups: dict[str, list[tuple[SourceFile, str]]] = {}
    for sf, text in sources:
        groups.setdefault(sf.group, []).append((sf, text))

    ordered = sorted(groups, key=lambda g: (g != "ROOT", g.lower()))
    created: list[Path] = []
    ordinal = 0
    usable = max_lines - 5

    for group in ordered:
        ordinal += 10
        seq = 1
        body: list[str] = []
        current_files: list[SourceFile] = []

        def flush():
            nonlocal seq, body, current_files
            if not body:
                return
            filename = f"{ordinal:02d}_{safe_group_name(group)}_{seq:03d}.md"
            out = output_dir / filename
            write_bundle(out, group, body, max_lines)
            for sf in current_files:
                if not sf.bundle:
                    sf.bundle = filename
                elif filename not in sf.bundle.split(" | "):
                    sf.bundle += " | " + filename
            created.append(out)
            seq += 1
            body = []
            current_files = []

        for sf, text in groups[group]:
            sections = split_source_sections(sf, text, usable)
            for section in sections:
                if body and len(body) + len(section) > usable:
                    flush()
                if len(section) > usable:
                    raise RuntimeError(f"Section too large: {sf.path}")
                body.extend(section)
                if sf not in current_files:
                    current_files.append(sf)

        flush()

    return created


def run_git(root: Path, args: list[str]) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        return proc.returncode, proc.stdout + (("\n" + proc.stderr) if proc.stderr else "")
    except Exception as exc:
        return 1, str(exc)


def git_metadata(root: Path) -> dict:
    result = {"branch": "", "head": ""}
    code, branch = run_git(root, ["branch", "--show-current"])
    if code == 0:
        result["branch"] = branch.strip()
    code, head = run_git(root, ["rev-parse", "HEAD"])
    if code == 0:
        result["head"] = head.strip()
    return result


def git_working_tree_text(root: Path, output_dir: Path, max_lines: int) -> str:
    code, inside = run_git(root, ["rev-parse", "--is-inside-work-tree"])
    if code != 0 or "true" not in inside.lower():
        return "_Git repository not detected._\n"

    result: list[str] = []
    meta = git_metadata(root)

    result += ["## Branch", "", f"`{meta.get('branch') or '(detached HEAD)'}`", ""]
    result += ["## HEAD", "", f"`{meta.get('head') or '(unknown)'}`", ""]

    _, status = run_git(root, ["status", "--short"])

    # Filter the generator's own output from status.
    filtered_status = []
    try:
        rel_output = output_dir.resolve().relative_to(root.resolve()).as_posix().rstrip("/") + "/"
    except ValueError:
        rel_output = ""

    for line in status.splitlines():
        candidate = line[3:].strip().replace("\\", "/") if len(line) >= 4 else line.strip()
        if rel_output and (candidate == rel_output.rstrip("/") or candidate.startswith(rel_output)):
            continue
        filtered_status.append(line)

    result += ["## Git status", "", "```text", "\n".join(filtered_status).strip() or "(clean)", "```", ""]

    _, diff = run_git(root, ["diff", "--no-ext-diff", "--unified=3"])
    diff_lines = diff.splitlines()[:max_lines]
    result += ["## Unstaged diff", "", "```diff"]
    result.extend(diff_lines or ["# no unstaged diff"])
    result += ["```", ""]

    _, staged = run_git(root, ["diff", "--cached", "--no-ext-diff", "--unified=3"])
    staged_lines = staged.splitlines()[:max_lines]
    result += ["## Staged diff", "", "```diff"]
    result.extend(staged_lines or ["# no staged diff"])
    result += ["```", ""]

    return "\n".join(result)


def load_previous_manifest(output_dir: Path) -> dict:
    path = output_dir / MANIFEST_FILENAME
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def compare_manifests(previous: dict, files: list[SourceFile]) -> tuple[list[str], list[str], list[str]]:
    old = {
        item.get("path"): item.get("sha256")
        for item in previous.get("files", [])
        if isinstance(item, dict) and item.get("path")
    }
    new = {f.path: f.sha256 for f in files}
    added = sorted(set(new) - set(old))
    removed = sorted(set(old) - set(new))
    modified = sorted(p for p in set(new) & set(old) if new[p] != old[p])
    return added, modified, removed


def build_tree(paths: list[str]) -> str:
    tree: dict = {}
    for path in paths:
        node = tree
        for part in path.split("/"):
            node = node.setdefault(part, {})

    out: list[str] = []

    def walk(node: dict, prefix: str = ""):
        items = sorted(node.items(), key=lambda kv: (not bool(kv[1]), kv[0].lower()))
        for i, (name, child) in enumerate(items):
            last = i == len(items) - 1
            out.append(prefix + ("└── " if last else "├── ") + name)
            if child:
                walk(child, prefix + ("    " if last else "│   "))

    walk(tree)
    return "\n".join(out)


def write_support_files(
    output_dir: Path,
    root: Path,
    files: list[SourceFile],
    bundles: list[Path],
    cfg: dict,
    added: list[str],
    modified: list[str],
    removed: list[str],
) -> None:
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    total_lines = sum(f.lines for f in files)
    total_bytes = sum(f.bytes for f in files)
    estimated_tokens = max(1, total_bytes // 4)
    git = git_metadata(root)

    common_header = [
        f"- Project: `{root}`",
        f"- Generated: `{now}`",
        f"- Git branch: `{git.get('branch') or '(not available)'}`",
        f"- Git HEAD: `{git.get('head') or '(not available)'}`",
    ]

    index = [
        f"# {APP_NAME} — Project Index",
        "",
        *common_header,
        f"- Exported source files: **{len(files)}**",
        f"- Source lines: **{total_lines:,}**",
        f"- Source bytes: **{total_bytes:,}**",
        f"- Bundles: **{len(bundles)}**",
        f"- Approximate raw-text tokens: **{estimated_tokens:,}**",
        "",
        "## Source folders",
        "",
        "| Folder | Files | Lines |",
        "|---|---:|---:|",
    ]

    folder_stats: dict[str, tuple[int, int]] = {}
    for f in files:
        count, lines = folder_stats.get(f.group, (0, 0))
        folder_stats[f.group] = (count + 1, lines + f.lines)

    for group, (count, lines) in sorted(folder_stats.items(), key=lambda kv: kv[0].lower()):
        index.append(f"| `{group}` | {count:,} | {lines:,} |")

    index += [
        "",
        "## Changes since previous snapshot",
        "",
        f"- Added: **{len(added)}**",
        f"- Modified: **{len(modified)}**",
        f"- Removed: **{len(removed)}**",
        "",
        "## Source map",
        "",
        "| Original source path | Bundle | Lines | Bytes | SHA256 |",
        "|---|---|---:|---:|---|",
    ]

    for f in files:
        index.append(
            f"| `{f.path}` | `{f.bundle}` | {f.lines} | {f.bytes:,} | `{f.sha256[:16]}` |"
        )

    (output_dir / "00_PROJECT_INDEX.md").write_text("\n".join(index) + "\n", encoding="utf-8")

    instructions = [
        f"# {APP_NAME} — AI Instructions",
        "",
        "This folder is a generated textual snapshot of a software project.",
        "",
        "1. Use `00_PROJECT_INDEX.md` to locate the real source path and bundle.",
        "2. Use `02_CODE_MAP.md` for a compact map of the included source files.",
        "3. Use `98_RECENT_CHANGES.md` first when reviewing the user's latest edits.",
        "4. Always reference the original path after `FROM:` — never the generated bundle path.",
        "5. Prefer minimal changes and avoid unrelated refactors.",
        "6. When practical, answer with exact BEFORE and AFTER code blocks.",
        "",
        *common_header,
        "",
    ]
    (output_dir / "01_AI_INSTRUCTIONS.md").write_text("\n".join(instructions), encoding="utf-8")

    code_map = [
        f"# {APP_NAME} — Code Map",
        "",
        *common_header,
        "",
    ]
    by_group: dict[str, list[str]] = {}
    for f in files:
        by_group.setdefault(f.group, []).append(f.path)

    for group in sorted(by_group, key=str.lower):
        code_map += [f"## {group}", ""]
        for path in sorted(by_group[group], key=str.lower):
            code_map.append(f"- `{path}`")
        code_map.append("")

    (output_dir / "02_CODE_MAP.md").write_text("\n".join(code_map), encoding="utf-8")

    tree = [
        f"# {APP_NAME} — Project Tree",
        "",
        *common_header,
        "",
        "```text",
        build_tree([f.path for f in files]),
        "```",
        "",
    ]
    (output_dir / "99_PROJECT_TREE.md").write_text("\n".join(tree), encoding="utf-8")

    recent = [
        f"# {APP_NAME} — Recent Changes",
        "",
        *common_header,
        "",
        "## Snapshot comparison",
        "",
        f"- Added: {len(added)}",
        f"- Modified: {len(modified)}",
        f"- Removed: {len(removed)}",
        "",
    ]
    if added:
        recent += ["### Added", ""] + [f"- `{p}`" for p in added] + [""]
    if modified:
        recent += ["### Modified", ""] + [f"- `{p}`" for p in modified] + [""]
    if removed:
        recent += ["### Removed", ""] + [f"- `{p}`" for p in removed] + [""]

    if cfg.get("include_git_diff", True):
        recent += ["---", "", "# Git working tree", ""]
        recent.append(
            git_working_tree_text(
                root,
                output_dir,
                int(cfg.get("git_diff_max_lines", 5000)),
            )
        )

    (output_dir / "98_RECENT_CHANGES.md").write_text("\n".join(recent) + "\n", encoding="utf-8")

    manifest = {
        "app": APP_NAME,
        "version": APP_VERSION,
        "project_root": str(root),
        "generated_at": now,
        "git": git,
        "config": cfg,
        "bundles": [p.name for p in bundles],
        "files": [asdict(f) for f in files],
    }
    (output_dir / MANIFEST_FILENAME).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def validate_scan(cfg: dict, rows: list[ScanRow]) -> list[str]:
    warnings: list[str] = []
    included = [r for r in rows if r.status == "Included"]
    selected = list(cfg.get("selected_roots", []))

    counts: dict[str, int] = {}
    for row in included:
        counts[row.group] = counts.get(row.group, 0) + 1

    for folder in selected:
        if counts.get(folder, 0) == 0:
            warnings.append(f'Selected folder "{folder}" has 0 included files.')

    if not included:
        warnings.append("No source files are included.")

    return warnings


def export_project(
    root: Path,
    output_dir: Path,
    cfg: dict,
    progress=None,
) -> ExportResult:
    root = root.expanduser().resolve()
    output_dir = output_dir.expanduser().resolve()

    if not root.is_dir():
        raise ValueError(f"Invalid project folder: {root}")

    max_lines = int(cfg.get("max_lines_per_bundle", DEFAULT_MAX_LINES))
    if max_lines < 55:
        raise ValueError("Max lines per bundle must be at least 55.")

    def emit(msg: str):
        if progress:
            progress(msg)

    # ALWAYS rescan using the current settings.
    emit("Scanning project with current settings...")
    rows = scan_project(root, output_dir, cfg, progress=emit)

    warnings = validate_scan(cfg, rows)
    for warning in warnings:
        emit(f"WARNING: {warning}")

    included_rows = [r for r in rows if r.status == "Included"]
    if not included_rows:
        raise RuntimeError("Nothing to export. Review folders/ignore rules.")

    previous = load_previous_manifest(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    sources: list[tuple[SourceFile, str]] = []
    for i, row in enumerate(included_rows, 1):
        path = root / Path(row.path)
        data = path.read_bytes()
        text, _ = read_text_file(path)
        sf = SourceFile(
            path=row.path,
            absolute_path=str(path),
            group=row.group,
            sha256=sha256_bytes(data),
            lines=count_lines(text),
            bytes=len(data),
        )
        sources.append((sf, text))
        if i % 250 == 0:
            emit(f"Preparing sources... {i:,}/{len(included_rows):,}")

    files = [sf for sf, _ in sources]
    added, modified, removed = compare_manifests(previous, files)

    emit("Cleaning previous generated files...")
    cleanup_generated_files(output_dir)

    emit("Generating Markdown bundles...")
    bundles = generate_bundles(sources, output_dir, max_lines)

    emit("Writing index, code map, tree and recent changes...")
    write_support_files(
        output_dir, root, files, bundles, cfg, added, modified, removed
    )

    folder_counts: dict[str, int] = {}
    for f in files:
        folder_counts[f.group] = folder_counts.get(f.group, 0) + 1

    total_lines = sum(f.lines for f in files)
    total_bytes = sum(f.bytes for f in files)

    emit("Project Bible generated.")

    return ExportResult(
        scanned=len(rows),
        exported=len(files),
        ignored=len([r for r in rows if r.status == "Ignored"]),
        source_lines=total_lines,
        estimated_tokens=max(1, total_bytes // 4),
        bundles=len(bundles),
        output_dir=str(output_dir),
        added=len(added),
        modified=len(modified),
        removed=len(removed),
        folder_counts=folder_counts,
    )


# -----------------------------------------------------------------------------
# GUI
# -----------------------------------------------------------------------------

def launch_gui() -> None:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    class App(tk.Tk):
        def __init__(self):
            super().__init__()
            self.title(f"{APP_NAME} v{APP_VERSION}")
            self.geometry("1180x780")
            self.minsize(1000, 680)

            self.project_var = tk.StringVar()
            self.output_var = tk.StringVar()
            self.max_lines_var = tk.StringVar(value=str(DEFAULT_MAX_LINES))
            self.max_mb_var = tk.StringVar(value=str(DEFAULT_MAX_SOURCE_MB))
            self.gitignore_var = tk.BooleanVar(value=True)
            self.root_files_var = tk.BooleanVar(value=True)
            self.gitdiff_var = tk.BooleanVar(value=True)
            self.gitdiff_lines_var = tk.StringVar(value="5000")

            self.search_var = tk.StringVar()
            self.view_mode_var = tk.StringVar(value="All")
            self.stats_var = tk.StringVar(value="Choose a project, then click Scan.")
            self.status_var = tk.StringVar(value="Ready.")

            self.folder_vars: dict[str, tk.BooleanVar] = {}
            self.scan_rows: list[ScanRow] = []
            self.ui_queue: queue.Queue = queue.Queue()
            self.busy = False

            self._build()
            self.after(100, self._process_queue)

        def _style(self):
            style = ttk.Style(self)
            try:
                if sys.platform.startswith("win"):
                    style.theme_use("vista")
            except Exception:
                pass
            style.configure("Title.TLabel", font=("Segoe UI", 20, "bold"))
            style.configure("Subtitle.TLabel", font=("Segoe UI", 10))
            style.configure("Section.TLabel", font=("Segoe UI", 11, "bold"))
            style.configure("Primary.TButton", font=("Segoe UI", 10, "bold"), padding=7)

        def _build(self):
            self._style()

            header = ttk.Frame(self, padding=(16, 12, 16, 8))
            header.pack(fill="x")
            ttk.Label(header, text=APP_NAME, style="Title.TLabel").pack(anchor="w")
            ttk.Label(
                header,
                text="Create a searchable AI-readable snapshot of any source project.",
                style="Subtitle.TLabel",
            ).pack(anchor="w")

            notebook = ttk.Notebook(self)
            notebook.pack(fill="both", expand=True, padx=14, pady=(0, 8))

            self.main_tab = ttk.Frame(notebook, padding=14)
            self.advanced_tab = ttk.Frame(notebook, padding=14)
            notebook.add(self.main_tab, text="Project Bible")
            notebook.add(self.advanced_tab, text="Advanced Settings")

            self._build_main()
            self._build_advanced()

            footer = ttk.Frame(self, padding=(14, 0, 14, 10))
            footer.pack(fill="x")
            ttk.Label(footer, textvariable=self.status_var).pack(side="left")
            ttk.Button(footer, text="Save settings for this project", command=self.save_settings).pack(side="right")

        def _build_main(self):
            f = self.main_tab
            f.columnconfigure(0, weight=1)
            f.rowconfigure(3, weight=1)

            project_box = ttk.LabelFrame(f, text="Project", padding=10)
            project_box.grid(row=0, column=0, sticky="ew")
            project_box.columnconfigure(1, weight=1)

            ttk.Label(project_box, text="Source folder:").grid(row=0, column=0, sticky="w", pady=4)
            ttk.Entry(project_box, textvariable=self.project_var).grid(row=0, column=1, sticky="ew", padx=8, pady=4)
            ttk.Button(project_box, text="Browse...", command=self.choose_project).grid(row=0, column=2, pady=4)

            ttk.Label(project_box, text="Output folder:").grid(row=1, column=0, sticky="w", pady=4)
            ttk.Entry(project_box, textvariable=self.output_var).grid(row=1, column=1, sticky="ew", padx=8, pady=4)
            ttk.Button(project_box, text="Browse...", command=self.choose_output).grid(row=1, column=2, pady=4)

            options_row = ttk.Frame(project_box)
            options_row.grid(row=2, column=0, columnspan=3, sticky="w", pady=(8, 0))
            ttk.Label(options_row, text="Max lines per bundle:").pack(side="left")
            ttk.Spinbox(options_row, from_=55, to=1000000, textvariable=self.max_lines_var, width=9).pack(side="left", padx=(6, 18))
            ttk.Checkbutton(options_row, text="Respect .gitignore", variable=self.gitignore_var).pack(side="left")

            folder_box = ttk.LabelFrame(f, text="Folders to include", padding=10)
            folder_box.grid(row=1, column=0, sticky="ew", pady=(10, 0))
            folder_box.columnconfigure(0, weight=1)

            ttk.Label(
                folder_box,
                text="Check the project folders that should enter the Bible. Root files are controlled in Advanced Settings.",
            ).grid(row=0, column=0, sticky="w", pady=(0, 6))

            folder_host = ttk.Frame(folder_box)
            folder_host.grid(row=1, column=0, sticky="ew")
            folder_host.columnconfigure(0, weight=1)

            self.folder_canvas = tk.Canvas(folder_host, height=120, highlightthickness=1, highlightbackground="#c8c8c8")
            folder_scroll = ttk.Scrollbar(folder_host, orient="vertical", command=self.folder_canvas.yview)
            self.folder_canvas.configure(yscrollcommand=folder_scroll.set)
            self.folder_canvas.grid(row=0, column=0, sticky="ew")
            folder_scroll.grid(row=0, column=1, sticky="ns")

            self.folder_inner = ttk.Frame(self.folder_canvas)
            self.folder_window = self.folder_canvas.create_window((0, 0), window=self.folder_inner, anchor="nw")
            self.folder_inner.bind("<Configure>", self._folder_scrollregion)
            self.folder_canvas.bind("<Configure>", self._folder_width)

            folder_buttons = ttk.Frame(folder_box)
            folder_buttons.grid(row=2, column=0, sticky="w", pady=(7, 0))
            ttk.Button(folder_buttons, text="Select all", command=self.select_all_folders).pack(side="left")
            ttk.Button(folder_buttons, text="Clear", command=self.clear_folders).pack(side="left", padx=6)

            action_bar = ttk.Frame(f)
            action_bar.grid(row=2, column=0, sticky="ew", pady=10)

            self.scan_btn = ttk.Button(action_bar, text="SCAN PROJECT", style="Primary.TButton", command=self.start_scan)
            self.scan_btn.pack(side="left")
            self.generate_btn = ttk.Button(action_bar, text="GENERATE BIBLE", style="Primary.TButton", command=self.start_generate)
            self.generate_btn.pack(side="left", padx=8)
            ttk.Button(action_bar, text="Open output", command=self.open_output).pack(side="left")

            ttk.Label(action_bar, textvariable=self.stats_var).pack(side="right")

            preview_box = ttk.LabelFrame(f, text="Preview", padding=8)
            preview_box.grid(row=3, column=0, sticky="nsew")
            preview_box.columnconfigure(0, weight=1)
            preview_box.rowconfigure(1, weight=1)

            filters = ttk.Frame(preview_box)
            filters.grid(row=0, column=0, sticky="ew", pady=(0, 6))
            filters.columnconfigure(1, weight=1)
            ttk.Label(filters, text="Search:").grid(row=0, column=0, sticky="w")
            ttk.Entry(filters, textvariable=self.search_var).grid(row=0, column=1, sticky="ew", padx=6)
            ttk.Label(filters, text="Show:").grid(row=0, column=2, padx=(12, 4))
            mode = ttk.Combobox(
                filters,
                textvariable=self.view_mode_var,
                state="readonly",
                values=["All", "Included", "Ignored"],
                width=10,
            )
            mode.grid(row=0, column=3)
            mode.bind("<<ComboboxSelected>>", lambda _e: self.refresh_preview())
            self.search_var.trace_add("write", lambda *_: self.refresh_preview())

            table_host = ttk.Frame(preview_box)
            table_host.grid(row=1, column=0, sticky="nsew")
            table_host.columnconfigure(0, weight=1)
            table_host.rowconfigure(0, weight=1)

            cols = ("status", "path", "reason", "lines", "size")
            self.tree = ttk.Treeview(table_host, columns=cols, show="headings")
            self.tree.heading("status", text="Status")
            self.tree.heading("path", text="Original source path")
            self.tree.heading("reason", text="Reason")
            self.tree.heading("lines", text="Lines")
            self.tree.heading("size", text="Size")

            self.tree.column("status", width=80, stretch=False)
            self.tree.column("path", width=520)
            self.tree.column("reason", width=260)
            self.tree.column("lines", width=80, anchor="e", stretch=False)
            self.tree.column("size", width=85, anchor="e", stretch=False)

            sy = ttk.Scrollbar(table_host, orient="vertical", command=self.tree.yview)
            sx = ttk.Scrollbar(table_host, orient="horizontal", command=self.tree.xview)
            self.tree.configure(yscrollcommand=sy.set, xscrollcommand=sx.set)

            self.tree.grid(row=0, column=0, sticky="nsew")
            sy.grid(row=0, column=1, sticky="ns")
            sx.grid(row=1, column=0, sticky="ew")

        def _build_advanced(self):
            f = self.advanced_tab
            f.columnconfigure(0, weight=1)
            f.columnconfigure(1, weight=1)
            f.rowconfigure(1, weight=1)

            ttk.Label(f, text="Included source extensions", style="Section.TLabel").grid(row=0, column=0, sticky="w")
            ttk.Label(f, text="Ignored directory names", style="Section.TLabel").grid(row=0, column=1, sticky="w", padx=(14, 0))

            self.extensions_text = tk.Text(f, wrap="none")
            self.extensions_text.grid(row=1, column=0, sticky="nsew", pady=(5, 10))

            self.ignore_dirs_text = tk.Text(f, wrap="none")
            self.ignore_dirs_text.grid(row=1, column=1, sticky="nsew", padx=(14, 0), pady=(5, 10))

            ttk.Label(f, text="Ignored file/path patterns", style="Section.TLabel").grid(row=2, column=0, sticky="w")
            ttk.Label(f, text="Specific relative paths to exclude", style="Section.TLabel").grid(row=2, column=1, sticky="w", padx=(14, 0))

            self.ignore_globs_text = tk.Text(f, height=12, wrap="none")
            self.ignore_globs_text.grid(row=3, column=0, sticky="ew", pady=(5, 10))

            self.exclude_paths_text = tk.Text(f, height=12, wrap="none")
            self.exclude_paths_text.grid(row=3, column=1, sticky="ew", padx=(14, 0), pady=(5, 10))

            ttk.Label(f, text="Special filenames (included even without normal extension)", style="Section.TLabel").grid(row=4, column=0, columnspan=2, sticky="w")
            self.special_text = tk.Text(f, height=7, wrap="none")
            self.special_text.grid(row=5, column=0, columnspan=2, sticky="ew", pady=(5, 10))

            opts = ttk.LabelFrame(f, text="Other options", padding=10)
            opts.grid(row=6, column=0, columnspan=2, sticky="ew")

            ttk.Checkbutton(opts, text="Include files directly in project root", variable=self.root_files_var).pack(side="left")
            ttk.Checkbutton(opts, text="Include Git status and diff", variable=self.gitdiff_var).pack(side="left", padx=16)

            ttk.Label(opts, text="Max source file (MB):").pack(side="left")
            ttk.Spinbox(opts, from_=0.1, to=1000, increment=0.1, textvariable=self.max_mb_var, width=7).pack(side="left", padx=(5, 16))

            ttk.Label(opts, text="Git diff max lines:").pack(side="left")
            ttk.Spinbox(opts, from_=0, to=1000000, textvariable=self.gitdiff_lines_var, width=8).pack(side="left", padx=5)

            buttons = ttk.Frame(f)
            buttons.grid(row=7, column=0, columnspan=2, sticky="w", pady=(10, 0))
            ttk.Button(buttons, text="Restore recommended defaults", command=self.restore_defaults).pack(side="left")

            self.restore_defaults()

        def _folder_scrollregion(self, _event=None):
            self.folder_canvas.configure(scrollregion=self.folder_canvas.bbox("all"))

        def _folder_width(self, event):
            self.folder_canvas.itemconfigure(self.folder_window, width=event.width)

        @staticmethod
        def _set_lines(widget, values):
            widget.delete("1.0", "end")
            widget.insert("1.0", "\n".join(values))

        @staticmethod
        def _get_lines(widget):
            return [line.strip() for line in widget.get("1.0", "end").splitlines() if line.strip()]

        def restore_defaults(self):
            self._set_lines(self.extensions_text, DEFAULT_EXTENSIONS)
            self._set_lines(self.ignore_dirs_text, DEFAULT_IGNORE_DIRS)
            self._set_lines(self.ignore_globs_text, DEFAULT_IGNORE_GLOBS)
            self._set_lines(self.exclude_paths_text, [])
            self._set_lines(self.special_text, DEFAULT_SPECIAL_FILENAMES)
            self.max_mb_var.set(str(DEFAULT_MAX_SOURCE_MB))
            self.root_files_var.set(True)
            self.gitdiff_var.set(True)
            self.gitdiff_lines_var.set("5000")

        def current_config(self):
            try:
                max_lines = int(self.max_lines_var.get())
                max_mb = float(self.max_mb_var.get())
                git_lines = int(self.gitdiff_lines_var.get())
            except ValueError as exc:
                raise ValueError("One of the numeric settings is invalid.") from exc

            selected_roots = [name for name, var in self.folder_vars.items() if var.get()]

            return {
                "selected_roots": selected_roots,
                "extensions": self._get_lines(self.extensions_text),
                "special_filenames": self._get_lines(self.special_text),
                "ignore_dirs": self._get_lines(self.ignore_dirs_text),
                "ignore_globs": self._get_lines(self.ignore_globs_text),
                "exclude_path_prefixes": self._get_lines(self.exclude_paths_text),
                "max_lines_per_bundle": max_lines,
                "max_source_file_mb": max_mb,
                "include_root_files": self.root_files_var.get(),
                "respect_gitignore": self.gitignore_var.get(),
                "include_git_diff": self.gitdiff_var.get(),
                "git_diff_max_lines": git_lines,
            }

        def apply_config(self, cfg):
            self.max_lines_var.set(str(cfg.get("max_lines_per_bundle", DEFAULT_MAX_LINES)))
            self.max_mb_var.set(str(cfg.get("max_source_file_mb", DEFAULT_MAX_SOURCE_MB)))
            self.root_files_var.set(bool(cfg.get("include_root_files", True)))
            self.gitignore_var.set(bool(cfg.get("respect_gitignore", True)))
            self.gitdiff_var.set(bool(cfg.get("include_git_diff", True)))
            self.gitdiff_lines_var.set(str(cfg.get("git_diff_max_lines", 5000)))

            self._set_lines(self.extensions_text, cfg.get("extensions", DEFAULT_EXTENSIONS))
            self._set_lines(self.special_text, cfg.get("special_filenames", DEFAULT_SPECIAL_FILENAMES))
            self._set_lines(self.ignore_dirs_text, cfg.get("ignore_dirs", DEFAULT_IGNORE_DIRS))
            self._set_lines(self.ignore_globs_text, cfg.get("ignore_globs", DEFAULT_IGNORE_GLOBS))
            self._set_lines(self.exclude_paths_text, cfg.get("exclude_path_prefixes", []))

            selected = set(cfg.get("selected_roots", []))
            for name, var in self.folder_vars.items():
                var.set(name in selected if selected else True)

        def choose_project(self):
            path = filedialog.askdirectory(title="Choose project folder")
            if not path:
                return

            root = Path(path)
            self.project_var.set(str(root))
            self.output_var.set(str(root / DEFAULT_OUTPUT_DIRNAME))
            self.load_folder_checkboxes(root)
            self.apply_config(load_config(root))
            self.scan_rows = []
            self.refresh_preview()
            self.status_var.set(f"Loaded: {root.name}")

        def choose_output(self):
            path = filedialog.askdirectory(title="Choose output folder")
            if path:
                self.output_var.set(path)

        def load_folder_checkboxes(self, root: Path):
            for child in self.folder_inner.winfo_children():
                child.destroy()
            self.folder_vars.clear()

            try:
                ignored = set(DEFAULT_IGNORE_DIRS)
                folders = sorted(
                    [
                        p.name
                        for p in root.iterdir()
                        if p.is_dir()
                        and p.name not in ignored
                        and p.name != DEFAULT_OUTPUT_DIRNAME
                    ],
                    key=str.lower,
                )
            except Exception as exc:
                messagebox.showerror(APP_NAME, str(exc))
                return

            columns = 4
            for index, name in enumerate(folders):
                var = tk.BooleanVar(value=True)
                self.folder_vars[name] = var
                cb = ttk.Checkbutton(self.folder_inner, text=name, variable=var)
                cb.grid(row=index // columns, column=index % columns, sticky="w", padx=(0, 28), pady=3)

            for col in range(columns):
                self.folder_inner.columnconfigure(col, weight=1)

            self._folder_scrollregion()

        def select_all_folders(self):
            for var in self.folder_vars.values():
                var.set(True)

        def clear_folders(self):
            for var in self.folder_vars.values():
                var.set(False)

        def validate_paths(self):
            root = Path(self.project_var.get()).expanduser()
            if not root.is_dir():
                raise ValueError("Choose a valid source project folder.")
            output_text = self.output_var.get().strip()
            output = Path(output_text).expanduser() if output_text else root / DEFAULT_OUTPUT_DIRNAME
            return root, output

        def start_scan(self):
            if self.busy:
                return
            try:
                root, output = self.validate_paths()
                cfg = self.current_config()
            except Exception as exc:
                messagebox.showerror(APP_NAME, str(exc))
                return

            self.busy = True
            self.scan_btn.configure(state="disabled")
            self.generate_btn.configure(state="disabled")
            self.status_var.set("Scanning...")

            def worker():
                try:
                    rows = scan_project(
                        root,
                        output,
                        cfg,
                        progress=lambda m: self.ui_queue.put(("status", m)),
                    )
                    self.ui_queue.put(("scan_done", (rows, cfg)))
                except Exception as exc:
                    self.ui_queue.put(("error", str(exc)))
                finally:
                    self.ui_queue.put(("idle", None))

            threading.Thread(target=worker, daemon=True).start()

        def start_generate(self):
            if self.busy:
                return
            try:
                root, output = self.validate_paths()
                cfg = self.current_config()
            except Exception as exc:
                messagebox.showerror(APP_NAME, str(exc))
                return

            self.busy = True
            self.scan_btn.configure(state="disabled")
            self.generate_btn.configure(state="disabled")
            self.status_var.set("Generating...")

            def worker():
                try:
                    result = export_project(
                        root,
                        output,
                        cfg,
                        progress=lambda m: self.ui_queue.put(("status", m)),
                    )
                    self.ui_queue.put(("generate_done", result))
                except Exception as exc:
                    self.ui_queue.put(("error", str(exc)))
                finally:
                    self.ui_queue.put(("idle", None))

            threading.Thread(target=worker, daemon=True).start()

        @staticmethod
        def human_size(size):
            value = float(size)
            for unit in ("B", "KB", "MB", "GB"):
                if value < 1024 or unit == "GB":
                    return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
                value /= 1024
            return str(size)

        def refresh_preview(self):
            if not hasattr(self, "tree"):
                return

            self.tree.delete(*self.tree.get_children())
            query = self.search_var.get().strip().lower()
            mode = self.view_mode_var.get()

            visible = 0
            for row in self.scan_rows:
                if mode != "All" and row.status != mode:
                    continue
                if query and query not in f"{row.path} {row.reason}".lower():
                    continue

                self.tree.insert(
                    "",
                    "end",
                    values=(
                        row.status,
                        row.path,
                        row.reason,
                        f"{row.lines:,}" if row.lines else "",
                        self.human_size(row.size_bytes),
                    ),
                )
                visible += 1

            included = [r for r in self.scan_rows if r.status == "Included"]
            total_lines = sum(r.lines for r in included)
            total_bytes = sum(r.size_bytes for r in included)
            tokens = total_bytes // 4 if included else 0

            folder_counts = {}
            for r in included:
                folder_counts[r.group] = folder_counts.get(r.group, 0) + 1

            folder_summary = ", ".join(
                f"{k}: {v:,}"
                for k, v in sorted(folder_counts.items(), key=lambda kv: kv[0].lower())
            )

            self.stats_var.set(
                f"Included {len(included):,} files | {total_lines:,} lines | ~{tokens:,} tokens"
                + (f" | {folder_summary}" if folder_summary else "")
            )

        def save_settings(self):
            try:
                root, _ = self.validate_paths()
                path = save_config(root, self.current_config())
                self.status_var.set(f"Saved {path.name}")
                messagebox.showinfo(APP_NAME, f"Settings saved:\n{path}")
            except Exception as exc:
                messagebox.showerror(APP_NAME, str(exc))

        def open_output(self):
            try:
                _, output = self.validate_paths()
                if not output.exists():
                    messagebox.showwarning(APP_NAME, "Output folder does not exist yet.")
                    return

                if sys.platform.startswith("win"):
                    os.startfile(str(output))  # type: ignore[attr-defined]
                elif sys.platform == "darwin":
                    subprocess.Popen(["open", str(output)])
                else:
                    subprocess.Popen(["xdg-open", str(output)])
            except Exception as exc:
                messagebox.showerror(APP_NAME, str(exc))

        def _process_queue(self):
            try:
                while True:
                    kind, payload = self.ui_queue.get_nowait()

                    if kind == "status":
                        self.status_var.set(str(payload))

                    elif kind == "scan_done":
                        rows, cfg = payload
                        self.scan_rows = rows
                        self.refresh_preview()
                        warnings = validate_scan(cfg, rows)
                        self.status_var.set("Scan complete.")
                        if warnings:
                            messagebox.showwarning(
                                APP_NAME,
                                "Scan completed with warnings:\n\n" + "\n".join(f"• {w}" for w in warnings),
                            )

                    elif kind == "generate_done":
                        result = payload
                        self.status_var.set("Bible generated successfully.")
                        folder_text = "\n".join(
                            f"{name}: {count:,} files"
                            for name, count in sorted(result.folder_counts.items(), key=lambda kv: kv[0].lower())
                        )
                        messagebox.showinfo(
                            APP_NAME,
                            "Project Bible generated!\n\n"
                            f"Source files: {result.exported:,}\n"
                            f"Bundles: {result.bundles:,}\n"
                            f"Source lines: {result.source_lines:,}\n"
                            f"Approx. raw tokens: {result.estimated_tokens:,}\n\n"
                            f"{folder_text}\n\n"
                            f"Output:\n{result.output_dir}",
                        )

                    elif kind == "error":
                        self.status_var.set("Error.")
                        messagebox.showerror(APP_NAME, str(payload))

                    elif kind == "idle":
                        self.busy = False
                        self.scan_btn.configure(state="normal")
                        self.generate_btn.configure(state="normal")

            except queue.Empty:
                pass

            self.after(100, self._process_queue)

    App().mainloop()


def build_parser():
    p = argparse.ArgumentParser(description=APP_NAME)
    p.add_argument("--project")
    p.add_argument("--output")
    p.add_argument("--roots", nargs="*")
    p.add_argument("--max-lines", type=int)
    p.add_argument("--no-gitignore", action="store_true")
    p.add_argument("--no-git-diff", action="store_true")
    p.add_argument("--gui", action="store_true")
    return p


def main():
    args = build_parser().parse_args()

    if args.gui or not args.project:
        launch_gui()
        return 0

    root = Path(args.project).expanduser().resolve()
    if not root.is_dir():
        print(f"Invalid project: {root}", file=sys.stderr)
        return 2

    cfg = load_config(root)
    if args.roots is not None:
        cfg["selected_roots"] = args.roots
    if args.max_lines is not None:
        cfg["max_lines_per_bundle"] = args.max_lines
    if args.no_gitignore:
        cfg["respect_gitignore"] = False
    if args.no_git_diff:
        cfg["include_git_diff"] = False

    output = Path(args.output).expanduser().resolve() if args.output else root / DEFAULT_OUTPUT_DIRNAME

    result = export_project(root, output, cfg, progress=print)
    print(json.dumps(asdict(result), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
