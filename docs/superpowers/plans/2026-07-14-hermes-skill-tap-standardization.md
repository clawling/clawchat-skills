# Hermes Skill Tap Standardization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert the repository into a standard Hermes multi-skill GitHub tap with complete, independently installable OfficeCLI, Hermes BOOT Hook, and Tarot Arcana skills.

**Architecture:** Place both skills as direct children of `skills/`, express categories through metadata and `skills.sh.json`, and keep every runtime dependency under an allowed support directory. Add a repository-level verifier that applies Hermes-compatible support-file discovery rules and exercises runtime paths after migration.

**Tech Stack:** Markdown/YAML frontmatter, JSON, Python 3, Node.js, POSIX shell, GitHub tap conventions

---

### Task 1: Add a failing tap-layout verifier

**Files:**
- Create: `tests/verify_skill_tap.py`
- Reference: `docs/superpowers/specs/2026-07-14-hermes-skill-tap-standardization-design.md`

- [ ] **Step 1: Write the verifier**

Create a stdlib-only Python script that checks:

- All three expected `skills/<name>/SKILL.md` files exist.
- The old `creative/tarot-arcana`, `productivity/clawchat-officecli`, and root `create-hermes-boot-hook` paths do not exist.
- `skills.sh.json` contains the exact Productivity and Creative groupings.
- Every path under `references/`, `templates/`, `scripts/`, `assets/`, or `examples/` directly referenced by each `SKILL.md` exists.
- Every file below those allowed support directories is directly referenced by that skill's `SKILL.md`.
- README files contain the tap add command, both tap install identifiers, and new skill directory links.

- [ ] **Step 2: Run the verifier and confirm RED**

Run: `python3 tests/verify_skill_tap.py`

Expected: non-zero exit with missing skill-directory failures.

### Task 2: Migrate ClawChat OfficeCLI

**Files:**
- Move: `productivity/clawchat-officecli/` → `skills/clawchat-officecli/`
- Move: `skills/clawchat-officecli/web/` → `skills/clawchat-officecli/assets/web/`
- Modify: `skills/clawchat-officecli/SKILL.md`
- Modify: `skills/clawchat-officecli/scripts/office-live-directory.py`

- [ ] **Step 1: Move the skill and static site**

Use filesystem moves so Git records the existing files as renames, with no duplicate legacy copy.

- [ ] **Step 2: Repair runtime paths**

Change the Office directory server static root from `web` to `assets/web` and update comments that encode the old categorized install path.

- [ ] **Step 3: Declare every runtime support file**

Add a `Bundled Files` section to the main `SKILL.md` that directly references all files under `scripts/`, `references/`, and `assets/`.

- [ ] **Step 4: Run focused checks**

Run:

```bash
python3 -m py_compile skills/clawchat-officecli/scripts/*.py
bash -n skills/clawchat-officecli/scripts/*.sh
test -f skills/clawchat-officecli/assets/web/index.html
```

Expected: exit status 0.

### Task 3: Migrate Tarot Arcana

**Files:**
- Move: `creative/tarot-arcana/` → `skills/tarot-arcana/`
- Move: `skills/tarot-arcana/data/deck.json` → `skills/tarot-arcana/assets/deck.json`
- Move: `skills/tarot-arcana/liveware/static/` → `skills/tarot-arcana/assets/liveware/`
- Move: `skills/tarot-arcana/liveware/server.py` → `skills/tarot-arcana/scripts/liveware/server.py`
- Move: `skills/tarot-arcana/liveware/scripts/setup.py` → `skills/tarot-arcana/scripts/liveware/setup.py`
- Move: `skills/tarot-arcana/liveware/scripts/start.sh` → `skills/tarot-arcana/scripts/liveware/start.sh`
- Modify: `skills/tarot-arcana/SKILL.md`
- Modify: `skills/tarot-arcana/references/liveware-app.md`
- Modify: `skills/tarot-arcana/scripts/draw-tarot.mjs`
- Modify: `skills/tarot-arcana/scripts/liveware/server.py`
- Modify: `skills/tarot-arcana/scripts/liveware/setup.py`
- Modify: `skills/tarot-arcana/scripts/liveware/start.sh`

- [ ] **Step 1: Move the skill and normalize support directories**

Preserve all existing content while relocating it under the standard tap root and allowed support directories. Remove empty legacy directories.

- [ ] **Step 2: Repair runtime paths and documentation**

Resolve the deck at `assets/deck.json`, serve Liveware from `assets/liveware`, and update every command or message that references the old `liveware/` path.

- [ ] **Step 3: Declare every runtime support file**

Add a `Bundled Files` section to the main `SKILL.md` that directly references all files under `scripts/`, `references/`, and `assets/`, including each static card and built frontend asset.

- [ ] **Step 4: Run focused checks**

Run:

```bash
node --check skills/tarot-arcana/scripts/draw-tarot.mjs
python3 -m py_compile skills/tarot-arcana/scripts/liveware/*.py
bash -n skills/tarot-arcana/scripts/liveware/*.sh
node skills/tarot-arcana/scripts/draw-tarot.mjs --spread one_card --question smoke-test
node skills/tarot-arcana/scripts/draw-tarot.mjs --spread three_card --question smoke-test
test -f skills/tarot-arcana/assets/liveware/index.html
```

Expected: syntax checks exit 0 and draw commands return valid JSON with one and three cards respectively.

### Task 4: Migrate Create Hermes BOOT Hook

**Files:**
- Move: `create-hermes-boot-hook/` → `skills/create-hermes-boot-hook/`
- Modify: `skills/create-hermes-boot-hook/SKILL.md`

- [ ] **Step 1: Move the skill**

Move the complete skill directory under the standard tap root without keeping a duplicate legacy path.

- [ ] **Step 2: Add classification and installation completeness metadata**

Add Hermes tags `[Automation, Hermes, Hooks, Liveware]` and ensure the main skill directly references `references/hermes-boot-hooks.md`.

### Task 5: Add tap metadata and update documentation

**Files:**
- Create: `skills.sh.json`
- Modify: `README.md`
- Modify: `README_zh.md`

- [ ] **Step 1: Add category groupings**

Create `skills.sh.json` with `$schema` set to
`https://skills.sh/schemas/skills.sh.schema.json`, Productivity containing
`clawchat-officecli`, Automation containing `create-hermes-boot-hook`, and
Creative containing `tarot-arcana`.

- [ ] **Step 2: Update both README files**

Link headings to `skills/clawchat-officecli/` and `skills/tarot-arcana/`. Replace Raw `SKILL.md` URL commands with the tap workflow and per-skill identifiers:

```bash
hermes skills tap add clawling/clawchat-skills
hermes skills install clawling/clawchat-skills/clawchat-officecli
hermes skills install clawling/clawchat-skills/create-hermes-boot-hook
hermes skills install clawling/clawchat-skills/tarot-arcana
```

Keep each install command directly below its matching skill, with the shared tap-add prerequisite stated once before the skill list.

- [ ] **Step 3: Run the repository verifier and confirm GREEN**

Run: `python3 tests/verify_skill_tap.py`

Expected: `PASS: Hermes skill tap structure is complete` and exit status 0.

### Task 6: Update repository tests for migrated paths

**Files:**
- Modify: `tests/creating_liveware_scripts/test_validate_scripts.py`

- [ ] **Step 1: Replace repository-fixture paths**

Update tests that open the checked-in Tarot and Office skill fixtures so they use the new `skills/<name>/` locations and normalized Tarot Liveware script paths.

- [ ] **Step 2: Run the existing test suite**

Run: `python3 -m unittest discover -s tests -p 'test_*.py'`

Expected: all existing repository tests pass.

### Task 7: Final verification and commit

**Files:**
- Verify all files changed in Tasks 1–6.

- [ ] **Step 1: Run the complete verification suite**

Run the repository verifier, Python compilation, shell syntax checks, Node syntax check, both Tarot draw modes, JSON parsing checks, static-entry checks, and `git diff --check`.

Expected: every command exits 0; Tarot outputs contain exactly one and three cards; no whitespace errors.

- [ ] **Step 2: Review migration scope**

Run: `git status --short && git diff --stat && git diff -- README.md README_zh.md skills.sh.json tests/verify_skill_tap.py`

Expected: only the planned design/plan, test, metadata, README, and two skill migrations are present.

- [ ] **Step 3: Commit**

```bash
git add README.md README_zh.md skills.sh.json skills tests docs/superpowers/plans/2026-07-14-hermes-skill-tap-standardization.md
git commit -m "refactor: standardize hermes skill tap layout"
```

Expected: one commit containing the complete standardization migration.
