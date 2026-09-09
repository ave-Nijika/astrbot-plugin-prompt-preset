# astrbot_plugin_prompt_preset

AstrBot prompt entry orchestrator — add, reorder, toggle, and fully control every prompt sent to the LLM, just like SillyTavern presets.

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![AstrBot](https://img.shields.io/badge/AstrBot-v4.27.5+-orange.svg)](https://github.com/AstrBotDevs/AstrBot)

## What is this

By default, AstrBot puts the persona into system_prompt and arranges chat history chronologically — you have no control over the order. This plugin lets you do what SillyTavern presets do:

- Turn persona, world-building, thinking frameworks, jailbreak entries into independent "entries"
- Set each entry's sort weight (order), role (system/user/assistant), and enable/disable toggle
- Reference AstrBot's built-in system prompts via `{{native_system}}` variable
- Reference LivingMemory recalled memories via `{{memories}}` variable
- Drag to reorder, toggle on/off, edit content — all in a WebUI panel

## Features

### Entry orchestration

- Per-entry: sort weight (order), role, content, enable/disable toggle
- Float order values allow inserting between any two entries
- Three sources: text (custom text), persona (persona full text), chat_history (conversation history)
- Variable replacement: `{{persona}}`, `{{native_system}}`, `{{memories}}`, `{{user_name}}`, `{{bot_name}}`, `{{time}}`, `{{date}}`

### WebUI panel

Plugin detail page → Pages → preset:
- Entry list sorted by order, drag to reorder (auto-renumbers 0/10/20/…)
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
- AstrBot's native system_prompt is replaced when plugin is active — use `{{native_system}}` entry to retain it
- `/preset add` only supports source=text entries; persona/chat_history entries via WebUI panel or presets.json

## License

[MIT](LICENSE)