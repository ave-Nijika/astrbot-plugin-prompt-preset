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
- 用 `{{memories}}` 引用 LivingMemory 检索到的记忆
- 拖拽排序、一键开关、变量替换——全部在 WebUI 面板里操作

## 功能

### 条目编排

- 每条目独立设置：排序权重（order）、角色（system/user/assistant）、内容、开关
- 浮点数 order 可插任意间隙（0.5 插在 0 和 1 之间）
- `source` 三种：text（自定义文本）、persona（引用人格全文）、chat_history（对话历史）
- 变量替换：`{{persona}}`、`{{native_system}}`、`{{memories}}`、`{{user_name}}`、`{{bot_name}}`、`{{time}}`、`{{date}}` 等

### WebUI 面板

插件详情页 → Pages → preset，可视化操作：
- 条目列表按 order 排列，拖拽排序（拖完自动重编号）
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
| `entries` | 条目列表（首次安装时灌入 presets.json） | 人格 + 自定义提示词两条脚手架 |
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
- AstrBot 原生的 system_prompt（安全模式/工具调用等）在启用后会被覆盖——如需保留请添加 `{{native_system}}` 条目
- `/preset add` 只支持 source=text 条目；persona/chat_history 条目请在 WebUI 面板或编辑 presets.json 配置
- 拖拽排序后会整体等间距重编号（0/10/20/…），不支持保留精细间隙

## 开发

```bash
# 运行测试（纯标准库，不需要 astrbot 环境）
python -m pytest tests/ -q

# 项目结构
core/
  assembler.py     # 组装引擎（条目排序 → 消息列表重建）
  entry_store.py   # 条目持久化（JSON）
  variables.py     # 变量替换引擎
main.py            # 插件入口（钩子 + 命令 + Web API 注册）
pages/preset/      # WebUI 面板（HTML + CSS + 原生 JS）
dashboard_api.py   # API 业务层（框架无关）
tests/             # 测试套件（139 条）
```

## License

[MIT](LICENSE)