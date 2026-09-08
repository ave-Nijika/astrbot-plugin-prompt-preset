# M1 交付报告：astrbot_plugin_prompt_preset 核心功能

**日期**：2026-09-08
**执行者**：zcode
**任务书**：`docs/task_m1_核心功能.md`（目标 AstrBot v4.28.0）
**状态**：已完成，待凛核验

---

## 1. 交付物清单

```
prompt-preset/                        # 仓库根 = 插件根（安装时拷贝至 data/plugins/astrbot_plugin_prompt_preset/）
├── main.py                           # Star 插件入口：on_llm_request 钩子 + /preset 全套命令 + /living_status
├── metadata.yaml                     # 插件元数据
├── _conf_schema.json                 # 配置：entries / variables / enable（照抄任务书）
├── core/
│   ├── __init__.py
│   ├── assembler.py                  # 需求 A：组装引擎 PromptAssembler
│   ├── entry_store.py                # 需求 B：条目持久化 EntryStore（JSON）
│   └── variables.py                  # 需求 C：变量替换 VariableResolver
├── tests/
│   ├── conftest.py                   # sys.path/包别名引导 + astrbot 缺失时的最小桩（见 §5）
│   ├── helpers.py                    # MockEvent / MockContext / MockProviderRequest / 命令运行器
│   ├── test_variables.py             # 需求 E：变量引擎
│   ├── test_entry_store.py           # 需求 E：CRUD 全流程 + JSON 持久化
│   ├── test_assembler.py             # 需求 E：组装引擎 + 端到端集成测试
│   └── test_commands.py              # 需求 E：mock event 命令测试 + 钩子守卫 + 配置灌入
├── docs/
│   ├── 项目总纲.md
│   ├── task_m1_核心功能.md
│   └── m1_report.md                  # 本文件
├── pytest.ini
└── .gitignore
```

核心模块（`core/`）零 astrbot 依赖，纯标准库，可独立测试；仅 `main.py` 依赖 astrbot API。

## 2. 测试结果

```
$ python -m pytest tests/ -q
109 passed in 0.53s
```

覆盖任务书需求 E 全部条目：条目排序（乱序/浮点插隙/同序稳定）、变量替换（已知/未知保留/嵌套不替换）、persona 引用（含空 persona）、chat_history 展开（含 LivingMemory 形态的 fake messages）、空列表跳过、全 disabled 跳过、CRUD 全流程、JSON 持久化（含损坏文件备份恢复）、mock event 命令测试、以及两个集成测试（直接调用 assembler 与完整钩子路径，断言最终 messages 逐字匹配条目配置）。

## 3. 开工前的源码二次核实（补充总纲 §3）

沙箱无 astrbot 环境，zcode 从 gitee 镜像取到 AstrBot v4.3.5 源码（2025-10 快照，老于目标的 v4.28.0）对插件面 API 做了二次核对，与总纲坐标互相印证：

| 事实 | 核实结果 | 对实现的影响 |
|---|---|---|
| 导入路径 | `from astrbot.api.event import filter, AstrMessageEvent`（`filter` 是子包）；`astrbot.api.star`/`api.provider`/`api` 均按总纲 | main.py 导入写法 |
| 钩子 | `@filter.on_llm_request()` → `call_event_hook(event, OnLLMRequestEvent, req)`，handler 收 `(event, req)` | 钩子签名 |
| **persona 读取** | **`get_default_persona_v3(umo)` 是 async**，返回 dict 形态 `Personality`，字段为 **`prompt`**（`astrbot/core/persona_mgr.py`、`db/po.py`） | 必须 `await`，且做了 prompt/system_prompt 双字段兼容 |
| 插件实例化 | `star_cls_type(context=..., config=...)`，TypeError 时回退 `(context=...)` | `__init__(self, context, config=None)` 双兼容 |
| 插件加载 | 以 `data.plugins.<目录名>.main` 整包 `__import__` | 相对导入可用（另留绝对导入兜底） |
| 命令参数 | `CommandFilter` 只绑定 handler 声明的参数，多余 token 忽略；`message_str` 已去 `/` 前缀 | handler 只声明 `(self, event)`，子命令手工解析 |

差异提示：总纲写“persona 的 system_prompt”，v4 源码实际字段名是 `prompt`。实现按 `prompt` → `system_prompt` 顺序兼容取值，两版均可用。

## 4. 关键设计决策（任务书歧义的裁决，请凛重点核验）

1. **system 条目的去向**：按任务书步骤 4，“第一条（或多条）role=system 的消息 → req.system_prompt = 拼接”。实现为：**所有** role=system 条目按 order 升序以空行（`\n\n`）连接写入 `system_prompt`；其余消息写入 `contexts`。条目在 order 轴上的相对位置仍完全由用户控制。
2. **contexts 完全替换**：即使条目里没有非 system 条目，`req.contexts` 也会被替换为空列表（原生历史已丢弃——这正是“完全接管”语义；想保留历史请放 chat_history 条目）。集成测试覆盖。
3. **热生效的实现**：条目每次组装时从 store 读取；`enable` 与 `variables` 每次钩子/命令时动态读 config；时间类变量每次请求重算。改 presets.json 后无需重启（下一次请求即生效），手改文件后也可 `/preset reload` 强制重读。
4. **presets.json 与 WebUI 配置的关系**：插件首次初始化（presets.json 不存在）时把 `_conf_schema.json` 的默认 entries 灌入 presets.json；**此后 presets.json 是唯一事实源**，WebUI 改 entries 不会回灌。这是“配置有 entries 字段 + 任务书要求 JSON 文件存储”两个要求的调和，命令测试覆盖“重载后不回灌”。
5. **条目 id**：store 为每条目生成 8 位 hex 管理用 id（任务书模型之外的字段，不发给 LLM），`remove/update` 支持按 id 或 name 定位，重名被拒绝。
6. **命令解析**：`/preset` 为单命令 + 子命令手工解析（兼容 `/preset ...` 与 `preset ...`）；add 的 content 为剩余全文（可含空格）；**条目名不能含空格**（命令帮助中注明）。`add` 只产生 source=text 条目（任务书命令规格如此）；persona/chat_history 条目通过编辑 presets.json + `/preset reload` 配置。`/preset status` 作为 `/living_status` 的别名同时支持（总纲与任务书命令表不一致，两者都实现）。
7. **role/source 校验**：store 层白名单校验（role: system/user/assistant，source: text/persona/chat_history），命令层给出友好错误；JSON 里的非法条目加载时跳过并告警，不影响其余条目。
8. **异常回退**：钩子内任何异常（如 persona 读取失败、手改 JSON 导致的脏数据）只记日志、不阻断请求；若异常发生在重建阶段，req 未被改动，保持 AstrBot 原生组装。persona 拿不到时按空 persona 继续组装（persona 条目展开为空串）。测试覆盖。
9. **保存原子性**：presets.json 写盘走临时文件 + `os.replace`；损坏文件加载失败时备份为 `.bak` 并从空列表开始（测试覆盖）。

## 5. 在 AstrBot venv 外跑测试的说明

`tests/conftest.py` 在 import astrbot 失败时（如本沙箱）注入最小化的 astrbot 桩（仅含 main.py 用到的 `Star/register/filter/AstrMessageEvent/ProviderRequest/logger` 名字），并给仓库根挂包别名 `astrbot_plugin_prompt_preset`；**在 VM 的 AstrBot venv 内运行时自动使用真实 astrbot，桩不生效**。因此同一套测试可在两处运行，且测试本身不依赖桩的行为（全部通过插件公开接口驱动）。

## 6. 红线自查

| 红线 | 自查 |
|---|---|
| 不修改 AstrBot 本体、不修改 LivingMemory | ✅ 纯插件，零外改；不 import LivingMemory 任何符号 |
| 不硬编码“推荐条目/预设模板” | ✅ 唯一内置条目是任务书 `_conf_schema.json` 自带的两个空 content 脚手架条目 |
| 不做 WebUI 面板 | ✅ 未做 |
| 不做 ST 预设导入 | ✅ 未做（M2） |
| 条目列表为空或全 disabled 不做任何操作 | ✅ 钩子早退 + assembler 双保险，测试覆盖（含“原生 req 逐字段不变”断言） |
| 不引入新依赖 | ✅ core 纯标准库；main.py 仅 astrbot API；pytest 仅测试期使用 |

## 7. 与 LivingMemory 的兼容性（按任务书 §兼容性说明）

M1 按“不依赖钩子顺序”策略实现：钩子里拿到的 `req.contexts` 已含 LivingMemory 的 fake messages，chat_history 条目展开时原样携带（集成测试里构造了伪工具调用消息对验证）。未做 `LivingMemoryBackend.probe()` 主动探测（任务书明确 M1 不做）。

## 8. 已知限制 / 移交 M2+ 的备注

- `/preset add` 不能直接创建 persona/chat_history 条目、条目名不支持空格（JSON 编辑 + reload 兜底）。
- 多条 system 条目拼接用 `\n\n` 连接，无自定义分隔符配置。
- WebUI 修改 `_conf_schema` 的 entries 后不会同步 presets.json（决策 §4.4）。
- `{{...}}` 变量为单遍替换，变量值里再含 `{{...}}` 不会递归展开。

## 9. 安装与验收指引（VM）

1. 将仓库内容拷贝到 AstrBot 的 `data/plugins/astrbot_plugin_prompt_preset/`（`.git`、`__pycache__` 可不带）。
2. 重启 AstrBot 一次（首次安装需要；之后改配置/条目均热生效）。
3. 验收路径：`/preset list`（应见默认“人格/自定义提示词”两条空脚手架）→ `/preset add 5 system 思考框架 回复前先思考` → `/living_status` 看预览 → 发一条消息验证 persona/历史/自定义条目的实际组装 → `/preset off 思考框架` → 再发消息验证开关即时生效。
4. 测试：在插件目录内 `python -m pytest tests/ -q`（AstrBot venv 或任意含 pytest 的 3.10+ 环境）。
