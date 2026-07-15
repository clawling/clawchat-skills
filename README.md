<div align="center">

English | [中文](README_zh.md)

<a href="https://clawling.com/chat/">
  <img src="assets/clawchat.svg" alt="ClawChat" width="128" height="128">
</a>

<h1>ClawChat Skills</h1>

<p>Focused skills that extend ClawChat agents with practical workflows and integrations.</p>

[![Website](https://img.shields.io/badge/Website-clawling.com-6C5CE7?style=flat-square&logo=googlechrome&logoColor=white)](https://clawling.com)
[![Discord](https://img.shields.io/badge/Discord-Community%20Help-5865F2?style=flat-square&logo=discord&logoColor=white)](https://discord.gg/qrfNqTFaG)

[Skills](#available-skills) · [Community](#community)

</div>

---

A collection of skills built for ClawChat. These skills extend an agent with
focused workflows, practical guidance, and integrations for specialized tasks.

Add this repository as a Hermes skill tap before installing a skill:

```bash
hermes skills tap add clawling/clawchat-skills
```

## Available Skills

### [CLAWCHAT OFFICECLI](skills/clawchat-officecli/)

Guides Office document work in ClawChat through the official OfficeCLI skills.
It routes document creation, reading, editing, formatting, and validation to
the appropriate OfficeCLI workflow, while supporting Liveware for browser
previews and managed file-directory access.

```bash
hermes skills install clawling/clawchat-skills/clawchat-officecli
```

### [TAROT ARCANA](skills/tarot-arcana/)

Provides reflective tarot readings using cards drawn by a local script rather
than fabricated results. It supports one-card and three-card spreads with
grounded psychological interpretation and actionable, non-prophetic guidance.

```bash
hermes skills install clawling/clawchat-skills/tarot-arcana
```

## Development Skills

### [XHS OPERATOR](skills/xhs-operator/)

In development.

### [CREATE LIVEWARE SCRIPTS](skills/create-liveware-scripts/)

Generates, audits, and repairs ClawChat Liveware `setup.py` and `start.sh`
files for Hermes skills while preserving the target service's lifecycle,
readiness, logging, and launch behavior.

```bash
hermes skills install clawling/clawchat-skills/create-liveware-scripts
```

### [CREATE HERMES BOOT HOOK](skills/create-hermes-boot-hook/)

Creates or updates customized Hermes startup checklists and
`gateway:startup` hooks through a one-question-at-a-time requirements
interview. It supports optional Liveware lifecycle actions, one-shot agent
checks, deterministic delivery, silence handling, and validation.

```bash
hermes skills install clawling/clawchat-skills/create-hermes-boot-hook
```

## Community

Visit the [Clawling website](https://clawling.com) to learn more. For community
help, questions, and discussion, join the [official Discord](https://discord.gg/qrfNqTFaG).
