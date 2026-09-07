# Project Bible Generator v2

**Turn any project into an AI-readable code bible.**

A GUI-first utility for converting source projects into searchable Markdown bundles that can be uploaded as **Sources** in a ChatGPT Project.

## Why this exists

Instead of making ChatGPT repeatedly crawl a repository, Project Bible Generator creates a textual snapshot of the project with each original path preserved:

```md
## FROM: `Client/modules/game_idle/squad.lua`
- SHA256: `...`
- SOURCE_LINES: 847
- SOURCE_BYTES: 24012

```lua
-- original source code
```
```

ChatGPT can then search the Bible, tell you exactly which real file to edit, and provide a focused before/after patch.

## GUI features

The app has five tabs:

### 1. Project

- Choose the source project folder.
- Choose the Bible output folder.
- Choose a preset.
- Max lines per bundle (default: 10,000).
- Max source-file size.
- Respect `.gitignore`.
- Include root files.
- Include Git status/diff.

### 2. Include

- Multi-select top-level folders.
- Multi-select allowed file extensions.
- Edit special filenames such as `CMakeLists.txt`, `Dockerfile`, `package.json`, etc.
- Quick `Canary + Client` selector.
- Quick `Code essentials` selector.

### 3. Ignore

- Edit ignored directory names.
- Edit ignored glob patterns.
- Exclude specific relative path prefixes.
- Restore defaults.
- Apply Tibia Idle ignore rules.

### 4. Preview

Before creating anything, click **SCAN PROJECT**.

The preview shows:

- Included / Ignored
- original path
- why the file was included/ignored
- lines
- size

There is also search and Included/Ignored filtering.

Statistics include an approximate raw-text token count.

### 5. Generate

Click **GENERATE PROJECT BIBLE**.

The operation runs in a background thread so the interface does not freeze.

## Tibia Idle preset

The built-in preset:

**Tibia Idle (Canary + Client)**

selects:

- `Canary`
- `Client`

and applies sensible ignore rules for source-code analysis.

Everything remains editable before scanning/generation.

## Generated files

Example:

```text
ProjectBible/
├── 00_PROJECT_INDEX.md
├── 01_AI_INSTRUCTIONS.md
├── 10_Canary_001.md
├── 10_Canary_002.md
├── 20_Client_001.md
├── 20_Client_002.md
├── 98_RECENT_CHANGES.md
├── 99_PROJECT_TREE.md
└── _projectbible_manifest.json
```

### 00_PROJECT_INDEX.md

Maps every real source path to its generated bundle and contains:

- path
- bundle
- line count
- byte size
- SHA-256
- changed files since previous export

### 01_AI_INSTRUCTIONS.md

Instructions for an AI consuming the Bible.

### 98_RECENT_CHANGES.md

Contains:

- files added since previous Bible generation
- files modified
- files removed
- current Git status
- local unstaged diff
- staged diff

### 99_PROJECT_TREE.md

A tree containing only files actually included in the Bible.

## 10,000-line rule

Bundles have a hard maximum of 10,000 lines by default.

The generator tries to keep a real source file together. If it would not fit in the current bundle, the entire source file starts in the next bundle.

A source file is only split into `PART 1/N`, `PART 2/N`, etc. when that single source file is itself too large to fit.

## Project configuration

Click **Save Project Config** in the app.

It creates:

```text
.projectbible.json
```

in the source project root.

Opening that project again reloads the configuration.

## Windows

Extract the ZIP and double-click:

```text
RUN_Project_Bible_Generator.bat
```

Python 3.10+ is recommended.

No `pip install` is required.

## CLI (optional)

The GUI is the intended workflow, but a CLI is included.

```powershell
python project_bible_generator.py --project "C:\Projects\Tibia-idle" --preset tibia-idle
```

Only Canary + Client:

```powershell
python project_bible_generator.py --project "C:\Projects\Tibia-idle" --roots Canary Client
```

Different line limit:

```powershell
python project_bible_generator.py --project "C:\Projects\Tibia-idle" --max-lines 10000
```

## Recommended workflow

1. Open Project Bible Generator.
2. Select the local project.
3. Choose the preset.
4. Review Include/Ignore settings.
5. **Scan Project**.
6. Verify the preview.
7. **Generate Project Bible**.
8. Upload the generated `.md` files to your ChatGPT Project Sources.
9. Ask ChatGPT for a task.
10. ChatGPT returns the exact real source path and the before/after code.
11. Apply it locally and test.
12. Generate the Bible again after meaningful code changes.
