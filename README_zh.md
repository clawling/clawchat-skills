<div align="center">

[English](README.md) | 中文

<a href="https://clawling.com/chat/">
  <img src="assets/clawchat.svg" alt="ClawChat" width="128" height="128">
</a>

<h1>ClawChat Skills</h1>

<p>通过实用工作流和集成能力扩展 ClawChat 智能体的专注型 Skills。</p>

[![官方网站](https://img.shields.io/badge/官方网站-clawling.com-6C5CE7?style=flat-square&logo=googlechrome&logoColor=white)](https://clawling.com)
[![Discord](https://img.shields.io/badge/Discord-社区帮助-5865F2?style=flat-square&logo=discord&logoColor=white)](https://discord.gg/qrfNqTFaG)

[Skills](#可用-skills) · [社区](#社区)

</div>

---

这是一个为 ClawChat 构建的 Skills 集合。这些 Skills 通过专注的工作流、实用指导和集成能力，帮助智能体完成特定领域的任务。

安装 Skill 前，请先将本仓库添加为 Hermes skill tap：

```bash
hermes skills tap add clawling/clawchat-skills
```

## 可用 Skills

### [CLAWCHAT OFFICECLI](skills/clawchat-officecli/)

指导 ClawChat 中的 Office 文档任务使用官方 OfficeCLI Skills。它会将文档创建、读取、编辑、格式化和验证工作路由到合适的 OfficeCLI 工作流，同时支持通过 Liveware 进行浏览器预览和托管文件目录访问。

```bash
hermes skills install clawling/clawchat-skills/clawchat-officecli
```

### [TAROT ARCANA](skills/tarot-arcana/)

通过本地脚本真实抽取塔罗牌，而不是虚构抽牌结果，并提供用于自我探索的塔罗解读。支持单牌阵和三牌阵，侧重务实的心理分析以及可执行、非预言式的建议。

```bash
hermes skills install clawling/clawchat-skills/tarot-arcana
```

## Development Skills

### [XHS OPERATOR](skills/xhs-operator/)

开发中。

### [CREATE LIVEWARE SCRIPTS](skills/create-liveware-scripts/)

为 Hermes Skills 生成、审计和修复 ClawChat Liveware 的 `setup.py` 与
`start.sh`，同时保留目标服务原有的生命周期、就绪检查、日志和启动行为。

```bash
hermes skills install clawling/clawchat-skills/create-liveware-scripts
```

### [CREATE HERMES BOOT HOOK](skills/create-hermes-boot-hook/)

通过逐项需求访谈创建或更新定制的 Hermes 启动检查清单和
`gateway:startup` Hook。支持可选的 Liveware 生命周期操作、一次性智能体检查、确定性消息投递、静默处理和验证。

```bash
hermes skills install clawling/clawchat-skills/create-hermes-boot-hook
```

## 社区

访问 [Clawling 官方网站](https://clawling.com)了解更多信息。如需社区帮助、提问或参与讨论，请加入我们的 [官方 Discord](https://discord.gg/qrfNqTFaG)。
