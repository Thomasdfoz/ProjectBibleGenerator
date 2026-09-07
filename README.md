# Project Bible Generator v5.1

A generic desktop utility that turns any local source project into a searchable Markdown “Bible” for ChatGPT Projects and other AI workflows.

## What changed in v5

### AI Rules are generated from the selected project

There is no static project-rules template anymore.

Open the **AI Rules** tab and click:

```text
ANALYZE PROJECT & GENERATE RULES
```

The program inspects the project currently selected on the main tab and generates evidence-based rules from what it actually finds.

It can detect and use signals such as:

- Unity (`Assets/`, `ProjectSettings/`, Unity version);
- Node / package.json and common frameworks;
- Python project metadata;
- Go modules;
- Rust crates/workspaces;
- CMake / CMakePresets;
- .NET solution/project files;
- selected source folders;
- source-file density and common extensions;
- obvious build/output/generated folders;
- hidden repository/tooling folders;
- real package.json validation scripts.

The result is editable. Review it and click **Save**.

Project-specific rules are stored as:

```text
.projectbible-rules.md
```

and are merged into:

```text
00_AI_RULES.md
```

### Cleaner AI Rules layout

The Rules tab is now compact:

- title + action buttons at the top;
- one large rule editor;
- small bottom panels for:
  - built-in generic rules;
  - ChatGPT Project instruction.

The large empty vertical gap from v4.1 is removed.

### Smarter new-project folder defaults

Obvious generated/tooling folders are unchecked by default, while normal source/content folders stay checked.

Examples usually unchecked:

- hidden folders beginning with `.` or `_`;
- Build / Builds;
- output / outputs / out / dist;
- GeneratedAssets;
- Recordings;
- Unity Library / Temp / Logs;
- cache / node_modules / vendor.

You can still manually check any folder.

Saved per-project settings always take precedence.

## Generated Bible

```text
ProjectBible/
├── 00_AI_RULES.md
├── 01_BIBLE_GUIDE.md
├── 02_PROJECT_INDEX.md
├── 03_CODE_MAP.md
├── 10_ROOT_001.md
├── 20_<folder>_001.md
├── ...
├── 98_RECENT_CHANGES.md
├── 99_PROJECT_TREE.md
└── _projectbible_manifest.json
```

## Recommended workflow

1. Choose a project.
2. Check only the folders that belong in the Bible.
3. Open **AI Rules**.
4. Click **ANALYZE PROJECT & GENERATE RULES**.
5. Review and save.
6. Click **SCAN PROJECT**.
7. Review the preview.
8. Click **GENERATE BIBLE**.
9. Upload the generated files to ChatGPT Project Sources.
10. Use **Copy instruction** once in the ChatGPT Project instructions.

## Windows

Extract and double-click:

```text
RUN_Project_Bible_Generator.bat
```

Python 3.10+ recommended. No pip packages required.


## v5.1 — automatic AI Rules on Generate

`GENERATE BIBLE` now protects against accidentally creating a Bible without project-specific rules.

When generation starts:

```text
Are project-specific rules blank?
├─ No  -> keep the existing rules exactly as they are
└─ Yes -> analyze the selected project
          -> generate project-specific rules
          -> save .projectbible-rules.md
          -> update the AI Rules editor
          -> generate the Bible
```

Existing rules are **never overwritten automatically**.

This avoids having to generate a large Bible twice just because the AI Rules step was forgotten.
