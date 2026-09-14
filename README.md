# astrbot_plugin_prompt_preset

AstrBot 提示词条目编排插件——像 SillyTavern 预设那样自由添加、排序、开关提示词条目，完全接管 LLM 请求的消息组装。

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![AstrBot](https://img.shields.io/badge/AstrBot-v4.27.5+-orange.svg)](https://github.com/AstrBotDevs/AstrBot)
[![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://www.python.org)

## 这是什么

AstrBot 默认把 persona 写进 system_prompt、对话历史按时间排列——你无法控制它们的顺序。这个插件让你像 SillyTavern 预设那样：

- 把 persona、世界观、思考框架、越狱词条全部变成独立"条目"
- 每条设置排序权重（order）、角色（role: system/user/assistant）、开关
- 用 `{{native_system}}` 引用 AstrBot 内置的提示词（安全模式等），自由控制它们的位置
- 用 `{{native_safety}}`、`{{native_persona}}`、`{{native_tools}}` 等 12 个切块变量逐块控制内置提示词
- 用 `{{memories}}` 引用 LivingMemory 检索到的记忆
- 拖拽排序、一键开关、变量替换——全部在 WebUI 面板里操作

## 预置条目说明

### 设计动机

本插件启用后会**完全接管**提示词组装：AstrBot 原本的 system_prompt 和对话历史不再直接发送，而是由条目列表重建。为了让不熟悉机制的用户"装完即用、行为不变"，插件在首次启动时自动预置 13 条「原生-*」条目——把 AstrBot 原生提示词按**真实执行顺序**拆成独立块（安全模式、人设、技能、工具说明……），加上一条对话历史条目。这样启用插件前后发给 LLM 的消息语义完全一致，你不需要做任何操作；想改造时，逐块调整顺序、改写内容即可。

### 13 条预置条目对照表

顺序即 AstrBot 源码核实出的真实注入顺序（安全模式块在运行时被前置到最前，搜索引用块最后注入）：

| 条目 | 变量 | 说明 | 何时非空 | 常见调整 |
|---|---|---|---|---|
| 原生-安全模式 | `{{native_safety}}` | AstrBot「健康模式」注入的安全规则提示 | WebUI 中健康模式开启时 | 关闭健康模式后此条自动为空，无需处理 |
| 原生-ChatUI生成 | `{{native_genui}}` | ChatUI 内联 HTML 生成（GenUI）功能提示 | 消息事件携带 `enable_inline_genui` 时（默认关闭） | 不用 ChatUI 画页面的可禁用 |
| 原生-人格说明 | `{{native_persona}}` | `# Persona Instructions` 标题 + 当前人格全文 | 已配置并选中人格时 | 想让自定义提示词紧跟人设之后：新建条目把 order 设在 120-140 之间 |
| 原生-默认人格 | `{{native_default_persona}}` | webchat 专用默认人格（"calm, patient friend"） | webchat 会话且未选人格、未关闭默认人格开关时 | 一般保持默认 |
| 原生-技能说明 | `{{native_skills}}` | AstrBot 技能库清单与使用规则 | 存在启用的技能时 | 想弱化技能存在感可禁用（技能本身仍注册） |
| 原生-路由提示 | `{{native_router}}` | 子代理编排的路由提示（用户自定义配置文本） | 目前恒为空（该文本无固定标记，内容归"原生-其他插件注入"） | 预留变量 |
| 原生-沙箱说明 | `{{native_sandbox}}` | 沙箱运行时（执行 shell/Python）说明 | 计算机使用运行时 = 沙箱 时 | 与"原生-本地模式"互斥，二者只会有一个非空 |
| 原生-本地模式 | `{{native_local_mode}}` | 本机运行时说明（含操作系统与 shell 提示） | 计算机使用运行时 = 本地 时 | 同上，互斥 |
| 原生-工具说明 | `{{native_tools}}` | 工具调用行为提示（两种工具 schema 模式文本不同） | 请求带有可用工具时 | 禁用后模型仍能调用工具，只是缺少行为约束提示 |
| 原生-Live模式 | `{{native_live}}` | 实时语音对话模式提示 | Live 通话场景 | 平时自动为空 |
| 原生-搜索引用 | `{{native_websearch}}` | 搜索结果引用格式（`<ref>` 标注）提示 | 启用了网页搜索类工具时 | 想让引用更自然可改写本条内容 |
| 原生-其他插件注入 | `{{native_other}}` | 兜底块：无标记的注入内容（其他插件的 system_prompt 追加、原生块之前的前置文本等） | 存在无法识别归属的注入内容时 | 保持在最后，保证未知内容不丢失 |
| 对话历史 | （source=chat_history） | 展开完整对话历史（含 LivingMemory 记忆消息） | 始终（历史为空时展开 0 条） | 想把历史放到最前/中间：调整 order 即可 |

### 保护规则

- 预置条目**不可删除**（面板删除按钮置灰、聊天命令与 REST API 均拒绝），提示"预置条目不可删除，如不需要请禁用该条目"；
- **允许**：编辑 content、启用/禁用开关、拖拽排序；
- 空值条目自动跳过：变量无内容时（如健康模式关闭），对应条目**不会产生任何消息**，无需手动处理；
- 直接手改 `presets.json` 删除 preset 条目不受保护，且**不会自动重建**（预置只在首次初始化发生一次，标记文件 `initialized.flag` 写入后永不重复）。

### 恢复默认

每条预置条目的默认 content 就是其对应变量引用（见上表）。改乱后把 content 改回单个变量引用即可恢复默认行为。

### 变量参考

| 变量 | 展开为 |
|---|---|
| `{{native_system}}` | AstrBot 原生 system_prompt 整块快照（含全部内置块与其他插件注入） |
| `{{native_safety}}` / `{{native_genui}}` / `{{native_persona}}` / `{{native_default_persona}}` / `{{native_skills}}` / `{{native_router}}` / `{{native_sandbox}}` / `{{native_local_mode}}` / `{{native_tools}}` / `{{native_live}}` / `{{native_websearch}}` / `{{native_other}}` | 按标记切分的各内置块（见对照表） |
| `{{memories}}` | LivingMemory 注入的记忆文本（进阶用法：默认不预置，避免与 LivingMemory 自行注入重复） |
| `{{persona}}` | 当前人格全文 |
| `{{user_name}}` / `{{bot_name}}` | 配置中的自定义变量（默认 主人/凛） |
| `{{time}}` / `{{date}}` / `{{datetime}}` | 当前时间 HH:MM / 日期 YYYY-MM-DD / 日期+时间 |

> `native_` 为**保留变量前缀**：在自定义变量里配置 `native_*` 会被忽略并记录警告日志。未知变量保留原样不替换。

## 功能

### 条目编排

- 每条目独立设置：排序权重（order）、角色（system/user/assistant）、内容、开关
- 浮点数 order 可插任意间隙（0.5 插在 0 和 1 之间）
- `source` 三种：text（自定义文本）、persona（引用人格全文）、chat_history（对话历史）
- 变量替换：`{{persona}}`、`{{native_system}}`、`{{memories}}`、`{{user_name}}`、`{{bot_name}}`、`{{time}}`、`{{date}}` 等

### WebUI 面板

插件详情页 → Pages → preset，可视化操作：
- 条目列表按 order 排列，拖拽排序（拖完自动重编号）；预置条目带 🔒 原生徽标，删除按钮置灰
- 每条独立开关（绿色=启用，灰色=禁用）
- 右侧编辑器：名称/role 下拉/source 下拉/order 数字框/内容多行编辑
- 顶部工具栏：新增/导入 JSON/导出 JSON/变量编辑/组装预览
- 深色主题，跟随 dashboard

### 组装预览

实时显示当前条目配置下的最终消息序列——每条的 order/role/名称/内容摘要，不用盲调。

### 聊天命令

| 命令 | 功能 |
|---|---|
| `/preset list` | 列出所有条目 |
| `/preset show <name>` | 显示条目详情 |
| `/preset add <order> <role> <name> <content>` | 添加条目 |
| `/preset del <name>` | 删除条目 |
| `/preset move <name> <new_order>` | 修改排序 |
| `/preset on <name>` / `/preset off <name>` | 启用/禁用 |
| `/preset reload` | 重载 JSON 文件 |
| `/preset status` | 组装结果预览 |

## 安装

1. 在 AstrBot WebUI → 插件管理 → 从仓库安装，填入本仓库地址
2. 或手动克隆到 `data/plugins/astrbot_plugin_prompt_preset/`
3. 重启 AstrBot

## 配置

| 配置 | 说明 | 默认值 |
|---|---|---|
| `entries` | 附加自定义条目（追加在预置条目之后） | 空（默认 13 条预置由插件自动生成） |
| `variables` | 自定义变量（`{{key}}` 替换） | user_name / bot_name |
| `enable` | 启用本插件 | true |

### 条目字段说明

| 字段 | 说明 |
|---|---|
| `order` | 排序权重，升序。浮点数可插任意间隙 |
| `role` | 消息角色：system / user / assistant |
| `source` | 内容来源：text（自定义文本）、persona（人格全文）、chat_history（对话历史） |
| `content` | 条目内容（source=text 时生效，支持变量替换） |
| `enabled` | 启用/禁用 |
| `name` | 条目名称（管理用） |

### 使用示例

```json
[
  {"order": -50, "role": "system", "source": "text", "content": "【世界观】这是一个赛博朋克世界……", "enabled": true, "name": "世界观"},
  {"order": 0, "role": "system", "source": "persona", "content": "", "enabled": true, "name": "人格"},
  {"order": 10, "role": "system", "source": "text", "content": "【思考规则】回复前依次思考：①我是谁 ②对方在说什么 ③我现在心情如何 ④用我的方式说话", "enabled": true, "name": "思考框架"},
  {"order": 999, "source": "chat_history", "content": "", "enabled": true, "name": "对话历史"}
]
```

## 已知限制

- 条目列表为空或全部禁用时不做任何操作（保留 AstrBot 原生行为）
- AstrBot 原生提示词由预置条目自动保留（逐块引用）；删除或禁用对应条目即放弃该块内容
- `/preset add` 只支持 source=text 条目；persona/chat_history 条目请在 WebUI 面板或编辑 presets.json 配置
- 拖拽排序后会整体等间距重编号（0/10/20/…），不支持保留精细间隙

## 开发

```bash
# 运行测试（纯标准库，不需要 astrbot 环境）
python -m pytest tests/ -q

# 项目结构
core/
  assembler.py     # 组装引擎（条目排序 → 消息列表重建）
  entry_store.py   # 条目持久化（JSON，含预置一次性初始化与删除拦截）
  variables.py     # 变量替换引擎（含 extract_memories）
  splitter.py      # 原生 system_prompt 内置块切分（native_* 注册表）
main.py            # 插件入口（钩子 + 命令 + Web API 注册）
pages/preset/      # WebUI 面板（HTML + CSS + 原生 JS）
dashboard_api.py   # API 业务层（框架无关）
tests/             # 测试套件（208 条）
```

## License

[MIT](LICENSE)