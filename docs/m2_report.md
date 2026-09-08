# M2 交付报告：WebUI 条目编排面板

**日期**：2026-09-09
**执行者**：zcode
**任务书**：`docs/task_m2_WebUI面板.md`（目标 AstrBot v4.28.0-beta.1）
**状态**：已完成，待凛核验 + 主人 VM 实测

---

## 1. 开工调研结论（需求 C，汇报节点 1）

按任务书要求先调研后写码。结论：**AstrBot ≥ 4.24.2 有官方"插件 Pages"机制**（来源：官方文档 `docs.astrbot.app/dev/star/guides/plugin-pages.html`，2026-07 更新；LivingMemory 的 README 也声明其面板依赖 4.24.2+。VM 的 v4.28.0-beta.1 满足）。任务书需求 C 的三个问题，官方答案如下：

| 问题 | 调研结论 |
|---|---|
| 静态文件放哪 | 插件目录下 **`pages/<page_name>/`**，一级子目录即一个 Page，必须含 `index.html`。dashboard 自动扫描并以**受限 iframe** 加载，无需自己挂静态路由 |
| 路由怎么注册 | 后端 REST API 用 **`context.register_web_api(route, handler, methods, desc)`**（plugin `__init__` 时调用）；**route 必须带插件名前缀**（如 `/astrbot_plugin_prompt_preset/entries`），支持 `<name>`（单段）与 `<path:name>`（多段）动态段；handler 的路径参数按关键字传入。页面本体不需要任何路由注册 |
| 鉴权怎么处理 | `register_web_api` 注册的路由位于 dashboard 的鉴权保护之下（dashboard 对 `/api/*` 统一 JWT 中间件）。**Pages 页面跑在受限 iframe 里，拿不到 dashboard 的 localStorage**；前端通过自动注入的 **`window.AstrBotPluginPage` bridge SDK**（`bridge.ready()` / `bridge.apiGet()` / `bridge.apiPost()`）调用后端，鉴权由 bridge 自动携带 |

调研过程还核实了：bridge 的返回值约定（`{"status":"ok","data":...}` 在前端 resolve 为 `data`；`error_response` 会让前端 Promise reject）；主题由服务端预注入 `<html data-theme>` 且 bridge 持续维护，页面只需按 `[data-theme="dark"]` 写 CSS 变量；静态资源用相对路径（`./app.js`），AstrBot 会带 asset_token 重写。

**对任务书的两处修正**（任务书假设 vs 官方机制，已按官方执行）：

1. 任务书 B 节"所有 API 调用用 fetch()，带 JWT token（从 localStorage 获取）"——在 Pages 沙箱里**不可行也无必要**（iframe 沙箱拿不到 localStorage），改为 bridge 调用。
2. 任务书 A 节"dashboard 是 FastAPI/Starlette"——v4.3.5 源码实为 Quart（本沙箱克隆核实）；无论哪个框架，`register_web_api` 都是官方插件入口，插件代码不直接触碰框架对象。

## 2. 交付物清单

```
├── dashboard_api.py            # API 核心层（框架无关，纯业务逻辑，可独立测试）
├── main.py                     # +适配层：register_web_api 路由注册、request 解析、错误转换
├── metadata.yaml               # desc → description（需求 E）；版本 v1.0.0 → v1.1.0
├── pages/preset/
│   ├── index.html              # 面板骨架（工具栏/左列表/右编辑器/预览抽屉/弹窗）
│   ├── style.css               # 深色主题（data-theme 变量）+ role 三色标签 + 开关样式
│   └── app.js                  # bridge 调用、列表渲染、HTML5 拖拽排序、编辑器、弹窗、预览
├── tests/test_dashboard_api.py # 需求 D：30 条新测试（核心层/适配层/HTTP 层）
└── docs/m2_report.md           # 本文件
```

M1 的 `core/`（assembler/entry_store/variables）**零改动**（红线自查见 §7）；`main.py` 仅增量（API 适配层 + 需求 E 的帮助文本）。

## 3. 后端 API（需求 A）

实际注册的路由（`register_web_api`，dashboard 侧完整路径为 `/api/v1/plugins/extensions/<route>`；bridge 前端调用时省略插件名前缀）：

| 任务书要求的端点 | 实际注册 route | methods | 说明 |
|---|---|---|---|
| GET `/api/prompt_preset/entries` | `/astrbot_plugin_prompt_preset/entries` | GET, POST | POST=新增条目 |
| POST `/api/prompt_preset/entries` | ↑ 同路由 | | |
| PUT `/api/prompt_preset/entries/{id}` | `/astrbot_plugin_prompt_preset/entries/<item_id>` | PUT, POST | **POST 是 bridge 别名**（bridge 无 PUT） |
| DELETE `/api/prompt_preset/entries/{id}` | ↑ 同路由 | DELETE | |
| PUT `/api/prompt_preset/entries/reorder` | `/astrbot_plugin_prompt_preset/entries/reorder` | PUT, POST | body `{"ids":[...]}`（兼容裸数组）；等间距重编号（步长 10）；要求 id 列表覆盖全部条目。静态段 `reorder` 先于动态段 `<item_id>` 注册，避免路由歧义 |
| GET `/api/prompt_preset/variables` | `/astrbot_plugin_prompt_preset/variables` | GET, PUT, POST | 变量存插件配置 `variables` 字段，PUT 后 `save_config()` 持久化（热生效） |
| PUT `/api/prompt_preset/variables` | ↑ 同路由 | | |
| GET `/api/prompt_preset/preview` | `/astrbot_plugin_prompt_preset/preview` | GET | 调 M1 `assembler.preview()`，与钩子组装同一套变量上下文（persona 实时读取） |

补充注册：`/entries/<item_id>/delete`（POST）——bridge 删除条目用。

**分层设计**：`dashboard_api.py` 的 `PromptPresetAPI` 是纯业务层（入参 Python 对象/出参 JSON dict，错误抛 `ApiError(status_code)`），完全不碰 request 对象；`main.py` 里的适配层每条路由只有"取 body → 调核心层 → `json_response`/`error_response`"三行逻辑。这保证了 API 逻辑可以脱离 AstrBot 全速测试，也守住了"M1 模块不动"的红线——底层全部复用 `EntryStore`。

## 4. 前端面板（需求 B，核心交付）

`pages/preset/`，纯原生 HTML+CSS+JS（无构建工具、无 CDN 依赖），符合任务书全部要点：

- **左侧条目列表（30%）**：按 order 升序；每条含拖拽把手、启用开关（绿=启用/灰=禁用，禁用条目划线置灰）、名称、role 彩色标签（system=蓝 / user=绿 / assistant=橙）、source 虚线标签、order 数值。
- **拖拽排序**：HTML5 Drag & Drop 原生实现（拖动实时插入定位 + 高亮落点线），松手后提交有序 id 列表给 `/entries/reorder`，后端等间距重编号（0/10/20/…），前端刷新同步 order 显示。
- **右侧编辑器（70%）**：名称 / role 下拉 / source 下拉 / order 数字框 / enabled 开关 / content 多行编辑；source=text 可编辑 content 并支持 `{{变量}}`（placeholder 提示）；source=persona/chat_history 时 content 置只读并显示说明条（这两个 source 的 content 不参与组装）。保存 / 删除按钮 + 条目 id 展示。
- **顶部工具栏**：➕新增 / 📥导入 JSON（弹窗粘贴数组逐条校验导入，失败逐条报告）/ 📤导出 JSON（弹窗展示 + 复制到剪贴板 + 下载 presets.json）/ 🔀自定义变量（弹窗增删改变量行，保存走 PUT variables）/ 👁组装预览。
- **底部**：组装预览抽屉（每条目最终位置：order / [role/source] / 名称 / 字数 / 50 字摘要，与请求时同一套引擎）；状态栏（操作结果 + "改动即时写入 presets.json"提示）；toast 提示。
- **视觉**：深色主题为默认（对齐主人提供的 ST 截图），CSS 变量 + `[data-theme="dark"]`，跟随 dashboard 明暗切换；未选择条目时编辑器区显示空态引导。
- **bridge 兼容**：SDK 显式 `<script>` 引入 + 运行时轮询兜底（防注入时序问题）；所有写操作走 POST 别名路由。

## 5. 测试结果（需求 D）

```
$ python -m pytest
139 passed
```

- **M1 的 109 条全部通过，零回归**（含组装/存储/变量/命令/集成）。
- 新增 30 条（`tests/test_dashboard_api.py`），超出任务书预估的 10-15 条，分三层：
  - **核心层 22 条**：entries CRUD（含 404/400/重名/缺省值/id 防篡改）、reorder（等间距重编号/裸数组与 dict 双格式/未知与重复与缺漏 id 校验/持久化）、variables（读写/setter 持久化/包装格式/非法输入/键名清洗）、preview（变量替换/persona 长度/空态）；
  - **适配层 4 条**：路由注册表（7 条路由、方法表、插件名前缀）、POST 分支创建、ApiError→error_response 转换、GET 分支；
  - **HTTP 层 4 条**：FastAPI TestClient 走真实 HTTP（与 main.py 注册表同构挂载）：CRUD 全流程、reorder+preview、错误形状（400/404）、variables。fastapi 为**测试环境依赖**（沙箱 pip 安装），插件运行时只用 AstrBot 自带的 `astrbot.api.web`，未引入任何新运行时依赖。
- **前端浏览器冒烟**（沙箱内可做的"实测"）：用浏览器 + mock bridge 真实渲染验证了初始化加载、条目选中、编辑器回填、新增→保存→列表刷新、变量弹窗、开关切换（计数徽章与状态栏同步）、**拖拽排序**（末位条目拖至首位，0/10/20/30 等间距重编号生效）、组装预览抽屉。截图 4 张：`docs/m2_截图_1_列表.png`、`m2_截图_2_编辑器.png`、`m2_截图_3_组装预览.png`、`m2_截图_4_变量弹窗.png`。
  - 冒烟抓出一个真实 bug 并已修复：未选中条目时 `classList.toggle(name, force)` 收到 `undefined` 会按"翻转"处理，导致空态提示被错误隐藏——已改为显式 `Boolean()` 并在浏览器回归确认。
- **VM 截图说明**：本沙箱无 AstrBot 运行环境，任务书要求的"启动 AstrBot 截 WebUI 面板"需在 VM 执行，步骤见 §8。上面 4 张为沙箱内等价冒烟截图（mock 了 bridge 的 API 语义），真实 dashboard 内的最终视觉请以 VM 实测为准（bridge 由 dashboard 注入，页面代码路径一致）。

## 6. 需求 E（M1 遗留）

- `/preset add` 帮助文本已注明"仅 source=text，persona/chat_history 条目请用 WebUI 面板或编辑 presets.json"（`USAGE` 常量）；`/preset` 帮助同时补充了面板入口指引。
- `metadata.yaml`：`desc` → `description`（v4 源码核实 `_load_plugin_metadata` 对两字段兼容），版本号升至 v1.1.0（`@register` 同步）。

## 7. 红线自查

| 红线 | 自查 |
|---|---|
| 不修改 AstrBot 本体 / LivingMemory | ✅ 纯插件目录内改动；只调官方公开 API（`register_web_api`、Pages 目录约定、bridge），未 fork 未 import LivingMemory |
| 不引入前端构建工具 | ✅ 三个纯静态文件，无 package.json/无打包 |
| 不引入新 Python 依赖 | ✅ 运行时仅 `astrbot.api.*` + 标准库；fastapi 仅测试环境 |
| 面板路由必须鉴权 | ✅ 全部走 `register_web_api`（dashboard JWT 中间件覆盖）；页面端经 bridge 自动携带鉴权，代码中无任何裸 token 处理 |
| M1 组装逻辑不变 | ✅ `core/assembler.py`、`core/entry_store.py`、`core/variables.py` 零 diff（git 可查）；M1 109 测试全绿佐证 |

## 8. VM 验收指引（主人实测）

1. 更新插件目录（`git pull` 或拷贝）后在 WebUI 重载插件。
2. WebUI → 插件管理 → astrbot_plugin_prompt_preset → 插件详情页 → **Pages → preset**，打开面板。
3. 建议走查：列表加载现有 presets.json 条目 → 点选条目编辑保存 → 拖拽换序后发一条消息验证顺序生效 → 开关某条目对比回复 → 新增 text 条目写 `{{user_name}}` 验证变量 → 导入/导出 JSON → 组装预览与 `/living_status` 输出对照 → 切换 dashboard 明暗主题看面板跟随。
4. API 抽查（浏览器已登录 dashboard 的会话里）：`GET /api/v1/plugins/extensions/astrbot_plugin_prompt_preset/entries` 应返回条目列表；未带 token 直接访问应 401。

## 9. 已知限制 / 备注

- 面板中文单语言（未做 `.astrbot-plugin/i18n` 多语言文件，Pages 的 i18n 为可选机制）。
- 拖拽排序提交的是**全量 id 列表**并整体等间距重编号——若用户在面板之外手工维护了精细 order 间隙，面板拖拽后会归整为 0/10/20（任务书即此设计）。
- bridge SDK 由 dashboard 注入，其 `apiGet/apiPost` 之外的方法（upload/download/SSE）本面板未使用。
- 编辑器无脏数据跟踪（切换条目即丢弃未保存修改）；ST 同款交互为显式保存，如需要可在 M3 加自动保存。
