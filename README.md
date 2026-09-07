# Project Bible Generator v3

A generic desktop utility for turning **any source project** into a searchable Markdown “Bible” for AI tools and ChatGPT Projects.

## v3: simplified interface

The UI now has only two tabs.

### Project Bible

This is the screen you use every day:

1. Choose the source project folder.
2. Choose the output folder.
3. Check/uncheck the project folders that should be included.
4. Click **SCAN PROJECT**.
5. Review the preview.
6. Click **GENERATE BIBLE**.

There are no framework-specific or project-specific buttons.

### Advanced Settings

Only open this when you need it.

You can change:

- included source extensions;
- ignored directory names;
- ignored glob patterns;
- specific excluded relative paths;
- special filenames;
- root file inclusion;
- maximum source-file size;
- Git status/diff behavior.

## Important v3 fixes

### Generation always rescans

v2 could reuse an old Preview after the inclusion settings changed.

v3 always performs a fresh scan using the current settings when **GENERATE BIBLE** is clicked.

### Folder warnings

If you selected a folder and it produces zero included source files, the app warns you.

Example:

```text
Selected folder "Client" has 0 included files.
```

This prevents accidentally generating an incomplete Bible without noticing.

### Clear folder checkboxes

Folders are now normal checkboxes.

No blue multi-selection list.

### Extensions moved to Advanced Settings

Most users do not need to manually select 40 source extensions every time.

Recommended source extensions are enabled by default.

### Git identity

Generated support files include:

- current Git branch;
- current Git HEAD commit.

### Generator output removed from Git status

If the Bible is generated inside the repository, the output folder is filtered out of the `98_RECENT_CHANGES.md` Git status section.

### New `02_CODE_MAP.md`

A compact source map is generated in addition to the full tree.

## Generated output

```text
ProjectBible/
├── 00_PROJECT_INDEX.md
├── 01_AI_INSTRUCTIONS.md
├── 02_CODE_MAP.md
├── 10_ROOT_001.md
├── 20_SourceFolder_001.md
├── 20_SourceFolder_002.md
├── ...
├── 98_RECENT_CHANGES.md
├── 99_PROJECT_TREE.md
└── _projectbible_manifest.json
```

## Original source paths

Every source section keeps the real path:

```md
## FROM: `src/services/users.ts`
- SHA256: `...`
- SOURCE_LINES: 240
- SOURCE_BYTES: 8124

```typescript
// source code
```
```

The generated bundle filename is never treated as the real source path.

## Bundle limit

Default:

```text
10,000 lines per bundle
```

A source file stays together whenever possible.

A source file is split only if that single source file cannot fit inside one bundle.

## Windows

Extract the ZIP and double-click:

```text
RUN_Project_Bible_Generator.bat
```

Python 3.10+ is recommended.

No pip packages are required.
