/* astrbot_plugin_prompt_preset —— 提示词编排面板逻辑
 * 运行在 AstrBot Plugin Pages 受限 iframe 中，通过 window.AstrBotPluginPage
 * bridge 调用后端（自动携带 dashboard 鉴权，页面内不接触任何 token）。
 * bridge 仅提供 GET/POST，因此更新/删除/重排序走后端的 POST 别名路由。 */

const bridge = await waitBridge();

const $ = (sel) => document.querySelector(sel);
const listEl = $("#entry-list");
const editorEl = $("#editor");

const state = {
  entries: [],
  selectedId: null,
  isNew: false, // 编辑器处于"新建"模式
};

/* ---------------- bridge 引导 ---------------- */

async function waitBridge(timeoutMs = 8000) {
  const start = Date.now();
  while (!window.AstrBotPluginPage) {
    if (Date.now() - start > timeoutMs) {
      document.body.textContent = "加载失败：未找到 AstrBot Pages bridge SDK。";
      throw new Error("bridge SDK not found");
    }
    await new Promise((r) => setTimeout(r, 50));
  }
  await window.AstrBotPluginPage.ready();
  return window.AstrBotPluginPage;
}

/* ---------------- 基础工具 ---------------- */

function toast(message, isError = false) {
  const el = $("#toast");
  el.textContent = message;
  el.classList.toggle("error", isError);
  el.classList.remove("hidden");
  clearTimeout(toast._timer);
  toast._timer = setTimeout(() => el.classList.add("hidden"), 2600);
}

function setStatus(text, extra = "") {
  $("#status-text").textContent = text;
  $("#status-extra").textContent = extra;
}

async function api(fn, okMessage) {
  try {
    const result = await fn();
    if (okMessage) {
      toast(okMessage);
      setStatus(okMessage);
    }
    return result;
  } catch (e) {
    const message = e && e.message ? e.message : String(e);
    toast(message, true);
    setStatus(`出错：${message}`);
    throw e;
  }
}

/* ---------------- 数据加载 ---------------- */

async function loadEntries({ keepSelection = true } = {}) {
  const data = await api(() => bridge.apiGet("entries"));
  state.entries = data.entries || [];
  if (!keepSelection || !state.entries.some((e) => e.id === state.selectedId)) {
    state.selectedId = null;
    state.isNew = false;
  }
  renderList();
  renderEditor();
}

/* ---------------- 左侧列表 ---------------- */

function tagEl(className, text) {
  const span = document.createElement("span");
  span.className = className;
  span.textContent = text;
  return span;
}

function renderList() {
  listEl.textContent = "";
  $("#list-empty").classList.toggle("hidden", state.entries.length > 0);
  $("#entry-count").textContent =
    `${state.entries.filter((e) => e.enabled).length}/${state.entries.length} 条启用`;

  for (const entry of state.entries) {
    const li = document.createElement("li");
    li.className = "entry-item";
    li.dataset.id = entry.id;
    li.draggable = true;
    if (entry.id === state.selectedId) li.classList.add("selected");
    if (!entry.enabled) li.classList.add("disabled-entry");

    const handle = tagEl("span drag-handle", "☰");
    const name = tagEl("span entry-name", entry.name);
    const role = tagEl(`tag tag-role-${entry.role}`, entry.role);
    const source = tagEl("tag tag-source", entry.source);
    const order = tagEl("span entry-order", String(entry.order));

    const toggle = document.createElement("input");
    toggle.type = "checkbox";
    toggle.className = "switch";
    toggle.checked = !!entry.enabled;
    toggle.title = entry.enabled ? "点击禁用" : "点击启用";
    toggle.addEventListener("change", () => toggleEntry(entry, toggle));
    toggle.addEventListener("click", (e) => e.stopPropagation());

    li.append(handle, toggle, name, role, source, order);
    li.addEventListener("click", () => selectEntry(entry.id));
    bindDrag(li);
    listEl.appendChild(li);
  }
}

async function toggleEntry(entry, toggle) {
  const target = !entry.enabled;
  try {
    await api(() => bridge.apiPost(`entries/${entry.id}`, { enabled: target }));
    entry.enabled = target;
    renderList();
    if (entry.id === state.selectedId && !state.isNew) {
      $("#f-enabled").checked = target;
    }
    setStatus(`已${target ? "启用" : "禁用"}「${entry.name}」`);
  } catch {
    toggle.checked = !target; // 失败回滚
  }
}

/* ---------------- 拖拽排序（HTML5 DnD，拖完等间距重编号） ---------------- */

function bindDrag(li) {
  li.addEventListener("dragstart", (e) => {
    e.dataTransfer.effectAllowed = "move";
    e.dataTransfer.setData("text/plain", li.dataset.id);
    li.classList.add("dragging");
  });
  li.addEventListener("dragend", () => {
    li.classList.remove("dragging");
    clearDropMarks();
    commitDomOrder();
  });
  li.addEventListener("dragover", (e) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
    const dragging = listEl.querySelector(".dragging");
    if (!dragging || dragging === li) return;
    clearDropMarks();
    const rect = li.getBoundingClientRect();
    const before = e.clientY < rect.top + rect.height / 2;
    li.classList.add(before ? "drop-before" : "drop-after");
    listEl.insertBefore(dragging, before ? li : li.nextSibling);
  });
}

function clearDropMarks() {
  listEl.querySelectorAll(".drop-before, .drop-after").forEach((el) =>
    el.classList.remove("drop-before", "drop-after")
  );
}

async function commitDomOrder() {
  const ids = [...listEl.querySelectorAll(".entry-item")].map((el) => el.dataset.id);
  if (ids.length < 2) return;
  if (ids.join(",") === state.entries.map((e) => e.id).join(",")) return;
  try {
    const data = await api(() => bridge.apiPost("entries/reorder", { ids }), "顺序已更新");
    state.entries = data.entries || [];
    renderList();
    renderEditor(); // order 数字同步刷新
  } catch {
    setStatus("重排序失败，已还原");
    await loadEntries();
  }
}

/* ---------------- 右侧编辑器 ---------------- */

const SOURCE_HINTS = {
  persona: "source=persona：组装时自动展开为「当前人格全文」，content 字段不参与组装。",
  chat_history:
    "source=chat_history：组装时在此位置展开完整对话历史（含 LivingMemory 记忆消息），content 字段不参与组装。",
};

function renderEditor() {
  const entry = state.entries.find((e) => e.id === state.selectedId);
  // classList.toggle 的 force 参数传 undefined 时等于"翻转"而非 false，必须显式转布尔
  const hasTarget = Boolean(state.isNew || entry);
  editorEl.classList.toggle("hidden", !hasTarget);
  $("#editor-empty").classList.toggle("hidden", hasTarget);
  if (!hasTarget) return;

  const source = state.isNew ? "text" : entry.source;
  $("#f-name").value = state.isNew ? "" : entry.name;
  $("#f-role").value = state.isNew ? "system" : entry.role;
  $("#f-source").value = source;
  $("#f-order").value = state.isNew
    ? String(nextOrder())
    : String(entry.order);
  $("#f-enabled").checked = state.isNew ? true : !!entry.enabled;
  $("#f-content").value = state.isNew ? "" : entry.content || "";
  $("#f-id").textContent = state.isNew ? "新条目（保存后生成 id）" : `id: ${entry.id}`;
  $("#btn-delete").textContent = state.isNew ? "✕ 取消" : "🗑 删除";
  $("#editor-note").textContent = "";
  applySourceUI(source);
}

function nextOrder() {
  const max = state.entries.reduce((m, e) => Math.max(m, Number(e.order) || 0), 0);
  return Math.round((max + 10) * 100) / 100;
}

function applySourceUI(source) {
  const hint = SOURCE_HINTS[source];
  $("#source-hint").textContent = hint || "";
  $("#source-hint").classList.toggle("hidden", !hint);
  const contentEl = $("#f-content");
  if (source === "text") {
    contentEl.removeAttribute("readonly");
  } else {
    contentEl.setAttribute("readonly", "readonly");
  }
}

function selectEntry(id) {
  state.selectedId = id;
  state.isNew = false;
  renderList();
  renderEditor();
}

function startNewEntry() {
  state.isNew = true;
  state.selectedId = null;
  renderList();
  renderEditor();
  $("#f-name").focus();
}

function collectEditor() {
  const name = $("#f-name").value.trim();
  if (!name) {
    toast("条目名不能为空", true);
    return null;
  }
  return {
    name,
    role: $("#f-role").value,
    source: $("#f-source").value,
    order: $("#f-order").value === "" ? undefined : Number($("#f-order").value),
    enabled: $("#f-enabled").checked,
    content: $("#f-content").value,
  };
}

async function saveEditor(event) {
  event.preventDefault();
  const payload = collectEditor();
  if (!payload) return;
  if (payload.order === undefined) delete payload.order;
  if (state.isNew) {
    const data = await api(() => bridge.apiPost("entries", payload), `已添加「${payload.name}」`);
    state.isNew = false;
    state.selectedId = data.entry.id;
  } else {
    await api(
      () => bridge.apiPost(`entries/${state.selectedId}`, payload),
      `已保存「${payload.name}」`
    );
  }
  await loadEntries();
  if (state.selectedId) selectEntry(state.selectedId);
}

async function deleteOrCancel() {
  if (state.isNew) {
    state.isNew = false;
    renderEditor();
    return;
  }
  const entry = state.entries.find((e) => e.id === state.selectedId);
  if (!entry) return;
  if (!window.confirm(`确认删除条目「${entry.name}」？`)) return;
  await api(() => bridge.apiPost(`entries/${entry.id}/delete`), `已删除「${entry.name}」`);
  state.selectedId = null;
  await loadEntries();
}

/* ---------------- 弹窗（导入 / 导出 / 变量） ---------------- */

function openModal(title, buildBody, onOk, okLabel = "确认") {
  $("#modal-title").textContent = title;
  const body = $("#modal-body");
  const extra = $("#modal-extra");
  body.textContent = "";
  extra.textContent = "";
  const cleanup = buildBody(body, extra) || (() => {});
  $("#modal-ok").textContent = okLabel;
  $("#modal-mask").classList.remove("hidden");
  $("#modal-ok").onclick = async () => {
    try {
      const keepOpen = await onOk();
      if (!keepOpen) closeModal();
    } catch {
      /* onOk 内部已 toast，保持弹窗便于修改 */
    }
  };
  $("#modal-cancel").onclick = () => {
    cleanup();
    closeModal();
  };
}

function closeModal() {
  $("#modal-mask").classList.add("hidden");
}

function openImportModal() {
  openModal(
    "📥 导入 JSON（数组，每项一个条目）",
    (body) => {
      const ta = document.createElement("textarea");
      ta.placeholder =
        '[\n  {"order": 0, "role": "system", "source": "persona", "content": "", "enabled": true, "name": "人格"},\n  {"order": 10, "role": "system", "source": "text", "content": "…", "enabled": true, "name": "自定义提示词"}\n]';
      body.appendChild(ta);
      return () => {};
    },
    async () => {
      let parsed;
      try {
        parsed = JSON.parse($("#modal-body textarea").value);
      } catch (e) {
        toast(`JSON 解析失败：${e.message}`, true);
        return true;
      }
      if (!Array.isArray(parsed)) {
        toast("需要 JSON 数组（[...]）", true);
        return true;
      }
      let ok = 0;
      const errors = [];
      for (const item of parsed) {
        try {
          await bridge.apiPost("entries", item);
          ok += 1;
        } catch (e) {
          errors.push(`${item && item.name ? item.name : "?"}: ${e.message}`);
        }
      }
      await loadEntries();
      if (errors.length) {
        toast(`导入完成：成功 ${ok} 条，失败 ${errors.length} 条（第一条：${errors[0]}）`, true);
        return true;
      }
      toast(`导入完成：共 ${ok} 条`);
      setStatus(`导入完成：共 ${ok} 条`);
    }
  );
}

function openExportModal() {
  openModal(
    "📤 导出 JSON（当前全部条目，按 order 升序）",
    (body, extra) => {
      const ta = document.createElement("textarea");
      ta.readOnly = true;
      ta.value = JSON.stringify(state.entries, null, 2);
      body.appendChild(ta);
      const copy = document.createElement("button");
      copy.className = "btn";
      copy.type = "button";
      copy.textContent = "📋 复制到剪贴板";
      copy.onclick = async () => {
        try {
          await navigator.clipboard.writeText(ta.value);
          toast("已复制");
        } catch {
          ta.select();
          document.execCommand("copy");
          toast("已复制（execCommand）");
        }
      };
      const download = document.createElement("button");
      download.className = "btn";
      download.type = "button";
      download.textContent = "⬇ 下载 presets.json";
      download.onclick = () => {
        const blob = new Blob([ta.value], { type: "application/json" });
        const a = document.createElement("a");
        a.href = URL.createObjectURL(blob);
        a.download = "presets.json";
        a.click();
        URL.revokeObjectURL(a.href);
      };
      extra.append(copy, download);
    },
    async () => closeModal(),
    "关闭"
  );
}

function openVariablesModal() {
  openModal(
    "🔀 自定义变量（content 中的 {{key}} 会被替换）",
    (body, extra) => {
      const rows = [];
      const container = document.createElement("div");
      body.appendChild(container);

      function addRow(key = "", value = "") {
        const row = document.createElement("div");
        row.className = "var-row";
        const keyInput = document.createElement("input");
        keyInput.type = "text";
        keyInput.placeholder = "变量名（如 user_name）";
        keyInput.value = key;
        const valueInput = document.createElement("input");
        valueInput.type = "text";
        valueInput.placeholder = "值";
        valueInput.value = value;
        const del = document.createElement("button");
        del.className = "btn danger";
        del.type = "button";
        del.textContent = "✕";
        del.onclick = () => row.remove();
        row.append(keyInput, valueInput, del);
        container.appendChild(row);
        rows.push(row);
      }

      bridge.apiGet("variables").then((data) => {
        Object.entries(data.variables || {}).forEach(([k, v]) => addRow(k, String(v)));
        if (!rows.length) addRow();
      });
      const add = document.createElement("button");
      add.className = "btn";
      add.type = "button";
      add.textContent = "➕ 添加变量";
      add.onclick = () => addRow();
      extra.appendChild(add);
    },
    async () => {
      const variables = {};
      for (const row of $("#modal-body").querySelectorAll(".var-row")) {
        const [keyInput, valueInput] = row.querySelectorAll("input");
        const key = keyInput.value.trim();
        if (!key) continue;
        variables[key] = valueInput.value;
      }
      const data = await api(() => bridge.apiPost("variables", { variables }), "变量已保存");
      setStatus(`变量已保存（${Object.keys(data.variables).length} 个）`);
    }
  );
}

/* ---------------- 组装预览 ---------------- */

async function togglePreview() {
  const drawer = $("#preview-drawer");
  if (!drawer.classList.contains("hidden")) {
    drawer.classList.add("hidden");
    return;
  }
  const data = await api(() => bridge.apiGet("preview"));
  const rows = $("#preview-rows");
  rows.textContent = "";
  for (const [index, row] of (data.rows || []).entries()) {
    const li = document.createElement("li");
    const idx = tagEl("span preview-idx", `${index + 1}.`);
    const meta = tagEl(
      "span preview-meta",
      `order=${row.order}  [${row.role}/${row.source}] ${row.name}（${row.length}字）`
    );
    const snippet = tagEl("span preview-snippet", row.snippet || "");
    li.append(idx, meta, snippet);
    rows.appendChild(li);
  }
  if (!data.count) {
    const li = document.createElement("li");
    li.textContent = "当前没有启用的条目：插件未接管组装（AstrBot 原生行为）。";
    rows.appendChild(li);
  }
  setStatus(`组装预览：${data.count} 条启用条目，persona ${data.persona_length} 字`);
  drawer.classList.remove("hidden");
}

/* ---------------- 事件绑定与启动 ---------------- */

$("#btn-add").addEventListener("click", startNewEntry);
$("#btn-import").addEventListener("click", openImportModal);
$("#btn-export").addEventListener("click", openExportModal);
$("#btn-variables").addEventListener("click", openVariablesModal);
$("#btn-preview").addEventListener("click", togglePreview);
$("#preview-close").addEventListener("click", () => $("#preview-drawer").classList.add("hidden"));
editorEl.addEventListener("submit", saveEditor);
$("#btn-delete").addEventListener("click", deleteOrCancel);
$("#f-source").addEventListener("change", (e) => applySourceUI(e.target.value));

await loadEntries({ keepSelection: false });
setStatus("就绪", "改动即时写入 presets.json，下一次 LLM 请求生效");
