# 任务书：astrbot_plugin_prompt_preset M2 —— WebUI 条目编排面板

**项目**：astrbot_plugin_prompt_preset（提示词条目编排插件）
**前情**：M1 已交付核验（109 测试全绿，组装引擎/条目存储/变量替换/聊天命令全部可用），已部署 VM（`_conf_schema.json` schema 已修复为 `type: list`，AstrBot v4.28.0-beta.1 加载成功）。
**工作位置**：`D:\sandbox\prompt-preset`
**目标**：仿照 SillyTavern 预设界面的排版，做一个内嵌在 AstrBot WebUI 里的管理面板——用户可以直观地添加/编辑/排序/开关提示词条目，替代当前 M1 的裸 JSON 编辑方式。
**参考实现**：`data/plugins/astrbot_plugin_livingmemory/`（它的 WebUI Pages 面板是最佳参考——左侧导航栏 + 主内容区的完整前端，已内嵌 AstrBot dashboard）
**交付**：WebUI 面板可用 + 后端 API + pytest 全绿 + `docs/m2_report.md`
**执行者**：zcode。交付后由凛核验 + 主人 VM 实测。

---

## ⚠️ 关键约束

1. 不改 AstrBot 本体、不改 LivingMemory。参考其实现方式但不复制代码（AGPL）。
2. M1 的 109 条测试不回归。M1 的核心模块（assembler/entry_store/variables）逻辑不变——M2 只加 WebUI 层。
3. 前端资源（HTML/CSS/JS）放在插件目录内，不引入前端构建工具（无 webpack/vite），纯原生 HTML+CSS+JS 单文件或少量文件。
4. 面板必须通过 AstrBot dashboard 鉴权才能访问（不能裸暴露）。
5. 热生效：面板上改动立即写入 presets.json，下一次 LLM 请求即生效（M1 已实现，M2 复用）。

---

## 需求 A：后端 API（插件注册 dashboard 路由）

AstrBot 的 dashboard 是 FastAPI/Starlette。插件需要注册以下 REST 端点（前缀 `/api/prompt_preset/`），参考 LivingMemory 的路由注册方式（调研其 dashboard 路由挂载点，照做但不复制代码）：

| 方法 | 路径 | 功能 |
|---|---|---|
| GET | `/api/prompt_preset/entries` | 返回全部条目列表（含 enabled/disabled） |
| POST | `/api/prompt_preset/entries` | 添加条目（body = 完整条目 JSON） |
| PUT | `/api/prompt_preset/entries/{id}` | 更新条目 |
| DELETE | `/api/prompt_preset/entries/{id}` | 删除条目 |
| PUT | `/api/prompt_preset/entries/reorder` | 批量重排序（body = 有序 id 列表，按新顺序重写 order） |
| GET | `/api/prompt_preset/variables` | 返回自定义变量 |
| PUT | `/api/prompt_preset/variables` | 更新自定义变量 |
| GET | `/api/prompt_preset/preview` | 返回当前组装结果预览（调 assembler.preview()） |

- 所有端点走 AstrBot dashboard 的 JWT 鉴权（同现有 API，不能裸暴露）。
- 底层调用 M1 的 `EntryStore`（已有 CRUD + JSON 持久化），不在 API 层重复实现。

## 需求 B：前端面板（核心交付）

### 布局（仿 SillyTavern 预设界面，主人提供了截图）

**左侧：条目列表（约 30% 宽）**
- 按当前 order 升序排列
- 每条显示：名称、role 标签（system/user/assistant 不同颜色）、source 标签、开关（启用/禁用）
- **拖拽排序**：拖动条目改变顺序，拖完自动按新顺序重写所有条目的 order（等间距重编号）
- 点击条目 → 右侧编辑面板显示详情

**右侧：条目编辑器（约 70% 宽）**
- 名称（文本框）
- role（下拉框：system / user / assistant）
- source（下拉框：text / persona / chat_history）
- order（数字输入框，也可由拖拽自动计算）
- content（多行文本编辑器，source=text 时可编辑；persona/chat_history 时显示说明文字）
- enabled 开关
- 保存 / 删除 按钮

**顶部工具栏**
- ➕ 添加新条目按钮
- 📥 导入 JSON（粘贴 JSON 数组批量导入）
- 📤 导出 JSON（导出当前条目列表）
- 变量编辑按钮（弹出自定义变量编辑面板）

**底部状态栏**
- 组装预览按钮：调 `/preview` API 显示当前组装结果（各条目的最终位置和内容摘要）

### 视觉风格

- 深色主题（主人截图里的 ST 是深色的，AstrBot dashboard 也有暗色模式）
- 启用条目的开关用亮色（绿色/橙色），禁用用灰色
- role 用不同颜色标签区分：system=蓝色、user=绿色、assistant=橙色
- 整体风格向 AstrBot dashboard 的暗色模式靠拢（和 LivingMemory 的面板风格一致）

### 技术实现

- 纯 HTML + CSS + 原生 JavaScript（或单文件 Vue CDN），**不用构建工具**
- 拖拽排序：HTML5 Drag & Drop API（原生，不需要库）
- 所有 API 调用用 fetch()，带 JWT token（从 AstrBot dashboard 的 localStorage 获取）
- 面板入口：通过 AstrBot dashboard 的插件面板机制注册（调研 LivingMemory 怎么注册 Pages 路由的，照做）

## 需求 C：面板注册到 AstrBot Dashboard

调研 LivingMemory 的 Pages 面板是怎么嵌入 AstrBot dashboard 的（可能是注册 dashboard 路由提供静态文件，或用 AstrBot 的插件面板机制）。照做但不复制代码。

需要确认的点（调研后写入报告）：
1. 静态文件放在插件目录的哪个子目录（如 `dist/` 或 `dashboard/`）
2. 路由怎么注册（插件初始化时往 dashboard app 挂 router？还是有专门的 Pages 注册接口？）
3. 鉴权怎么处理（dashboard 的 JWT 是否自动覆盖插件注册的路由？还是需要单独处理？）

## 需求 D：测试

- 后端 API：用 FastAPI TestClient（或等效）测试各端点的 CRUD / reorder / preview
- M1 的 109 条测试不回归
- 前端不做自动化测试（纯静态 JS），但需要 zcode 在 VM 上实测截图给主人
- 预计新增 10-15 条测试

## 需求 E：M1 遗留修复（顺手做）

- `/preset add` 命令目前不能创建 persona/chat_history 条目——M2 有 WebUI 后不是问题了，但命令帮助文本里注明
- `metadata.yaml` 的 `desc` 字段改成 `description`（AstrBot 兼容两者但 `description` 是标准字段名）

---

## ⚠️ 红线

- ❌ 不修改 AstrBot 本体 / LivingMemory。
- ❌ 不引入前端构建工具（webpack/vite/npm）。
- ❌ 不引入新 Python 依赖。
- ❌ 面板路由必须鉴权（不能裸暴露）。
- ❌ M1 的组装逻辑不变——M2 只加 WebUI 层，assembler/entry_store/variables 不动。

## 汇报节点

1. **开工前必须先调研** LivingMemory 的 Pages 注册机制和 dashboard 路由挂载点，**调研结论先报给凛再写代码**。
2. 交付附 `m2_report.md` + 测试结果 + **VM 上面板截图**（zcode 启动 AstrBot 后截 WebUI 的插件面板页面）。
3. 等凛核验 + 主人实测。