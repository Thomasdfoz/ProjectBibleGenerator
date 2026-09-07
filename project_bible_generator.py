#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Project Bible Generator v2
Turn any project into an AI-readable code bible.

GUI-first, standard-library-only utility.

Main features
-------------
- Choose source project and output folder.
- Select which top-level folders are included.
- Select which extensions/special filenames are included.
- Edit ignored folders, ignored glob patterns and excluded path prefixes.
- Optional .gitignore support.
- Maximum source-file size.
- Maximum generated bundle size in lines (10,000 by default).
- Preview scan showing Included/Ignored + reason.
- Search/filter the preview.
- Project presets, including Tibia Idle (Canary + Client).
- Per-project configuration file.
- Project index, project tree, recent changes and Git diff.
- Snapshot manifest to detect added/modified/removed files.
- Keeps original source paths in every generated section.
- Avoids splitting a source file unless that single source file is too large.

Python 3.10+ recommended. No pip packages required.
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
APP_VERSION = "2.0.0"

CONFIG_FILENAME = ".projectbible.json"
LEGACY_CONFIG_FILENAME = ".projecttoai.json"
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
    "ChatGPTProject",  # old ProjectToAI default, prevent recursive snapshots
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

TIBIA_IDLE_EXTRA_IGNORE_DIRS = [
    "research-assets",
]

TIBIA_IDLE_EXTRA_IGNORE_GLOBS = [
    "*.map",
    "*.pak",
    "*.cache",
    "*.log",
]


@dataclass
class ScanRow:
    path: str
    status: str
    reason: str
    extension: str
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


def default_config() -> dict:
    return {
        "preset": "Default",
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


def tibia_idle_config() -> dict:
    cfg = default_config()
    cfg.update({
        "preset": "Tibia Idle (Canary + Client)",
        "selected_roots": ["Canary", "Client"],
        "ignore_dirs": sorted(set(DEFAULT_IGNORE_DIRS + TIBIA_IDLE_EXTRA_IGNORE_DIRS), key=str.lower),
        "ignore_globs": sorted(set(DEFAULT_IGNORE_GLOBS + TIBIA_IDLE_EXTRA_IGNORE_GLOBS), key=str.lower),
    })
    return cfg


def normalize_rel(path: Path) -> str:
    return path.as_posix()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def safe_json_load(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def load_config(project_root: Path) -> dict:
    cfg = default_config()
    path = project_root / CONFIG_FILENAME
    legacy = project_root / LEGACY_CONFIG_FILENAME
    if path.exists():
        cfg.update(safe_json_load(path))
    elif legacy.exists():
        cfg.update(safe_json_load(legacy))
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
            pass
    return data.decode("utf-8", errors="replace"), "utf-8-replace"


def count_lines(text: str) -> int:
    return len(text.splitlines()) if text else 0


class GitIgnoreMatcher:
    """
    Lightweight matcher for common .gitignore rules.
    It is intentionally not a byte-for-byte reimplementation of Git,
    but handles ordinary path, glob, directory and negation patterns.
    """

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
        return any(fnmatch.fnmatch(segment, pat) for segment in rel.split("/"))

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


def match_ignore_glob(rel_path: str, filename: str, globs: Iterable[str]) -> Optional[str]:
    rel_l = rel_path.lower()
    name_l = filename.lower()
    for raw in globs:
        pattern = str(raw).strip()
        if not pattern:
            continue
        p = pattern.lower()
        if fnmatch.fnmatch(name_l, p) or fnmatch.fnmatch(rel_l, p):
            return pattern
    return None


def top_group(rel: Path) -> str:
    return rel.parts[0] if len(rel.parts) > 1 else "ROOT"


def language_for(path: str) -> str:
    p = Path(path)
    if p.name == "CMakeLists.txt":
        return "cmake"
    if p.name in {"Dockerfile", "Makefile"}:
        return "text"
    return LANGUAGE_MAP.get(p.suffix.lower(), "text")


def matches_excluded_prefix(rel_str: str, prefixes: Iterable[str]) -> Optional[str]:
    normalized = rel_str.replace("\\", "/").strip("/")
    for raw in prefixes:
        prefix = str(raw).strip().replace("\\", "/").strip("/")
        if not prefix:
            continue
        if normalized == prefix or normalized.startswith(prefix + "/"):
            return prefix
    return None


def classify_path(
    path: Path,
    root: Path,
    output_dir: Path,
    cfg: dict,
    gitignore: GitIgnoreMatcher,
) -> tuple[str, str]:
    try:
        rel = path.relative_to(root)
    except ValueError:
        return "Ignored", "outside project"

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
        return "Ignored", f"top folder not selected: {rel.parts[0]}"

    if len(rel.parts) == 1 and not cfg.get("include_root_files", True):
        return "Ignored", "root files disabled"

    prefix = matches_excluded_prefix(rel_str, cfg.get("exclude_path_prefixes", []))
    if prefix:
        return "Ignored", f"excluded path: {prefix}"

    ignored_glob = match_ignore_glob(rel_str, path.name, cfg.get("ignore_globs", []))
    if ignored_glob:
        return "Ignored", f"ignored pattern: {ignored_glob}"

    if cfg.get("respect_gitignore", True) and gitignore.ignored(rel_str, False):
        return "Ignored", ".gitignore"

    try:
        size = path.stat().st_size
    except Exception:
        return "Ignored", "cannot stat"

    max_bytes = int(float(cfg.get("max_source_file_mb", DEFAULT_MAX_SOURCE_MB)) * 1024 * 1024)
    if size > max_bytes:
        return "Ignored", f"larger than {cfg.get('max_source_file_mb')} MB"

    if path.name in set(cfg.get("special_filenames", [])):
        return "Included", "special filename"

    ext = path.suffix.lower()
    allowed = {str(x).lower() for x in cfg.get("extensions", [])}
    if ext not in allowed:
        return "Ignored", f"extension not selected: {ext or '(none)'}"

    try:
        sample = path.read_bytes()[:4096]
        if b"\x00" in sample:
            return "Ignored", "binary/NUL"
    except Exception:
        return "Ignored", "cannot read"

    return "Included", "selected source"


def scan_project(
    root: Path,
    output_dir: Path,
    cfg: dict,
    progress=None,
    stop_event: Optional[threading.Event] = None,
) -> list[ScanRow]:
    root = root.resolve()
    output_dir = output_dir.resolve()
    matcher = GitIgnoreMatcher(root)
    rows: list[ScanRow] = []
    seen = 0

    def emit(message: str):
        if progress:
            progress(message)

    ignore_dirs = set(cfg.get("ignore_dirs", []))
    selected_roots = set(cfg.get("selected_roots", []))

    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        if stop_event and stop_event.is_set():
            break

        current = Path(dirpath)

        # Fast pruning of directories. Ignored files inside a pruned directory
        # are intentionally not listed in preview; the directory itself is already
        # an explicit rule.
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

            if len(rel.parts) == 1 and selected_roots and d not in selected_roots:
                continue

            if cfg.get("respect_gitignore", True) and matcher.ignored(normalize_rel(rel), True):
                continue

            prefix = matches_excluded_prefix(normalize_rel(rel), cfg.get("exclude_path_prefixes", []))
            if prefix:
                continue

            kept.append(d)

        dirnames[:] = kept

        for filename in filenames:
            if stop_event and stop_event.is_set():
                break

            path = current / filename
            seen += 1

            status, reason = classify_path(path, root, output_dir, cfg, matcher)
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
                extension=path.suffix.lower() or "(none)",
                size_bytes=size,
                lines=lines,
                group=top_group(rel),
                sha256=sha,
            ))

            if seen % 250 == 0:
                emit(f"Scanned {seen:,} files...")

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
    result.append(fence)
    result.append("")
    return result


def split_source_sections(sf: SourceFile, text: str, usable_lines: int) -> list[list[str]]:
    lines = text.splitlines()
    rendered = render_section(sf, lines)
    if len(rendered) <= usable_lines:
        sf.part_count = 1
        return [rendered]

    overhead = len(render_section(sf, [], part=(1, 999999)))
    capacity = usable_lines - overhead - 1
    if capacity < 1:
        raise RuntimeError("Bundle line limit is too small for metadata headers.")

    chunks = [lines[i:i + capacity] for i in range(0, len(lines), capacity)]
    sf.part_count = len(chunks)
    sections = []

    for i, chunk in enumerate(chunks, 1):
        section = render_section(sf, chunk, part=(i, len(chunks)))
        while len(section) > usable_lines and chunk:
            chunk = chunk[:-1]
            section = render_section(sf, chunk, part=(i, len(chunks)))
        sections.append(section)

    return sections


def safe_group_name(group: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", group.strip()) or "ROOT"


def cleanup_generated_files(output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    exact = {
        "00_PROJECT_INDEX.md",
        "01_AI_INSTRUCTIONS.md",
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
    all_lines = prefix + body
    if len(all_lines) > max_lines:
        raise RuntimeError(f"{path.name} exceeded line limit: {len(all_lines)} > {max_lines}")
    path.write_text("\n".join(all_lines) + "\n", encoding="utf-8")


def generate_bundles(
    sources: list[tuple[SourceFile, str]],
    output_dir: Path,
    max_lines: int,
) -> list[Path]:
    grouped: dict[str, list[tuple[SourceFile, str]]] = {}
    for sf, text in sources:
        grouped.setdefault(sf.group, []).append((sf, text))

    groups = sorted(grouped, key=lambda g: (g != "ROOT", g.lower()))
    created: list[Path] = []
    ordinal = 0
    bundle_prefix_lines = 5
    usable = max_lines - bundle_prefix_lines

    if usable < 50:
        raise ValueError("Maximum lines per bundle must be at least 55.")

    for group in groups:
        ordinal += 10
        sequence = 1
        body: list[str] = []
        bundle_files: list[SourceFile] = []

        def flush():
            nonlocal sequence, body, bundle_files
            if not body:
                return
            name = f"{ordinal:02d}_{safe_group_name(group)}_{sequence:03d}.md"
            out = output_dir / name
            write_bundle(out, group, body, max_lines)
            for sf in bundle_files:
                if not sf.bundle:
                    sf.bundle = name
                elif name not in sf.bundle.split(" | "):
                    sf.bundle += " | " + name
            created.append(out)
            sequence += 1
            body = []
            bundle_files = []

        for sf, text in grouped[group]:
            sections = split_source_sections(sf, text, usable)

            for section in sections:
                if body and len(body) + len(section) > usable:
                    flush()

                if len(section) > usable:
                    raise RuntimeError(f"Section for {sf.path} cannot fit in bundle.")

                body.extend(section)
                if sf not in bundle_files:
                    bundle_files.append(sf)

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


def git_working_tree_text(root: Path, max_lines: int) -> str:
    code, inside = run_git(root, ["rev-parse", "--is-inside-work-tree"])
    if code != 0 or "true" not in inside.lower():
        return "_Git repository not detected._\n"

    result: list[str] = []

    _, branch = run_git(root, ["branch", "--show-current"])
    result += ["## Branch", "", f"`{branch.strip() or '(detached HEAD)'}`", ""]

    _, status = run_git(root, ["status", "--short"])
    result += ["## Git status", "", "```text", status.strip() or "(clean)", "```", ""]

    _, diff = run_git(root, ["diff", "--no-ext-diff", "--unified=3"])
    diff_lines = diff.splitlines()
    truncated = len(diff_lines) > max_lines
    diff_lines = diff_lines[:max_lines]
    result += ["## Unstaged diff", "", "```diff"]
    result.extend(diff_lines or ["# no unstaged diff"])
    result.append("```")
    if truncated:
        result += ["", f"> Diff truncated to {max_lines} lines."]
    result.append("")

    _, staged = run_git(root, ["diff", "--cached", "--no-ext-diff", "--unified=3"])
    staged_lines = staged.splitlines()
    truncated2 = len(staged_lines) > max_lines
    staged_lines = staged_lines[:max_lines]
    result += ["## Staged diff", "", "```diff"]
    result.extend(staged_lines or ["# no staged diff"])
    result.append("```")
    if truncated2:
        result += ["", f"> Staged diff truncated to {max_lines} lines."]
    result.append("")

    return "\n".join(result)


def load_previous_manifest(output_dir: Path) -> dict:
    path = output_dir / MANIFEST_FILENAME
    return safe_json_load(path) if path.exists() else {}


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


def build_project_tree(paths: list[str]) -> str:
    tree: dict = {}
    for path in paths:
        node = tree
        for part in path.split("/"):
            node = node.setdefault(part, {})

    lines: list[str] = []

    def walk(node: dict, prefix: str = ""):
        items = sorted(node.items(), key=lambda kv: (not bool(kv[1]), kv[0].lower()))
        for index, (name, child) in enumerate(items):
            last = index == len(items) - 1
            lines.append(prefix + ("└── " if last else "├── ") + name)
            if child:
                walk(child, prefix + ("    " if last else "│   "))

    walk(tree)
    return "\n".join(lines)


def write_support_files(
    output_dir: Path,
    project_root: Path,
    files: list[SourceFile],
    bundles: list[Path],
    cfg: dict,
    added: list[str],
    modified: list[str],
    removed: list[str],
) -> None:
    generated_at = datetime.now().astimezone().isoformat(timespec="seconds")
    total_lines = sum(f.lines for f in files)
    total_bytes = sum(f.bytes for f in files)
    estimated_tokens = max(1, total_bytes // 4)

    ai_instructions = [
        f"# {APP_NAME} — AI Instructions",
        "",
        "This directory is a generated textual snapshot of a software project.",
        "",
        "## How to use these sources",
        "",
        "1. Search `00_PROJECT_INDEX.md` first when the exact source path is unknown.",
        "2. Open only the bundle(s) listed for the relevant source file.",
        "3. `98_RECENT_CHANGES.md` is the preferred source when reviewing the user's newest local edits.",
        "4. Every code proposal must mention the exact original source path.",
        "5. Prefer minimal, scoped changes. Do not refactor unrelated code.",
        "6. When telling the user what to edit, provide an exact BEFORE block and AFTER block whenever practical.",
        "7. Do not treat generated bundle paths as real source paths. Use the path shown after `FROM:`.",
        "",
        f"- Project root at export time: `{project_root}`",
        f"- Generated: `{generated_at}`",
        f"- Source files: **{len(files)}**",
        f"- Source lines: **{total_lines:,}**",
        f"- Approximate raw-text tokens: **{estimated_tokens:,}**",
        "",
    ]
    (output_dir / "01_AI_INSTRUCTIONS.md").write_text(
        "\n".join(ai_instructions) + "\n",
        encoding="utf-8",
    )

    index = [
        f"# {APP_NAME} — Project Index",
        "",
        f"- Project: `{project_root}`",
        f"- Generated: `{generated_at}`",
        f"- Exported source files: **{len(files)}**",
        f"- Source lines: **{total_lines:,}**",
        f"- Source bytes: **{total_bytes:,}**",
        f"- Bundles: **{len(bundles)}**",
        f"- Approximate raw-text tokens: **{estimated_tokens:,}**",
        "",
        "## Changes since previous snapshot",
        "",
        f"- Added: **{len(added)}**",
        f"- Modified: **{len(modified)}**",
        f"- Removed: **{len(removed)}**",
        "",
    ]

    if added:
        index += ["### Added", ""] + [f"- `{p}`" for p in added] + [""]
    if modified:
        index += ["### Modified", ""] + [f"- `{p}`" for p in modified] + [""]
    if removed:
        index += ["### Removed", ""] + [f"- `{p}`" for p in removed] + [""]

    index += [
        "## Source map",
        "",
        "| Original source path | Bundle | Lines | Bytes | SHA256 |",
        "|---|---|---:|---:|---|",
    ]

    for f in files:
        index.append(
            f"| `{f.path}` | `{f.bundle}` | {f.lines} | {f.bytes:,} | `{f.sha256[:16]}` |"
        )

    (output_dir / "00_PROJECT_INDEX.md").write_text(
        "\n".join(index) + "\n",
        encoding="utf-8",
    )

    tree = [
        f"# {APP_NAME} — Project Tree",
        "",
        "> This tree contains only files included in the generated Bible.",
        "",
        "```text",
        build_project_tree([f.path for f in files]),
        "```",
        "",
    ]
    (output_dir / "99_PROJECT_TREE.md").write_text(
        "\n".join(tree),
        encoding="utf-8",
    )

    recent = [
        f"# {APP_NAME} — Recent Changes",
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
                project_root,
                int(cfg.get("git_diff_max_lines", 5000)),
            )
        )

    (output_dir / "98_RECENT_CHANGES.md").write_text(
        "\n".join(recent) + "\n",
        encoding="utf-8",
    )

    manifest = {
        "app": APP_NAME,
        "version": APP_VERSION,
        "generated_at": generated_at,
        "project_root": str(project_root),
        "config": cfg,
        "bundles": [p.name for p in bundles],
        "files": [asdict(f) for f in files],
    }
    (output_dir / MANIFEST_FILENAME).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def export_project(
    project_root: Path,
    output_dir: Path,
    cfg: dict,
    scan_rows: Optional[list[ScanRow]] = None,
    progress=None,
) -> ExportResult:
    project_root = project_root.expanduser().resolve()
    output_dir = output_dir.expanduser().resolve()

    if not project_root.is_dir():
        raise ValueError(f"Invalid project folder: {project_root}")

    max_lines = int(cfg.get("max_lines_per_bundle", DEFAULT_MAX_LINES))
    if max_lines < 55:
        raise ValueError("Maximum lines per bundle must be at least 55.")

    def emit(message: str):
        if progress:
            progress(message)

    output_dir.mkdir(parents=True, exist_ok=True)
    previous = load_previous_manifest(output_dir)

    if scan_rows is None:
        emit("Scanning project...")
        scan_rows = scan_project(project_root, output_dir, cfg, progress=emit)

    included_rows = [r for r in scan_rows if r.status == "Included"]
    emit(f"Included files: {len(included_rows):,}")

    sources: list[tuple[SourceFile, str]] = []
    for index, row in enumerate(included_rows, 1):
        path = project_root / Path(row.path)
        try:
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
        except Exception as exc:
            emit(f"Skipped during export: {row.path} ({exc})")

        if index % 250 == 0:
            emit(f"Prepared {index:,}/{len(included_rows):,} files...")

    files = [sf for sf, _ in sources]
    added, modified, removed = compare_manifests(previous, files)

    emit("Cleaning previous generated bundles...")
    cleanup_generated_files(output_dir)

    emit("Generating Markdown bundles...")
    bundles = generate_bundles(sources, output_dir, max_lines)

    emit("Writing index/tree/change files...")
    write_support_files(
        output_dir,
        project_root,
        files,
        bundles,
        cfg,
        added,
        modified,
        removed,
    )

    total_lines = sum(f.lines for f in files)
    total_bytes = sum(f.bytes for f in files)
    estimated_tokens = max(1, total_bytes // 4)

    emit("Done.")

    return ExportResult(
        scanned=len(scan_rows),
        exported=len(files),
        ignored=len([r for r in scan_rows if r.status == "Ignored"]),
        source_lines=total_lines,
        estimated_tokens=estimated_tokens,
        bundles=len(bundles),
        output_dir=str(output_dir),
        added=len(added),
        modified=len(modified),
        removed=len(removed),
    )


# ---------------------------------------------------------------------------
# GUI
# ---------------------------------------------------------------------------

def launch_gui() -> None:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    class App(tk.Tk):
        def __init__(self):
            super().__init__()
            self.title(f"{APP_NAME} v{APP_VERSION}")
            self.geometry("1180x790")
            self.minsize(980, 680)

            self.scan_rows: list[ScanRow] = []
            self.scan_thread: Optional[threading.Thread] = None
            self.export_thread: Optional[threading.Thread] = None
            self.stop_event = threading.Event()
            self.ui_queue: queue.Queue = queue.Queue()

            self.project_var = tk.StringVar()
            self.output_var = tk.StringVar()
            self.preset_var = tk.StringVar(value="Default")
            self.max_lines_var = tk.StringVar(value=str(DEFAULT_MAX_LINES))
            self.max_file_mb_var = tk.StringVar(value=str(DEFAULT_MAX_SOURCE_MB))
            self.root_files_var = tk.BooleanVar(value=True)
            self.gitignore_var = tk.BooleanVar(value=True)
            self.gitdiff_var = tk.BooleanVar(value=True)
            self.gitdiff_lines_var = tk.StringVar(value="5000")

            self.preview_search_var = tk.StringVar()
            self.preview_mode_var = tk.StringVar(value="All")

            self.stats_var = tk.StringVar(value="No scan yet.")
            self.status_var = tk.StringVar(value="Ready.")

            self._build_ui()
            self.after(100, self._process_ui_queue)

        # ------------------------ UI construction ------------------------

        def _build_ui(self):
            self._configure_style()

            header = ttk.Frame(self, padding=(16, 12, 16, 8))
            header.pack(fill="x")

            ttk.Label(
                header,
                text=APP_NAME,
                style="Title.TLabel",
            ).pack(anchor="w")
            ttk.Label(
                header,
                text="Turn any project into an AI-readable code bible.",
                style="Subtitle.TLabel",
            ).pack(anchor="w")

            self.notebook = ttk.Notebook(self)
            self.notebook.pack(fill="both", expand=True, padx=14, pady=(0, 8))

            self.tab_project = ttk.Frame(self.notebook, padding=14)
            self.tab_include = ttk.Frame(self.notebook, padding=14)
            self.tab_ignore = ttk.Frame(self.notebook, padding=14)
            self.tab_preview = ttk.Frame(self.notebook, padding=14)
            self.tab_generate = ttk.Frame(self.notebook, padding=14)

            self.notebook.add(self.tab_project, text="1. Project")
            self.notebook.add(self.tab_include, text="2. Include")
            self.notebook.add(self.tab_ignore, text="3. Ignore")
            self.notebook.add(self.tab_preview, text="4. Preview")
            self.notebook.add(self.tab_generate, text="5. Generate")

            self._build_project_tab()
            self._build_include_tab()
            self._build_ignore_tab()
            self._build_preview_tab()
            self._build_generate_tab()

            bottom = ttk.Frame(self, padding=(14, 0, 14, 10))
            bottom.pack(fill="x")
            ttk.Label(bottom, textvariable=self.status_var).pack(side="left")
            ttk.Button(bottom, text="Save Project Config", command=self.save_project_config).pack(side="right")

        def _configure_style(self):
            style = ttk.Style(self)
            try:
                if sys.platform.startswith("win"):
                    style.theme_use("vista")
            except Exception:
                pass
            style.configure("Title.TLabel", font=("Segoe UI", 20, "bold"))
            style.configure("Subtitle.TLabel", font=("Segoe UI", 10))
            style.configure("Section.TLabel", font=("Segoe UI", 11, "bold"))
            style.configure("Big.TButton", font=("Segoe UI", 11, "bold"), padding=8)

        def _build_project_tab(self):
            f = self.tab_project

            ttk.Label(f, text="Project folders", style="Section.TLabel").grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 8))

            ttk.Label(f, text="Source project:").grid(row=1, column=0, sticky="w", pady=5)
            ttk.Entry(f, textvariable=self.project_var).grid(row=1, column=1, sticky="ew", padx=8, pady=5)
            ttk.Button(f, text="Browse...", command=self.choose_project).grid(row=1, column=2, pady=5)

            ttk.Label(f, text="Bible output:").grid(row=2, column=0, sticky="w", pady=5)
            ttk.Entry(f, textvariable=self.output_var).grid(row=2, column=1, sticky="ew", padx=8, pady=5)
            ttk.Button(f, text="Browse...", command=self.choose_output).grid(row=2, column=2, pady=5)

            ttk.Separator(f).grid(row=3, column=0, columnspan=3, sticky="ew", pady=14)

            ttk.Label(f, text="Preset", style="Section.TLabel").grid(row=4, column=0, columnspan=3, sticky="w", pady=(0, 6))
            ttk.Label(f, text="Preset:").grid(row=5, column=0, sticky="w", pady=5)

            preset = ttk.Combobox(
                f,
                textvariable=self.preset_var,
                state="readonly",
                values=["Default", "Tibia Idle (Canary + Client)"],
                width=34,
            )
            preset.grid(row=5, column=1, sticky="w", padx=8, pady=5)
            preset.bind("<<ComboboxSelected>>", lambda _e: self.apply_preset())

            ttk.Button(f, text="Apply preset", command=self.apply_preset).grid(row=5, column=2, pady=5)

            ttk.Separator(f).grid(row=6, column=0, columnspan=3, sticky="ew", pady=14)

            ttk.Label(f, text="Generation limits", style="Section.TLabel").grid(row=7, column=0, columnspan=3, sticky="w", pady=(0, 6))

            limits = ttk.Frame(f)
            limits.grid(row=8, column=0, columnspan=3, sticky="w", pady=4)

            ttk.Label(limits, text="Max lines per bundle:").pack(side="left")
            ttk.Spinbox(limits, from_=55, to=1000000, textvariable=self.max_lines_var, width=10).pack(side="left", padx=(6, 24))

            ttk.Label(limits, text="Max source file size (MB):").pack(side="left")
            ttk.Spinbox(limits, from_=0.1, to=1000, increment=0.1, textvariable=self.max_file_mb_var, width=9).pack(side="left", padx=(6, 24))

            ttk.Label(limits, text="Git diff max lines:").pack(side="left")
            ttk.Spinbox(limits, from_=0, to=1000000, textvariable=self.gitdiff_lines_var, width=9).pack(side="left", padx=6)

            options = ttk.LabelFrame(f, text="Options", padding=10)
            options.grid(row=9, column=0, columnspan=3, sticky="ew", pady=(14, 4))

            ttk.Checkbutton(options, text="Include files stored directly in project root", variable=self.root_files_var).pack(anchor="w")
            ttk.Checkbutton(options, text="Respect .gitignore", variable=self.gitignore_var).pack(anchor="w", pady=3)
            ttk.Checkbutton(options, text="Generate Git status + local diff in 98_RECENT_CHANGES.md", variable=self.gitdiff_var).pack(anchor="w")

            tip = (
                "Recommended for Tibia Idle: choose the Tibia Idle preset, then scan the project. "
                "The Preview tab lets you verify exactly what will and will not enter the Bible before generating it."
            )
            ttk.Label(f, text=tip, wraplength=850).grid(row=10, column=0, columnspan=3, sticky="w", pady=(18, 0))

            f.columnconfigure(1, weight=1)

        def _build_include_tab(self):
            f = self.tab_include
            f.columnconfigure(0, weight=1)
            f.columnconfigure(1, weight=1)
            f.rowconfigure(1, weight=1)

            ttk.Label(f, text="Top-level folders", style="Section.TLabel").grid(row=0, column=0, sticky="w")
            ttk.Label(f, text="File extensions", style="Section.TLabel").grid(row=0, column=1, sticky="w", padx=(16, 0))

            left = ttk.Frame(f)
            left.grid(row=1, column=0, sticky="nsew", pady=(6, 8))
            left.rowconfigure(0, weight=1)
            left.columnconfigure(0, weight=1)

            self.roots_list = tk.Listbox(left, selectmode=tk.EXTENDED, exportselection=False)
            roots_scroll = ttk.Scrollbar(left, orient="vertical", command=self.roots_list.yview)
            self.roots_list.configure(yscrollcommand=roots_scroll.set)
            self.roots_list.grid(row=0, column=0, sticky="nsew")
            roots_scroll.grid(row=0, column=1, sticky="ns")

            root_buttons = ttk.Frame(left)
            root_buttons.grid(row=1, column=0, columnspan=2, sticky="w", pady=(6, 0))
            ttk.Button(root_buttons, text="Select all", command=lambda: self.roots_list.select_set(0, "end")).pack(side="left")
            ttk.Button(root_buttons, text="Clear", command=lambda: self.roots_list.selection_clear(0, "end")).pack(side="left", padx=6)
            ttk.Button(root_buttons, text="Canary + Client", command=self.select_tibia_roots).pack(side="left")

            right = ttk.Frame(f)
            right.grid(row=1, column=1, sticky="nsew", padx=(16, 0), pady=(6, 8))
            right.rowconfigure(0, weight=1)
            right.columnconfigure(0, weight=1)

            self.extensions_list = tk.Listbox(right, selectmode=tk.EXTENDED, exportselection=False)
            ext_scroll = ttk.Scrollbar(right, orient="vertical", command=self.extensions_list.yview)
            self.extensions_list.configure(yscrollcommand=ext_scroll.set)
            self.extensions_list.grid(row=0, column=0, sticky="nsew")
            ext_scroll.grid(row=0, column=1, sticky="ns")

            for ext in sorted(DEFAULT_EXTENSIONS):
                self.extensions_list.insert("end", ext)
            self.extensions_list.select_set(0, "end")

            ext_buttons = ttk.Frame(right)
            ext_buttons.grid(row=1, column=0, columnspan=2, sticky="w", pady=(6, 0))
            ttk.Button(ext_buttons, text="Select all", command=lambda: self.extensions_list.select_set(0, "end")).pack(side="left")
            ttk.Button(ext_buttons, text="Clear", command=lambda: self.extensions_list.selection_clear(0, "end")).pack(side="left", padx=6)
            ttk.Button(ext_buttons, text="Code essentials", command=self.select_code_essentials).pack(side="left")

            ttk.Label(f, text="Special filenames (one per line)", style="Section.TLabel").grid(row=2, column=0, columnspan=2, sticky="w", pady=(10, 4))
            self.special_text = tk.Text(f, height=7, wrap="none")
            self.special_text.grid(row=3, column=0, columnspan=2, sticky="ew")
            self._set_text_lines(self.special_text, DEFAULT_SPECIAL_FILENAMES)

        def _build_ignore_tab(self):
            f = self.tab_ignore
            f.columnconfigure(0, weight=1)
            f.columnconfigure(1, weight=1)
            f.rowconfigure(1, weight=1)

            ttk.Label(f, text="Ignored directory names", style="Section.TLabel").grid(row=0, column=0, sticky="w")
            ttk.Label(f, text="Ignored file/path patterns", style="Section.TLabel").grid(row=0, column=1, sticky="w", padx=(16, 0))

            self.ignore_dirs_text = tk.Text(f, wrap="none")
            self.ignore_dirs_text.grid(row=1, column=0, sticky="nsew", pady=(6, 8))

            self.ignore_globs_text = tk.Text(f, wrap="none")
            self.ignore_globs_text.grid(row=1, column=1, sticky="nsew", padx=(16, 0), pady=(6, 8))

            self._set_text_lines(self.ignore_dirs_text, DEFAULT_IGNORE_DIRS)
            self._set_text_lines(self.ignore_globs_text, DEFAULT_IGNORE_GLOBS)

            ttk.Label(
                f,
                text="Directory names apply anywhere in the tree. Example: bin",
            ).grid(row=2, column=0, sticky="w")
            ttk.Label(
                f,
                text="Patterns use glob syntax. Examples: *.png  or  data/cache/*",
            ).grid(row=2, column=1, sticky="w", padx=(16, 0))

            ttk.Label(f, text="Excluded relative paths / prefixes", style="Section.TLabel").grid(row=3, column=0, columnspan=2, sticky="w", pady=(14, 4))
            self.exclude_paths_text = tk.Text(f, height=7, wrap="none")
            self.exclude_paths_text.grid(row=4, column=0, columnspan=2, sticky="ew")
            ttk.Label(
                f,
                text="One per line. Example: Canary/docs  or  Client/data/things. Everything under that path is skipped.",
            ).grid(row=5, column=0, columnspan=2, sticky="w", pady=(4, 8))

            actions = ttk.Frame(f)
            actions.grid(row=6, column=0, columnspan=2, sticky="w")
            ttk.Button(actions, text="Restore defaults", command=self.restore_ignore_defaults).pack(side="left")
            ttk.Button(actions, text="Tibia Idle ignore preset", command=self.apply_tibia_ignore_defaults).pack(side="left", padx=8)

        def _build_preview_tab(self):
            f = self.tab_preview
            f.columnconfigure(0, weight=1)
            f.rowconfigure(2, weight=1)

            controls = ttk.Frame(f)
            controls.grid(row=0, column=0, sticky="ew")
            controls.columnconfigure(1, weight=1)

            ttk.Button(controls, text="SCAN PROJECT", style="Big.TButton", command=self.start_scan).grid(row=0, column=0, padx=(0, 12))
            ttk.Entry(controls, textvariable=self.preview_search_var).grid(row=0, column=1, sticky="ew")
            ttk.Label(controls, text="Show:").grid(row=0, column=2, padx=(12, 4))
            mode = ttk.Combobox(
                controls,
                textvariable=self.preview_mode_var,
                state="readonly",
                width=11,
                values=["All", "Included", "Ignored"],
            )
            mode.grid(row=0, column=3)
            mode.bind("<<ComboboxSelected>>", lambda _e: self.refresh_preview())
            self.preview_search_var.trace_add("write", lambda *_: self.refresh_preview())

            ttk.Label(f, textvariable=self.stats_var).grid(row=1, column=0, sticky="w", pady=(10, 6))

            table_frame = ttk.Frame(f)
            table_frame.grid(row=2, column=0, sticky="nsew")
            table_frame.rowconfigure(0, weight=1)
            table_frame.columnconfigure(0, weight=1)

            cols = ("status", "path", "reason", "lines", "size")
            self.preview_tree = ttk.Treeview(table_frame, columns=cols, show="headings")
            self.preview_tree.heading("status", text="Status")
            self.preview_tree.heading("path", text="Original source path")
            self.preview_tree.heading("reason", text="Reason")
            self.preview_tree.heading("lines", text="Lines")
            self.preview_tree.heading("size", text="Size")

            self.preview_tree.column("status", width=85, stretch=False)
            self.preview_tree.column("path", width=480)
            self.preview_tree.column("reason", width=250)
            self.preview_tree.column("lines", width=80, anchor="e", stretch=False)
            self.preview_tree.column("size", width=90, anchor="e", stretch=False)

            y = ttk.Scrollbar(table_frame, orient="vertical", command=self.preview_tree.yview)
            x = ttk.Scrollbar(table_frame, orient="horizontal", command=self.preview_tree.xview)
            self.preview_tree.configure(yscrollcommand=y.set, xscrollcommand=x.set)

            self.preview_tree.grid(row=0, column=0, sticky="nsew")
            y.grid(row=0, column=1, sticky="ns")
            x.grid(row=1, column=0, sticky="ew")

        def _build_generate_tab(self):
            f = self.tab_generate
            f.columnconfigure(0, weight=1)
            f.rowconfigure(3, weight=1)

            ttk.Label(f, text="Generate the Project Bible", style="Section.TLabel").grid(row=0, column=0, sticky="w")

            description = (
                "Generation uses the same settings shown in the other tabs. "
                "If you scanned the project first, the preview snapshot is reused."
            )
            ttk.Label(f, text=description, wraplength=900).grid(row=1, column=0, sticky="w", pady=(4, 10))

            buttons = ttk.Frame(f)
            buttons.grid(row=2, column=0, sticky="ew", pady=(0, 8))

            self.generate_button = ttk.Button(
                buttons,
                text="GENERATE PROJECT BIBLE",
                style="Big.TButton",
                command=self.start_export,
            )
            self.generate_button.pack(side="left")

            ttk.Button(buttons, text="Open output folder", command=self.open_output).pack(side="left", padx=8)
            ttk.Button(buttons, text="Save config", command=self.save_project_config).pack(side="left")

            log_frame = ttk.Frame(f)
            log_frame.grid(row=3, column=0, sticky="nsew")
            log_frame.rowconfigure(0, weight=1)
            log_frame.columnconfigure(0, weight=1)

            self.log_text = tk.Text(log_frame, wrap="word")
            log_scroll = ttk.Scrollbar(log_frame, orient="vertical", command=self.log_text.yview)
            self.log_text.configure(yscrollcommand=log_scroll.set)
            self.log_text.grid(row=0, column=0, sticky="nsew")
            log_scroll.grid(row=0, column=1, sticky="ns")

        # ------------------------ config helpers ------------------------

        @staticmethod
        def _text_lines(widget) -> list[str]:
            return [
                line.strip()
                for line in widget.get("1.0", "end").splitlines()
                if line.strip()
            ]

        @staticmethod
        def _set_text_lines(widget, values: Iterable[str]):
            widget.delete("1.0", "end")
            widget.insert("1.0", "\n".join(values))

        def selected_roots(self) -> list[str]:
            return [self.roots_list.get(i) for i in self.roots_list.curselection()]

        def selected_extensions(self) -> list[str]:
            return [self.extensions_list.get(i) for i in self.extensions_list.curselection()]

        def current_config(self) -> dict:
            try:
                max_lines = int(self.max_lines_var.get())
                max_mb = float(self.max_file_mb_var.get())
                git_lines = int(self.gitdiff_lines_var.get())
            except ValueError as exc:
                raise ValueError("Generation limits contain an invalid number.") from exc

            return {
                "preset": self.preset_var.get(),
                "selected_roots": self.selected_roots(),
                "extensions": self.selected_extensions(),
                "special_filenames": self._text_lines(self.special_text),
                "ignore_dirs": self._text_lines(self.ignore_dirs_text),
                "ignore_globs": self._text_lines(self.ignore_globs_text),
                "exclude_path_prefixes": self._text_lines(self.exclude_paths_text),
                "max_lines_per_bundle": max_lines,
                "max_source_file_mb": max_mb,
                "include_root_files": self.root_files_var.get(),
                "respect_gitignore": self.gitignore_var.get(),
                "include_git_diff": self.gitdiff_var.get(),
                "git_diff_max_lines": git_lines,
            }

        def apply_config_to_ui(self, cfg: dict):
            self.preset_var.set(cfg.get("preset", "Default"))
            self.max_lines_var.set(str(cfg.get("max_lines_per_bundle", DEFAULT_MAX_LINES)))
            self.max_file_mb_var.set(str(cfg.get("max_source_file_mb", DEFAULT_MAX_SOURCE_MB)))
            self.root_files_var.set(bool(cfg.get("include_root_files", True)))
            self.gitignore_var.set(bool(cfg.get("respect_gitignore", True)))
            self.gitdiff_var.set(bool(cfg.get("include_git_diff", True)))
            self.gitdiff_lines_var.set(str(cfg.get("git_diff_max_lines", 5000)))

            self._set_text_lines(self.special_text, cfg.get("special_filenames", DEFAULT_SPECIAL_FILENAMES))
            self._set_text_lines(self.ignore_dirs_text, cfg.get("ignore_dirs", DEFAULT_IGNORE_DIRS))
            self._set_text_lines(self.ignore_globs_text, cfg.get("ignore_globs", DEFAULT_IGNORE_GLOBS))
            self._set_text_lines(self.exclude_paths_text, cfg.get("exclude_path_prefixes", []))

            ext_set = set(cfg.get("extensions", DEFAULT_EXTENSIONS))
            self.extensions_list.selection_clear(0, "end")
            for i in range(self.extensions_list.size()):
                if self.extensions_list.get(i) in ext_set:
                    self.extensions_list.select_set(i)

            roots = set(cfg.get("selected_roots", []))
            self.roots_list.selection_clear(0, "end")
            for i in range(self.roots_list.size()):
                if not roots or self.roots_list.get(i) in roots:
                    self.roots_list.select_set(i)

        # ------------------------ project handling ------------------------

        def choose_project(self):
            path = filedialog.askdirectory(title="Choose source project")
            if not path:
                return

            root = Path(path)
            self.project_var.set(str(root))
            self.output_var.set(str(root / DEFAULT_OUTPUT_DIRNAME))
            self.populate_roots(root)

            cfg = load_config(root)
            self.apply_config_to_ui(cfg)
            self.scan_rows = []
            self.refresh_preview()
            self.status_var.set(f"Project loaded: {root.name}")

        def choose_output(self):
            path = filedialog.askdirectory(title="Choose Bible output folder")
            if path:
                self.output_var.set(path)

        def populate_roots(self, root: Path):
            self.roots_list.delete(0, "end")
            try:
                dirs = sorted(
                    [
                        p.name
                        for p in root.iterdir()
                        if p.is_dir() and p.name not in {".git", DEFAULT_OUTPUT_DIRNAME}
                    ],
                    key=str.lower,
                )
                for name in dirs:
                    self.roots_list.insert("end", name)
                if dirs:
                    self.roots_list.select_set(0, "end")
            except Exception as exc:
                messagebox.showerror(APP_NAME, f"Could not list folders:\n{exc}")

        def save_project_config(self):
            try:
                root = Path(self.project_var.get())
                if not root.is_dir():
                    raise ValueError("Choose a valid source project first.")
                path = save_config(root, self.current_config())
                self.status_var.set(f"Config saved: {path.name}")
                messagebox.showinfo(APP_NAME, f"Project configuration saved:\n{path}")
            except Exception as exc:
                messagebox.showerror(APP_NAME, str(exc))

        # ------------------------ presets ------------------------

        def apply_preset(self):
            name = self.preset_var.get()
            if name == "Tibia Idle (Canary + Client)":
                cfg = tibia_idle_config()
            else:
                cfg = default_config()
                cfg["preset"] = "Default"
            self.apply_config_to_ui(cfg)

            if name == "Tibia Idle (Canary + Client)":
                self.select_tibia_roots()

            self.status_var.set(f"Preset applied: {name}")

        def select_tibia_roots(self):
            wanted = {"Canary", "Client"}
            self.roots_list.selection_clear(0, "end")
            for i in range(self.roots_list.size()):
                if self.roots_list.get(i) in wanted:
                    self.roots_list.select_set(i)

        def select_code_essentials(self):
            wanted = {
                ".c", ".cc", ".cpp", ".cxx", ".h", ".hpp",
                ".cs", ".lua", ".otui", ".otmod",
                ".py", ".js", ".jsx", ".ts", ".tsx",
                ".xml", ".json", ".yaml", ".yml", ".toml", ".ini", ".sql",
                ".md", ".txt",
            }
            self.extensions_list.selection_clear(0, "end")
            for i in range(self.extensions_list.size()):
                if self.extensions_list.get(i) in wanted:
                    self.extensions_list.select_set(i)

        def restore_ignore_defaults(self):
            self._set_text_lines(self.ignore_dirs_text, DEFAULT_IGNORE_DIRS)
            self._set_text_lines(self.ignore_globs_text, DEFAULT_IGNORE_GLOBS)
            self._set_text_lines(self.exclude_paths_text, [])
            self.status_var.set("Ignore rules restored to defaults.")

        def apply_tibia_ignore_defaults(self):
            self._set_text_lines(
                self.ignore_dirs_text,
                sorted(set(DEFAULT_IGNORE_DIRS + TIBIA_IDLE_EXTRA_IGNORE_DIRS), key=str.lower),
            )
            self._set_text_lines(
                self.ignore_globs_text,
                sorted(set(DEFAULT_IGNORE_GLOBS + TIBIA_IDLE_EXTRA_IGNORE_GLOBS), key=str.lower),
            )
            self.status_var.set("Tibia Idle ignore rules applied.")

        # ------------------------ scan / preview ------------------------

        def validate_paths(self) -> tuple[Path, Path]:
            root = Path(self.project_var.get()).expanduser()
            if not root.is_dir():
                raise ValueError("Choose a valid source project folder.")

            output_text = self.output_var.get().strip()
            output = Path(output_text).expanduser() if output_text else root / DEFAULT_OUTPUT_DIRNAME
            return root, output

        def queue_log(self, message: str):
            self.ui_queue.put(("log", message))

        def start_scan(self):
            if self.scan_thread and self.scan_thread.is_alive():
                return
            try:
                root, output = self.validate_paths()
                cfg = self.current_config()
            except Exception as exc:
                messagebox.showerror(APP_NAME, str(exc))
                return

            self.stop_event.clear()
            self.scan_rows = []
            self.status_var.set("Scanning...")
            self.stats_var.set("Scanning project...")
            self.preview_tree.delete(*self.preview_tree.get_children())

            def worker():
                try:
                    rows = scan_project(
                        root,
                        output,
                        cfg,
                        progress=lambda m: self.ui_queue.put(("status", m)),
                        stop_event=self.stop_event,
                    )
                    self.ui_queue.put(("scan_done", rows))
                except Exception as exc:
                    self.ui_queue.put(("error", f"Scan failed:\n{exc}"))

            self.scan_thread = threading.Thread(target=worker, daemon=True)
            self.scan_thread.start()

        @staticmethod
        def human_size(size: int) -> str:
            value = float(size)
            for unit in ("B", "KB", "MB", "GB"):
                if value < 1024 or unit == "GB":
                    return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
                value /= 1024
            return f"{size} B"

        def refresh_preview(self):
            if not hasattr(self, "preview_tree"):
                return
            query = self.preview_search_var.get().strip().lower()
            mode = self.preview_mode_var.get()

            self.preview_tree.delete(*self.preview_tree.get_children())

            visible = 0
            for row in self.scan_rows:
                if mode != "All" and row.status != mode:
                    continue
                hay = f"{row.path} {row.reason} {row.extension}".lower()
                if query and query not in hay:
                    continue

                self.preview_tree.insert(
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
            ignored = [r for r in self.scan_rows if r.status == "Ignored"]
            total_lines = sum(r.lines for r in included)
            total_bytes = sum(r.size_bytes for r in included)
            approx_tokens = max(1, total_bytes // 4) if included else 0

            self.stats_var.set(
                f"Included: {len(included):,}  |  Ignored: {len(ignored):,}  |  "
                f"Source lines: {total_lines:,}  |  Approx. raw tokens: {approx_tokens:,}  |  "
                f"Visible rows: {visible:,}"
            )

        # ------------------------ export ------------------------

        def start_export(self):
            if self.export_thread and self.export_thread.is_alive():
                return

            try:
                root, output = self.validate_paths()
                cfg = self.current_config()
            except Exception as exc:
                messagebox.showerror(APP_NAME, str(exc))
                return

            self.notebook.select(self.tab_generate)
            self.log_text.delete("1.0", "end")
            self.generate_button.configure(state="disabled")
            self.status_var.set("Generating Project Bible...")

            scan_snapshot = list(self.scan_rows) if self.scan_rows else None

            def worker():
                try:
                    result = export_project(
                        root,
                        output,
                        cfg,
                        scan_rows=scan_snapshot,
                        progress=lambda m: self.ui_queue.put(("log", m)),
                    )
                    self.ui_queue.put(("export_done", result))
                except Exception as exc:
                    self.ui_queue.put(("error", f"Generation failed:\n{exc}"))
                    self.ui_queue.put(("export_finished", None))

            self.export_thread = threading.Thread(target=worker, daemon=True)
            self.export_thread.start()

        def open_output(self):
            try:
                _, output = self.validate_paths()
                if not output.exists():
                    messagebox.showwarning(APP_NAME, "The output folder does not exist yet.")
                    return

                if sys.platform.startswith("win"):
                    os.startfile(str(output))  # type: ignore[attr-defined]
                elif sys.platform == "darwin":
                    subprocess.Popen(["open", str(output)])
                else:
                    subprocess.Popen(["xdg-open", str(output)])
            except Exception as exc:
                messagebox.showerror(APP_NAME, str(exc))

        # ------------------------ async queue ------------------------

        def _append_log(self, message: str):
            self.log_text.insert("end", str(message) + "\n")
            self.log_text.see("end")

        def _process_ui_queue(self):
            try:
                while True:
                    kind, payload = self.ui_queue.get_nowait()

                    if kind == "status":
                        self.status_var.set(str(payload))
                    elif kind == "log":
                        self._append_log(str(payload))
                        self.status_var.set(str(payload))
                    elif kind == "scan_done":
                        self.scan_rows = payload
                        self.refresh_preview()
                        self.status_var.set("Scan complete.")
                    elif kind == "export_done":
                        result: ExportResult = payload
                        self._append_log("")
                        self._append_log(f"Exported files: {result.exported:,}")
                        self._append_log(f"Bundles: {result.bundles:,}")
                        self._append_log(f"Source lines: {result.source_lines:,}")
                        self._append_log(f"Approx. raw tokens: {result.estimated_tokens:,}")
                        self._append_log(f"Added: {result.added:,} | Modified: {result.modified:,} | Removed: {result.removed:,}")
                        self._append_log(f"Output: {result.output_dir}")
                        self.status_var.set("Project Bible generated successfully.")
                        self.generate_button.configure(state="normal")
                        messagebox.showinfo(
                            APP_NAME,
                            "Project Bible generated successfully!\n\n"
                            f"Files: {result.exported:,}\n"
                            f"Bundles: {result.bundles:,}\n"
                            f"Source lines: {result.source_lines:,}\n"
                            f"Approx. raw tokens: {result.estimated_tokens:,}\n\n"
                            f"{result.output_dir}",
                        )
                    elif kind == "export_finished":
                        self.generate_button.configure(state="normal")
                    elif kind == "error":
                        self.status_var.set("Error.")
                        self.generate_button.configure(state="normal")
                        messagebox.showerror(APP_NAME, str(payload))

            except queue.Empty:
                pass

            self.after(100, self._process_ui_queue)

    App().mainloop()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=APP_NAME)
    parser.add_argument("--project", help="Source project folder")
    parser.add_argument("--output", help="Output folder")
    parser.add_argument("--preset", choices=["default", "tibia-idle"], default="default")
    parser.add_argument("--roots", nargs="*", help="Top-level folders to include")
    parser.add_argument("--max-lines", type=int, help="Maximum lines per generated bundle")
    parser.add_argument("--max-file-mb", type=float, help="Maximum source file size in MB")
    parser.add_argument("--no-gitignore", action="store_true")
    parser.add_argument("--no-git-diff", action="store_true")
    parser.add_argument("--save-config", action="store_true")
    parser.add_argument("--gui", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()

    if args.gui or not args.project:
        launch_gui()
        return 0

    root = Path(args.project).expanduser().resolve()
    if not root.is_dir():
        print(f"Invalid project: {root}", file=sys.stderr)
        return 2

    cfg = tibia_idle_config() if args.preset == "tibia-idle" else load_config(root)

    if args.roots is not None:
        cfg["selected_roots"] = args.roots
    if args.max_lines is not None:
        cfg["max_lines_per_bundle"] = args.max_lines
    if args.max_file_mb is not None:
        cfg["max_source_file_mb"] = args.max_file_mb
    if args.no_gitignore:
        cfg["respect_gitignore"] = False
    if args.no_git_diff:
        cfg["include_git_diff"] = False

    if args.save_config:
        path = save_config(root, cfg)
        print(f"Saved config: {path}")

    output = Path(args.output).expanduser().resolve() if args.output else root / DEFAULT_OUTPUT_DIRNAME

    rows = scan_project(root, output, cfg, progress=print)
    result = export_project(root, output, cfg, scan_rows=rows, progress=print)

    print(json.dumps(asdict(result), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
