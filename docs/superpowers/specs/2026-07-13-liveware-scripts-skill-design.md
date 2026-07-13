# Liveware setup/start 脚本生成 Skill 设计

## 目标

在当前仓库中创建一个项目级 Codex skill，用于为 Hermes skill 生成、检查和修复 ClawChat Liveware 接入脚本。

该 Codex skill 自身不是 Hermes skill。它面向 Hermes skill 开发过程，只操作目标项目中的：

```text
<target-skill>/liveware/scripts/setup.py
<target-skill>/liveware/scripts/start.sh
```

Skill 固定 Liveware 登录、应用状态、ClawChat 注册和 tunnel 绑定协议，但不规定目标 server 必须使用 Python、Node、静态站点、进程脚本或某种服务管理器。

## 安装位置与名称

项目级 Codex skill 放在：

```text
.agents/skills/creating-liveware-scripts/
```

Codex 从仓库根目录的 `.agents/skills` 自动发现它。Skill 只在当前仓库及其子目录中使用。

## 语言规范

该 Codex skill 的全部可交付内容统一使用英文，包括：

- `SKILL.md` 和 `agents/openai.yaml`。
- `references/` 中的规范文档。
- `scripts/` 中的帮助文本、错误消息、注释和 docstring。
- `assets/` 中的模板、代码注释和用户提示。
- 最终生成的 `setup.py` 与 `start.sh` 中由本 skill 新增的输出和错误消息。

目标项目中已有的命令、路径、服务名称及 `SKILL.md` 元数据值按原样使用，不做翻译。例如目标 Hermes skill 明确提供的 `display_name` 可以是非英文文本。

本设计文档保留中文，便于项目设计审阅；它不属于最终 skill 的运行内容。

## 用户场景

Skill 支持三类请求：

1. 为一个新的 Hermes skill 生成标准 `setup.py` 和 `start.sh`。
2. 检查已有 Liveware 脚本是否符合规范。
3. 修复已有脚本，同时保留目标 server 正确的启动、生命周期和日志策略。

目标 skill 根目录必须包含 `SKILL.md`。生成路径固定，不提供其他目录布局变体。

## 总体方案

采用“分析器 + 标准模板 + 校验器”的混合方案：

```text
.agents/skills/creating-liveware-scripts/
├── SKILL.md
├── agents/
│   └── openai.yaml
├── scripts/
│   ├── analyze_target.py
│   ├── render_scripts.py
│   └── validate_scripts.py
├── assets/
│   ├── setup.py.tmpl
│   └── start.sh.tmpl
└── references/
    └── liveware-script-contract.md
```

- `SKILL.md` 定义触发条件、操作顺序、歧义处理和验证边界。
- `analyze_target.py` 只读分析目标 skill 和 server 接口。
- `render_scripts.py` 使用分析结果生成或修复脚本。
- `validate_scripts.py` 检查脚本结构、安全约束和项目一致性。
- `setup.py.tmpl` 固定全部 Liveware setup 行为。
- `start.sh.tmpl` 固定 Liveware 绑定段，并为目标 server 适配段保留明确边界。
- `liveware-script-contract.md` 保存详细字段、状态和错误契约，避免让 `SKILL.md` 过长。

生成后的 `setup.py` 和 `start.sh` 必须自包含；运行时不能依赖这个 Codex skill 的安装路径。

## 目标分析

### 输入

分析器接收目标 Hermes skill 根目录，并定位：

```text
<target-skill>/SKILL.md
<target-skill>/liveware/
```

### Skill 元数据

分析器在生成阶段读取 `SKILL.md` YAML frontmatter：

- `name`：必需，作为稳定的 skill 标识。
- `display_name`：可选，作为 ClawChat 中的展示名称。
- 缺少 `display_name` 时使用 `name`。

最终脚本写入已确认的常量，不在运行时重新解析 `SKILL.md`。

示例：

```python
SKILL_NAME = "tarot-arcana"
CLAWCHAT_APP_NAME = "Tarot Arcana"
```

### Server 适配分析

Skill 不要求 server 具有特定形态。分析器只描述如何使用用户已经提供的 server。

只读检查顺序：

1. 已有启动脚本、服务配置和 Liveware 文档。
2. `package.json` scripts、Python 项目配置、Docker、s6、supervisor 或其他项目声明。
3. 明确的入口文件及其监听配置。
4. 静态资源目录。
5. 已有 `start.sh` 中正确的 server 适配逻辑。

分析结果至少包含：

- 工作目录。
- 现有启动入口或静态目录。
- 目标 server 的生命周期所有者。
- 默认监听地址和端口（适用时）。
- 健康检查方式（适用时）。
- 日志所有者。
- 每项判断的文件证据。
- 状态：`ready`、`ambiguous` 或 `blocked`。

分析器不执行未知项目代码，不自动安装依赖，也不修改 server。

存在多个入口、多个冲突端口或证据不足时返回 `ambiguous`。Codex 必须停止生成，并一次只向用户询问一个具体问题；不能使用猜测值继续。

默认端口以生成阶段从入口或配置中检测到的值为主。生成的 `start.sh` 可保留 `PORT` 环境变量作为运行时覆盖，但不要求用户每次传入端口参数。运行时端口必须验证为 `1` 到 `65535` 的纯数字。

## 应用名称与状态

区分 Liveware 内部名称和 ClawChat 展示名称：

- `liveware app create` 使用稳定的 skill `name`。
- `register_app` 使用 `display_name`；缺失时使用 `name`。
- 状态文件名使用 skill `name`。

每个 Hermes agent 可以拥有多个 Liveware 应用。应用状态固定写入：

```text
$HOME/.clawling/apps/<skill-name>.json
```

状态格式：

```json
{
  "schema_version": 1,
  "skill_name": "tarot-arcana",
  "app_name": "Tarot Arcana",
  "app_id": "app-xxx",
  "public_url": "https://app-xxx.apps.clawling.io",
  "registered": true
}
```

约束：

- `$HOME/.clawling` 与 `apps` 目录权限为 `0700`。
- 状态文件权限为 `0600`。
- 使用同目录临时文件写入并原子替换。
- 状态文件不保存 token、ClawChat 凭据或 Liveware 登录凭据。
- 状态中的 skill 名称和 App ID 必须验证后才能使用。

## `setup.py` 契约

`setup.py` 只处理 Liveware 应用准备和 ClawChat 注册，不启动目标 server，也不绑定 tunnel。

执行顺序：

1. 解析 Liveware CLI：`LIVEWARE_BIN` 覆盖、`PATH`、`$HERMES_HOME/clawchat/liveware/liveware`。
2. 导入 ClawChat 插件：优先正常 Python 导入；失败后检查 `$HERMES_HOME/plugins/clawchat`。
3. 调用 `clawchat_gateway.tools.liveware_login()`；禁止自行读取或传递 token。
4. 读取并验证目标 skill 的状态 JSON。
5. 若状态中存在 App ID，使用 `liveware app inspect` 验证它。
6. 状态缺失或失效时，执行 `liveware app list`，只接受与 skill `name` 精确匹配的应用。
7. 找不到时执行 `liveware app create <skill-name> --agent-type hermes`。
8. 保存 App ID 与确定性公网 URL，并暂记 `registered: false`。
9. 调用 `clawchat_gateway.tools.register_app()`，展示名使用 `display_name`。
10. 注册成功后原子更新为 `registered: true`。

应用创建成功但注册失败时保留 App ID 和 `registered: false`。下次运行必须复用该应用并只重试注册，避免重复创建。

应用查找不得回退到列表第一项，不得模糊匹配其他 skill，也不得为了配额删除现有应用。

## `start.sh` 契约

`start.sh` 由两个逻辑区域组成：

1. 目标 server 适配段。
2. 标准 Liveware 绑定段。

### 目标 server 适配段

适配段由分析证据生成，沿用用户提供的 server 形式：

- Python 或 Node 入口使用项目已经声明的启动方式。
- 已有脚本直接调用已有脚本，不复制其内部实现。
- 现有服务使用其已有安全启动方式，或只检查已由外部管理的服务。
- 纯静态目录不创建 server 进程。
- 目标项目已有日志和 PID 管理时必须沿用。
- 只有项目原本缺少日志策略且由 `start.sh` 直接启动普通进程时，才捕获其 stdout/stderr。

Skill 不改变依赖结构，不执行 `npm install`、`pip install` 或其他下载命令。依赖缺失时停止并给出明确提示。

### 标准 Liveware 绑定段

绑定段必须：

1. 从 `$HOME/.clawling/apps/<skill-name>.json` 读取并验证 App ID。
2. 状态缺失时提示先运行 `setup.py`；不得自动调用 setup。
3. 对动态服务确认本地服务已就绪，再绑定到明确的 loopback upstream。
4. 对静态目录使用 `liveware tunnel bind-static`。
5. 服务未就绪、入口不安全或状态无效时停止，不绑定 tunnel。
6. 不删除应用，不杀死未知进程，不接管项目已有生命周期。
7. 成功后在 stdout 输出简短状态与公网地址，例如：

   ```text
   Liveware ready: https://app-xxx.apps.clawling.io
   ```

该输出是调用结果，不是 server 日志。原始 server 和 tunnel 日志遵循目标项目已有的日志策略，不强制创建统一日志目录。

## 安全要求

- 登录只能通过 ClawChat 插件工具完成。
- 禁止读取、输出、保存或直接传递 ClawChat token。
- Python 子进程必须使用参数数组，不使用 `shell=True`。
- 生成的 shell 命令必须正确引用静态生成值；运行时输入必须先验证。
- 动态服务默认只允许 tunnel 绑定 `127.0.0.1`。
- App ID、skill 名称、端口、域名和 JSON 字段必须验证。
- 错误消息不得包含 token 或凭据。
- 缺少 Liveware CLI 或 ClawChat 插件时明确失败，不自动下载安装。
- 端口被未知进程占用时失败，不终止未知进程。

## 生成、检查与修复

### 生成

1. 运行分析器。
2. Codex 审查分析证据。
3. 分析状态为 `ready` 时渲染两个固定路径脚本。
4. 分析状态为 `ambiguous` 或 `blocked` 时停止并向用户澄清。
5. 写入后执行允许的静态检查。

### 检查

检查必须只读，并报告：

- 固定文件路径是否存在。
- setup/start 职责是否分离。
- 应用命名、查找和状态协议是否正确。
- 是否存在 token 处理、`shell=True`、不安全 shell 拼接或宽松应用回退。
- start 的 server 适配是否与当前项目证据一致。
- 是否错误安装依赖、杀死未知进程或覆盖用户 server 生命周期。
- Python 与 Bash 静态语法是否有效。

### 修复

- 完整重建不合规的 `setup.py`。
- 仅替换 `start.sh` 的 Liveware 绑定段。
- 保留与当前项目证据一致的 server 适配段。
- server 适配本身不一致时，根据当前项目重新生成，并在写入前展示差异。
- 不修改目标 server 源码、依赖清单或服务管理配置。
- 使用原子文件替换，修改后展示最终 diff。

## 验证边界

静态检查始终允许：

- `python -m py_compile`。
- `bash -n`。
- `validate_scripts.py` 的结构、安全和项目一致性检查。
- skill 目录的 `quick_validate.py`。

运行时或集成验证只在用户提供真实 Hermes/ClawChat/Liveware 环境时进行。没有真实环境时：

- 不运行生成的 `setup.py`。
- 不运行生成的 `start.sh`。
- 不创建假 ClawChat 插件、假 Liveware CLI 或假 server 来模拟成功。
- 明确报告“已完成静态检查，未进行运行时验证”。

即使存在真实环境，创建 Liveware 应用、注册 ClawChat 应用或绑定 tunnel 前也必须确认这些操作属于用户授权范围。

## Skill 自身验证

Skill 编写遵循 skill-creator 与 writing-skills 的要求：

- 在写 skill 内容前，用目标项目的真实文件做无 skill 基线任务，记录代理遗漏的规范项。
- 启用 skill 后重复相同任务，确认代理能生成正确的分析和脚本设计。
- 前向测试只验证 skill 工作流、静态分析和生成结果；不伪造 Liveware 运行环境，不执行未经授权的远程状态变更。
- 完成后运行 skill `quick_validate.py`。

## 非目标

本 skill 不负责：

- 创建或修改目标 server。
- 选择 Python、Node、静态站点或服务管理器。
- 安装目标项目依赖。
- 安装 Liveware CLI 或 ClawChat 插件。
- 管理 Liveware 应用配额、删除应用或迁移账号。
- 规范目标 server 的日志、PID 或部署架构。
- 在没有真实环境时模拟运行成功。

## 验收标准

1. Codex 能从项目根目录发现该 skill。
2. Skill 的本体、模板和自有用户提示全部使用英文。
3. Skill 能对目标 Hermes skill 生成固定路径的两个脚本。
4. 生成过程从 `SKILL.md` 提取稳定名称和展示名称，且不翻译用户提供的元数据值。
5. Skill 不改变用户提供的 server 形态。
6. 状态按 skill 隔离在 `$HOME/.clawling/apps`。
7. setup 登录、应用恢复、创建、状态写入和 ClawChat 注册行为幂等且安全。
8. start 沿用项目 server 接口，并只在服务可用后绑定 tunnel。
9. 检查器能发现当前 Office 和 Tarot 脚本中的关键协议差异。
10. 修复不会改动目标 server 实现或正确的生命周期管理。
11. 没有真实环境时只报告静态检查结果，不声称运行验证通过。

## 参考环境的地位

本地 `hermes-skill-test` 容器只用于了解实际 Hermes、ClawChat 插件和 Liveware CLI 的接口与安装差异，不作为新规范的来源。该容器当前未遵守本设计中的状态和脚本规范。
