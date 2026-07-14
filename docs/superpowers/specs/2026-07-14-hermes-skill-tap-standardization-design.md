# Hermes Skill Tap Standardization Design

## Goal

Convert this repository into a standard multi-skill Hermes GitHub tap whose
skills are discoverable, independently installable, updateable, and complete
after installation, including required scripts and static assets.

## Repository Layout

The repository will use the Hermes default tap root with one skill per direct
child directory:

```text
skills/
├── clawchat-officecli/
│   ├── SKILL.md
│   ├── assets/
│   │   └── web/
│   ├── references/
│   └── scripts/
└── tarot-arcana/
    ├── SKILL.md
    ├── assets/
    │   ├── deck.json
    │   └── liveware/
    ├── references/
    └── scripts/
        └── liveware/
```

The existing `creative/` and `productivity/` copies will be removed by the
migration. Category information will remain in `SKILL.md` tags and in a root
`skills.sh.json` grouping file instead of directory nesting.

## OfficeCLI Migration

- Move `productivity/clawchat-officecli/` to
  `skills/clawchat-officecli/`.
- Move its `web/` directory to `assets/web/`.
- Update `scripts/office-live-directory.py` to resolve static files from
  `assets/web/`.
- Keep OfficeCLI helper programs in `scripts/` and documentation in
  `references/`.
- Add direct support-file references to the main `SKILL.md` for all three
  helper scripts, the Liveware reference, and every required web asset.

## Tarot Arcana Migration

- Move `creative/tarot-arcana/` to `skills/tarot-arcana/`.
- Move `data/deck.json` to `assets/deck.json`.
- Move the Liveware static site to `assets/liveware/`.
- Move the Liveware setup, start, and server programs to
  `scripts/liveware/`.
- Update the draw script, Liveware server, start script, setup output, main
  skill instructions, and Liveware reference to use the new paths.
- Add direct support-file references to the main `SKILL.md` for the draw
  script, deck, reference documents, Liveware programs, and every required
  Liveware static asset.

## Tap Metadata and Installation

Add `skills.sh.json` with two groupings:

- `Productivity`: `clawchat-officecli`
- `Creative`: `tarot-arcana`

The README files will describe the standard tap workflow:

```bash
hermes skills tap add clawling/clawchat-skills
hermes skills install clawling/clawchat-skills/clawchat-officecli
hermes skills install clawling/clawchat-skills/tarot-arcana
```

Skill headings will link to their new `skills/<name>/` directories. Direct
GitHub installation identifiers with the full `skills/<name>` path may be
mentioned only as an alternative to adding the tap.

## Installation Contract

Hermes copies `SKILL.md` plus explicitly referenced support files under the
allowed `references/`, `templates/`, `scripts/`, `assets/`, and `examples/`
directories. Each main `SKILL.md` must therefore directly mention every file
required at runtime. Nested references alone are not sufficient.

No required runtime file may remain under a nonstandard top-level directory
such as `data/`, `liveware/`, or `web/` inside a skill.

## Compatibility

This is an intentional repository-path migration. The old `creative/` and
`productivity/` paths will not be retained as duplicates or symlinks. Runtime
behavior and the skill names `clawchat-officecli` and `tarot-arcana` remain
unchanged.

## Verification

- Confirm the tap root has exactly the two expected direct child skill
  directories and each contains `SKILL.md`.
- Confirm no old `creative/` or `productivity/` skill directory remains.
- Parse each main `SKILL.md` with Hermes' referenced-support-file rules and
  verify every referenced file exists.
- Confirm all runtime files are directly referenced by the matching main
  `SKILL.md`.
- Run one-card and three-card Tarot draws and validate their JSON output.
- Run Python compilation checks for all Python helper programs.
- Run shell syntax checks for all shell helper programs.
- Check JavaScript syntax for the Tarot draw program.
- Confirm both Liveware static sites contain their required entry documents
  and referenced assets.
- Confirm README links, tap commands, skill install commands, and bilingual
  navigation.
- Run `git diff --check` and verify no unrelated files changed.
