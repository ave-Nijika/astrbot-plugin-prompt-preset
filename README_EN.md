# astrbot_plugin_prompt_preset

AstrBot prompt entry orchestrator — add, reorder, toggle, and fully control every prompt sent to the LLM, just like SillyTavern presets.

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![AstrBot](https://img.shields.io/badge/AstrBot-v4.27.5+-orange.svg)](https://github.com/AstrBotDevs/AstrBot)

## What is this

By default, AstrBot puts the persona into system_prompt and arranges chat history chronologically — you have no control over the order. This plugin lets you do what SillyTavern presets do:

- Turn persona, world-building, thinking frameworks, jailbreak entries into independent "entries"
- Set each entry's sort weight (order), role (system/user/assistant), and enable/disable toggle
- Reference AstrBot's built-in system prompts via `{{native_system}}`, or block-by-block via 12 split variables (`{{native_safety}}`, `{{native_persona}}`, `{{native_tools}}`, …)
- Reference LivingMemory recalled memories via `{{memories}}` variable
- Drag to reorder, toggle on/off, edit content — all in a WebUI panel

## Preset entries

### Motivation

Once enabled, this plugin **fully takes over** prompt assembly: AstrBot's original system_prompt and chat history are no longer sent directly — the entry list rebuilds them. So that users unfamiliar with the mechanism get "install and forget" behavior, the plugin automatically seeds 13 preset entries (marked `原生-*`, with a lock icon in the panel) on first startup. These split AstrBot's native prompts into independent blocks **in their real execution order** (safe mode, persona, skills, tool instructions, …) plus one chat-history entry. The messages sent to the LLM are semantically identical before and after enabling the plugin — no action required. When you want to customize, reorder or rewrite blocks one by one.

### The 13 preset entries

The order below reflects the real injection order verified from AstrBot source (the safety block is prepended to the front at runtime; the web-search citation block is injected last):

| Entry | Variable | Description | Non-empty when | Common tweaks |
|---|---|---|---|---|
| 原生-安全模式 | `{{native_safety}}` | Safe-mode rules injected by AstrBot's "healthy mode" | Healthy mode enabled in WebUI | Disable healthy mode and this entry becomes empty automatically |
| 原生-ChatUI生成 | `{{native_genui}}` | ChatUI inline HTML generation (GenUI) hint | Message event carries `enable_inline_genui` (off by default) | Disable if you don't use ChatUI page rendering |
| 原生-人格说明 | `{{native_persona}}` | `# Persona Instructions` header + full persona text | A persona is configured and selected | To place custom text right after the persona, create an entry with order between 120-140 |
| 原生-默认人格 | `{{native_default_persona}}` | Webchat-only default persona ("calm, patient friend") | Webchat session without a selected persona and default prompt enabled | Keep as-is |
| 原生-技能说明 | `{{native_skills}}` | Skill inventory and usage rules | There are active skills | Disable to de-emphasize skills (skills stay registered) |
| 原生-路由提示 | `{{native_router}}` | Sub-agent orchestrator routing prompt (user-configured text) | Currently always empty (no stable marker; content falls into 原生-其他插件注入) | Reserved variable |
| 原生-沙箱说明 | `{{native_sandbox}}` | Sandbox runtime (shell/Python execution) note | Computer-use runtime = sandbox | Mutually exclusive with 原生-本地模式 |
| 原生-本地模式 | `{{native_local_mode}}` | Local runtime note (OS & shell hints) | Computer-use runtime = local | Mutually exclusive with 原生-沙箱说明 |
| 原生-工具说明 | `{{native_tools}}` | Tool-call behavior hint (two texts for the two tool schema modes) | Request has usable tools | Disabling keeps tools callable, minus the behavior hint |
| 原生-Live模式 | `{{native_live}}` | Real-time (live call) conversation hint | During live sessions | Empty otherwise |
| 原生-搜索引用 | `{{native_websearch}}` | Web-search citation format (`<ref>` tagging) hint | Web-search tools enabled | Rewrite this entry for looser citation style |
| 原生-其他插件注入 | `{{native_other}}` | Fallback block: unmatched injected content (other plugins' system_prompt appends, text before the first known block) | When unrecognized injections exist | Keep last so unknown content is never lost |
| 对话历史 | (source=chat_history) | Expands the full chat history (including LivingMemory memory messages) | Always (expands 0 messages when history is empty) | Move history earlier/later by changing order |

### Protection rules

- Preset entries **cannot be deleted** (greyed-out delete button in the panel; chat commands and the REST API refuse as well) — the error reads "预置条目不可删除，如不需要请禁用该条目" (preset entries cannot be deleted; disable them instead);
- **Allowed**: edit content, enable/disable toggle, drag to reorder;
- Empty entries are skipped automatically: when a variable has no content (e.g. healthy mode off), the corresponding entry produces **no message** — no manual cleanup needed;
- Deleting preset entries by hand-editing `presets.json` is unprotected and **will not be re-seeded** (seeding happens exactly once; once the `initialized.flag` marker file is written it never runs again).

### Restoring defaults

Each preset entry's default content is exactly its variable reference (see table above). To undo edits, set the content back to that single variable reference.

### Variable reference

| Variable | Expands to |
|---|---|
| `{{native_system}}` | The full native system_prompt snapshot (all built-in blocks plus other plugins' injections) |
| `{{native_safety}}` / `{{native_genui}}` / `{{native_persona}}` / `{{native_default_persona}}` / `{{native_skills}}` / `{{native_router}}` / `{{native_sandbox}}` / `{{native_local_mode}}` / `{{native_tools}}` / `{{native_live}}` / `{{native_websearch}}` / `{{native_other}}` | Individual built-in blocks split by markers (see table above) |
| `{{memories}}` | LivingMemory recalled memories (advanced use: not preset by default to avoid duplicate injection) |
| `{{persona}}` | Full current persona text |
| `{{user_name}}` / `{{bot_name}}` | Custom variables from config (default 主人/凛) |
| `{{time}}` / `{{date}}` / `{{datetime}}` | Current time HH:MM / date YYYY-MM-DD / date+time |

> `native_` is a **reserved variable prefix**: custom variables named `native_*` in the config are ignored with a warning log. Unknown variables are kept verbatim.

## Features

### Entry orchestration

- Per-entry: sort weight (order), role, content, enable/disable toggle
- Float order values allow inserting between any two entries
- Three sources: text (custom text), persona (persona full text), chat_history (conversation history)
- Variable replacement: `{{persona}}`, `{{native_system}}`, `{{memories}}`, `{{user_name}}`, `{{bot_name}}`, `{{time}}`, `{{date}}`

### WebUI panel

Plugin detail page → Pages → preset:
- Entry list sorted by order, drag to reorder (auto-renumbers 0/10/20/…); preset entries show a 🔒 原生 badge with greyed-out delete button
- Per-entry toggle (green=enabled, gray=disabled)
- Right panel editor: name / role dropdown / source dropdown / order input / content textarea
- Toolbar: add / import JSON / export JSON / variables / assembly preview
- Dark theme, follows dashboard

### Assembly preview

Real-time preview of the final message sequence under current entry configuration.

### Chat commands

`/preset list|show|add|del|move|on|off|reload|status`

## Installation

Same as any AstrBot plugin. Requires AstrBot v4.27.5+.

## Known limitations

- Empty or all-disabled entry list = no operation (AstrBot native behavior preserved)
- Native prompts are preserved automatically by the preset entries (referenced block by block); deleting or disabling a preset entry gives up that block's content
- Splitting relies on marker texts from AstrBot source; if a future AstrBot version rewrites its built-in prompts, unmatched content falls into `{{native_other}}` (nothing is lost, only block attribution changes)
- `/preset add` only supports source=text entries; persona/chat_history entries via WebUI panel or presets.json

## License

[MIT](LICENSE)