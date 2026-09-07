# Project Bible Generator v4

A generic desktop utility that turns **any source project** into a searchable Markdown “Bible” for ChatGPT Projects and other AI workflows.

## v4 — rules separated from navigation

The generated support files now have clear responsibilities:

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

### `00_AI_RULES.md`

Mandatory AI behavior.

It contains generic safety/workflow rules plus optional project-specific rules.

Project/assistant instructions should explicitly tell the AI to read this file first.

### `01_BIBLE_GUIDE.md`

Navigation manual only:

- how to use the index;
- how to use the code map;
- how to use recent changes;
- when to open bundles;
- why `FROM:` is the real source path.

### `02_PROJECT_INDEX.md`

Maps every original source path to the bundle containing it.

### `03_CODE_MAP.md`

Compact list of included original source files grouped by top-level folder.

## AI Rules tab

v4 adds a dedicated **AI Rules** tab.

Write only rules that are specific to the current project, for example:

```md
- `Server/` is the authoritative backend.
- `ClientSource/` is the editable client source.
- `ClientRuntime/` is a generated/runnable copy and should not be edited first.
- Do not change production deployment configuration without explicit approval.
```

The text is saved in the source project as:

```text
.projectbible-rules.md
```

That file is generator metadata and is **not duplicated into the source bundles**.

When the Bible is generated, those project-specific rules are appended to `00_AI_RULES.md`.

## ChatGPT Project instruction

The AI Rules tab includes a **Copy ChatGPT instruction** button.

Paste the copied instruction into the ChatGPT Project's instruction field.

The default instruction is intentionally short:

> Before any technical task about this project, read and follow `00_AI_RULES.md` first. Then use `01_BIBLE_GUIDE.md` to navigate the Bible, `02_PROJECT_INDEX.md` to locate source files, `03_CODE_MAP.md` to understand the structure, and `98_RECENT_CHANGES.md` for recent work. Never treat generated bundle files as real source files; always use the original path shown after `FROM:`.

This means the ChatGPT Project instruction can remain almost identical for every project.  
Project-specific behavior belongs in `.projectbible-rules.md` / `00_AI_RULES.md`.

## Main workflow

1. Choose the source project.
2. Choose which top-level folders belong in the Bible.
3. Optionally add project-specific rules in **AI Rules**.
4. Click **SCAN PROJECT**.
5. Review included/ignored files.
6. Click **GENERATE BIBLE**.
7. Upload the generated Bible files as Project Sources.
8. Paste the copied ChatGPT Project instruction once.

## Advanced Settings

You normally do not need this tab.

It controls:

- source extensions;
- ignored directory names;
- ignored glob patterns;
- excluded relative paths;
- special filenames;
- `.gitignore`;
- Git status/diff;
- max source file size.

## Bundle size

The default hard limit remains 10,000 lines, and can be changed in the main window.

A source file stays together whenever possible. It is split only if that individual file cannot fit in one bundle.

## Windows

Extract the ZIP and double-click:

```text
RUN_Project_Bible_Generator.bat
```

Python 3.10+ is recommended. No pip packages are required.
