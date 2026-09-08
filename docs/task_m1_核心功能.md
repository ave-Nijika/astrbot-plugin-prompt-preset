# 任务书：astrbot_plugin_prompt_preset —— 提示词条目编排插件

**项目**：AstrBot 插件，让用户像 SillyTavern 预设那样自由添加提示词条目、完全控制所有提示词的发送顺序与角色
**工作位置**：`D:\sandbox\prompt-preset`
**目标 AstrBot 版本**：v4.28.0（VM 上实测通过的版本）
**执行环境**：AstrBot venv（Python 3.12.9），插件安装至 `data/plugins/astrbot_plugin_prompt_preset/`
**交付**：可运行的完整插件 + pytest 全绿 + `docs/m1_report.md`
**执行者**：zcode。交付后由凛核验。

---

## 项目定位（一段话，开工前读完）

AstrBot 默认的 LLM 请求组装是固定的：persona 进 system_prompt、对话历史按时间排列、插件钩子按加载顺序追加。这个插件**完全接管这个组装过程**——把 persona、对话历史、自定义文本全部变成"条目"，每条有排序权重和角色，用户按任意顺序排列组合，插件按排序结果重建最终发给 LLM 的 messages 列表。用户因此获得对提示词的完全控制权。

## ⚠️ 核心设计原则（违反即打回）

1. **零固定位置**。没有任何条目被强制在"最前面"或"最后面"。全部由 `order` 数值决定，浮点数可插入任意间隙。
2. **零硬编码语义**。没有"世界观条目""思考框架条目"这类预设分类。条目就是条目，内容用户自己写。
3. **role 全开放**。每条目的 `role` 可以是 `system`/`user`/`assistant` 任意值，用户自定。
4. **AstrBot 原生内容不丢弃**。persona、LivingMemory 记忆、对话历史这些 AstrBot 本身会注入的内容，通过"来源引用"变成条目——用户决定它们的位置和去留，而不是插件替用户决定。
5. **热生效**。改配置不重启 AstrBot。

---

## 核心数据模型

### 条目（Entry）

```json
{
  "order": 0.0,
  "role": "system",
  "source": "text",
  "content": "【思考框架】① 回到身份：我是凛……② 理解主人的意图……",
  "enabled": true,
  "name": "思考框架"
}
```

| 字段 | 类型 | 说明 |
|---|---|---|
| order | float | 排序权重，升序排列。浮点数可插任意间隙。必填 |
| role | string | `system` / `user` / `assistant`。默认 system |
| source | string | `text` / `persona` / `memories` / `chat_history`。默认 text |
| content | string | 条目内容（source=text 时生效；支持变量替换） |
| enabled | bool | 开关。默认 true |
| name | string | 条目名（管理用，不发给 LLM） |

### source 类型说明

| source | 内容来源 | 说明 |
|---|---|---|
| `text` | content 字段 | 自定义文本，支持变量替换 |
| `persona` | AstrBot 当前人格全文 | 等价于 `{{persona}}` 变量 |
| `chat_history` | 对话历史（contexts） | 整段对话历史作为块插入 |

### 组装算法

`on_llm_request` 钩子触发时（此时 req.system_prompt 和 req.contexts 已含 AstrBot 原生注入）：

1. 收集原材料：
   - `persona_text` = 从 persona_manager 取当前 persona 的 system_prompt
   - `chat_history` = req.contexts（**原样，含 LivingMemory 的 fake messages 和所有历史**）
   - AstrBot 原生 system_prompt **不再使用**（被条目列表完全接管）
2. 遍历启用的条目，按 order 升序排列
3. 逐条生成消息：
   - source=text → 变量替换 content → 按 role 生成消息
   - source=persona → persona_text 作为消息 content（role 按条目配置）
   - source=chat_history → 将原始 contexts 中的消息展开插入当前位置
4. 写回 req.system_prompt 和 req.contexts

**关键**：完全接管意味着 AstrBot 原生的 system_prompt 被丢弃——persona、LivingMemory 记忆等都在条目列表里由用户控制。**如果用户没有放置 persona 条目，AstrBot 就没有 persona**——这是预期行为。

### 变量系统（source=text 的 content 中支持）

| 变量 | 展开为 |
|---|---|
| `{{persona}}` | AstrBot 当前人格全文 |
| `{{user_name}}` | 配置中的用户名 |
| `{{bot_name}}` | 配置中的机器人名 |
| `{{time}}` | 当前时间 HH:MM |
| `{{date}}` | 当前日期 YYYY-MM-DD |
| `{{datetime}}` | 日期+时间 |

---

## 插件结构

```
astrbot_plugin_prompt_preset/
├── main.py                    # Star 插件入口：注册钩子/命令/初始化
├── metadata.yaml
├── _conf_schema.json          # 配置：条目列表 JSON + 变量
├── core/
│   ├── assembler.py           # 组装引擎：条目排序 → 消息列表重建
│   ├── variables.py           # 变量替换引擎
│   └── entry_store.py         # 条目持久化（JSON 文件）
├── tests/
│   ├── test_assembler.py
│   ├── test_variables.py
│   └── test_commands.py
└── docs/
    └── m1_report.md
```

---

## 需求 A：组装引擎（core/assembler.py）

```python
class PromptAssembler:
    async def assemble(self, req, persona_text: str) -> None:
        """完全接管消息组装。

        读取条目配置，按 order 排序，逐条生成消息，写回 req。
        req.system_prompt 和 req.contexts 的原生内容被丢弃——
        所有内容由条目列表决定。
        """
```

**组装步骤**：
1. 读取条目列表（从 entry_store），过滤 enabled=true
2. 按 order 升序排序
3. 逐条生成消息 dict `{"role": role, "content": variable_replaced(content)}`：
   - source=text → content 做变量替换
   - source=persona → content = persona_text
   - source=chat_history → 展开 req.contexts 中的原始消息列表（保持原始顺序和 role）
4. 写回：
   - 第一条 role=system 的消息（或多条 system 消息）→ `req.system_prompt` = 拼接
   - 其余消息 → `req.contexts` = 消息列表（**完全替换**，含覆盖 LivingMemory 的 fake messages）
5. 如果条目列表为空（用户没配任何条目）→ **不做任何操作**，保留 AstrBot 原生行为

**边界情况**：
- persona_text 为空（无 persona 配置）→ persona 条目展开为空字符串
- req.contexts 为空 → chat_history 条目展开为空列表
- 条目全部 disabled → 不做任何操作（同空列表）

## 需求 B：条目持久化（core/entry_store.py）

- 存储为 JSON 文件：`data/plugin_data/astrbot_plugin_prompt_preset/presets.json`
- 提供 CRUD：`add(entry)` / `remove(name_or_id)` / `update(name_or_id, patch)` / `list_entries()` / `reorder(name, new_order)` / `toggle(name)`
- 热生效：`assembler` 每次从 store 读取最新条目列表

## 需求 C：变量替换引擎（core/variables.py）

```python
class VariableResolver:
    def __init__(self, context: dict): ...
    def resolve(self, text: str) -> str:
        """替换 {{key}} 格式的变量。未知变量保留原样（不替换不报错）。"""
```

- 上下文由调用方注入（persona_text / user_name / bot_name / time / date / datetime）
- 正则 `{{(\w+)}}` 匹配，查 dict 替换；找不到保留原样

## 需求 D：聊天命令（main.py）

| 命令 | 功能 |
|---|---|
| `/preset list` | 列出所有条目（名称/排序/角色/开关） |
| `/preset show <name>` | 显示条目详情 |
| `/preset add <order> <role> <name> <content>` | 添加条目 |
| `/preset del <name>` | 删除条目 |
| `/preset move <name> <new_order>` | 修改排序 |
| `/preset on <name>` / `/preset off <name>` | 启用/禁用 |
| `/preset reload` | 重新加载 JSON 文件 |
| `/living_status` | 显示当前组装结果预览（调试用：各条目的 order/role/前50字） |

## 需求 E：测试

- 组装引擎：条目排序、变量替换、persona 引用、chat_history 展开、空列表跳过、全 disabled 跳过
- 条目存储：CRUD 全流程、JSON 持久化
- 变量引擎：已知变量替换、未知变量保留、嵌套内容不替换
- 命令：mock event 验证各命令的参数解析和调用
- **集成测试**：mock ProviderRequest（含 system_prompt + contexts + persona），组装后断言最终 messages 的顺序与内容完全匹配条目配置

---

## ⚠️ 与 LivingMemory 的兼容性说明

LivingMemory 在自己的 `on_llm_request` 钩子里通过 `req.contexts.extend(fake_messages)` 把记忆以伪造工具调用消息对注入对话历史。本插件完全接管后：

- **chat_history 条目会包含 LivingMemory 的 fake messages**（它们已在 req.contexts 里）——记忆内容不会丢，只是位置由 chat_history 条目的 order 决定
- 两个插件的钩子执行顺序按插件加载顺序（字母序），LivingMemory（l）在本插件（p）之前执行。如果实测发现顺序反了，调整方式：本插件在钩子里主动调 `LivingMemoryBackend.probe()` 拿记忆（M0 的软依赖模式），**不依赖 req.contexts 中的 fake messages**——但这会增加复杂度，M1 先不做，M1 只需保证 chat_history 条目包含原始 contexts

---

## 配置文件（_conf_schema.json）

```json
{
  "entries": {
    "description": "提示词条目列表",
    "type": "object",
    "hint": "JSON 数组，按 order 升序组装。详见文档。",
    "default": [
      {"order": 0, "role": "system", "source": "persona", "content": "", "enabled": true, "name": "人格"},
      {"order": 10, "role": "system", "source": "text", "content": "", "enabled": true, "name": "自定义提示词"}
    ]
  },
  "variables": {
    "description": "自定义变量",
    "type": "object",
    "hint": "条目 content 中的 {{key}} 会被替换为此处的值。",
    "default": {"user_name": "主人", "bot_name": "凛"}
  },
  "enable": {
    "description": "启用本插件",
    "type": "bool",
    "default": true
  }
}
```

---

## ⚠️ 红线（打回项）

- ❌ 不修改 AstrBot 本体、不修改 LivingMemory。
- ❌ 不硬编码任何"推荐条目""预设模板"——条目内容全由用户自己写。
- ❌ 不做 WebUI 面板（M1 不做，后续再说）。
- ❌ 不做 ST 预设导入（M2 再做）。
- ❌ 不引入新依赖（httpx/aiohttp/aiosqlite 已在 venv 中可用）。
- ❌ 条目列表为空或全 disabled 时**必须不做任何操作**（保留 AstrBot 原生行为）。

## 汇报节点

1. 开工前若有歧义先问。
2. 交付附 `m1_report.md` + 测试结果，等凛核验。