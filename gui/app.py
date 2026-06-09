"""Gradio GUI — thin frontend that delegates all logic to the Backend.

Handlers are lightweight direct method calls (no blocking work except
the pipeline triggers which run on ThreadPoolExecutor).
Polling timer auto-refreshes the queue UI every 1.5s.
All state lives in Backend (in-memory dict + RLock).
"""

from __future__ import annotations

import base64
import tempfile
from pathlib import Path

import gradio as gr

from backend.engine import Backend
from src.models import QueueItem, QueueStatus, Subject, QuestionType

# ── Clipboard paste JavaScript (injected into page <head>) ──────────────────

_PASTE_JS = """
<script>
(function() {
    // Shared: send base64 data to backend via hidden textbox JS bridge
    function sendToBackend(base64Data) {
        var el = document.querySelector('#paste_input textarea, #paste_input input');
        if (!el) return;
        var p = el.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
        Object.getOwnPropertyDescriptor(p, 'value').set.call(el, base64Data);
        el.dispatchEvent(new InputEvent('input', {bubbles: true, inputType: 'insertText'}));
    }

    // Ctrl+V: paste event (synchronously reads clipboardData — the only
    // reliable cross-browser method for pasting images from clipboard)
    document.addEventListener('paste', function(e) {
        var tag = (e.target.tagName || '').toUpperCase();
        if (tag === 'INPUT' || tag === 'TEXTAREA') return;
        if (!e.clipboardData || !e.clipboardData.items) return;
        for (var i = 0; i < e.clipboardData.items.length; i++) {
            if (e.clipboardData.items[i].type.startsWith('image/')) {
                e.preventDefault();
                var blob = e.clipboardData.items[i].getAsFile();
                var reader = new FileReader();
                reader.onload = function(ev) { sendToBackend(ev.target.result); };
                reader.readAsDataURL(blob);
                return;
            }
        }
    });
})();
</script>
"""

# ── Backend (direct, same-process, no HTTP) ────────────────────────────────────

_backend = Backend()
# Enable auto mode by default (user preference)
_backend.set_auto_ocr(True)
_backend.set_auto_llm(True)


# ── Render helpers (pure presentation, local to GUI) ───────────────────────────

STATUS_ICONS = {
    QueueStatus.IDLE: "⬜",
    QueueStatus.OCR_QUEUED: "📤",
    QueueStatus.OCR_RUNNING: "⏳",
    QueueStatus.OCR_DONE: "📷",
    QueueStatus.LLM_QUEUED: "📤",
    QueueStatus.LLM_RUNNING: "🤖",
    QueueStatus.LLM_DONE: "✅",
    QueueStatus.WAITING_REVIEW: "📋",
    QueueStatus.ACCEPTED: "👍",
    QueueStatus.ARCHIVED: "💾",
    QueueStatus.SKIPPED: "⏭️",
    QueueStatus.DELETED: "🗑️",
    QueueStatus.ERROR_OCR: "❌",
    QueueStatus.ERROR_LLM: "❌",
    QueueStatus.ERROR_ARCHIVE: "❌",
}


def _queue_items_from_state(state: dict) -> list[QueueItem]:
    """Reconstitute QueueItem objects from Backend state dict."""
    return [QueueItem(**d) for d in state.get("queue", [])]


def _render_queue_html(items: list[QueueItem], selected_idx: int,
                       page: int = 0, page_size: int = 10) -> str:
    """Render queue as HTML table with JS bridge for click-to-select + pagination."""
    if not items:
        return "<p style='color:#888;padding:12px;'>队列为空，请上传截图</p>"

    total_pages = max(1, (len(items) + page_size - 1) // page_size)
    page = max(0, min(page, total_pages - 1))
    start = page * page_size
    end = min(start + page_size, len(items))
    page_items = items[start:end]

    rows = []
    for item in page_items:
        icon = STATUS_ICONS.get(item.status, "❓")
        label = item.record.meta.lecture if (item.record and item.record.meta.lecture) else f"#{item.id + 1}"
        img_tag = f"📷×{len(item.image_paths)} " if len(item.image_paths) > 1 else ""
        sel = item.id == selected_idx
        marker = "●" if sel else "○"
        row_style = (
            "border-left:3px solid #6366f1;background:rgba(99,102,241,0.06);font-weight:500;"
            if sel else "border-left:3px solid transparent;background:transparent;"
        )
        rows.append(
            f"<tr style='cursor:pointer;{row_style}' "
            f"onclick=\"(function(e){{"
            f"var el=document.querySelector('#queue_selector textarea, #queue_selector input');"
            f"if(!el)return;"
            f"var p=el.tagName==='TEXTAREA'?HTMLTextAreaElement.prototype:HTMLInputElement.prototype;"
            f"Object.getOwnPropertyDescriptor(p,'value').set.call(el,String({item.id}));"
            f"el.dispatchEvent(new InputEvent('input',{{bubbles:true,inputType:'insertText'}}));"
            f"}})(event)\">"
            f"<td style='width:24px;'>{marker}</td>"
            f"<td style='width:24px;'>{icon}</td>"
            f"<td style='max-width:140px;overflow:hidden;'>{img_tag}{label}</td>"
            f"</tr>"
        )

    table = "<table style='width:100%;font-size:13px;'>" + "\n".join(rows) + "</table>"

    # Pagination bar
    pagination = (
        f"<div style='display:flex;justify-content:center;align-items:center;"
        f"gap:12px;padding:8px 0;font-size:12px;color:#888;margin-top:4px;'>"
        f"<span onclick=\"(function(e){{"
        f"var el=document.querySelector('#page_selector textarea, #page_selector input');"
        f"if(!el)return;"
        f"var p=el.tagName==='TEXTAREA'?HTMLTextAreaElement.prototype:HTMLInputElement.prototype;"
        f"Object.getOwnPropertyDescriptor(p,'value').set.call(el,'prev');"
        f"el.dispatchEvent(new InputEvent('input',{{bubbles:true,inputType:'insertText'}}));"
        f"}})(event)\" style='cursor:pointer;user-select:none;"
        f"color:{'#6366f1' if page > 0 else '#444'};font-weight:bold;'>"
        f"◀ 上页</span>"
        f"<span>第 {page + 1}/{total_pages} 页</span>"
        f"<span onclick=\"(function(e){{"
        f"var el=document.querySelector('#page_selector textarea, #page_selector input');"
        f"if(!el)return;"
        f"var p=el.tagName==='TEXTAREA'?HTMLTextAreaElement.prototype:HTMLInputElement.prototype;"
        f"Object.getOwnPropertyDescriptor(p,'value').set.call(el,'next');"
        f"el.dispatchEvent(new InputEvent('input',{{bubbles:true,inputType:'insertText'}}));"
        f"}})(event)\" style='cursor:pointer;user-select:none;"
        f"color:{'#6366f1' if page < total_pages - 1 else '#444'};font-weight:bold;'>"
        f"下页 ▶</span>"
        f"</div>"
    )

    return table + pagination


def _render_queue_from_state(state: dict) -> str:
    """Render queue HTML from state dict, including pagination."""
    items = _queue_items_from_state(state)
    return _render_queue_html(items, state.get("selected_idx", 0),
                              page=state.get("queue_page", 0),
                              page_size=state.get("page_size", 10))


def _nav_info(state: dict) -> str:
    """Build navigation info bar."""
    total = state.get("total", 0)
    if total == 0:
        return ""
    idx = state.get("selected_idx", 0) + 1
    return (f"**{idx}/{total}** | ✅ {state.get('accepted', 0)} "
            f"| ⏭️ {state.get('skipped', 0)} | 🗑️ {state.get('deleted', 0)} "
            f"| ❌ {state.get('errors', 0)} "
            f"| 📋 待审: {state.get('waiting_review', 0)}")


def _render_md_preview(item: QueueItem) -> str:
    """Render final MD preview from a QueueItem."""
    if item is None or item.record is None:
        return "*暂无内容，请先完成 LLM 整理*"
    try:
        from src.archive import ArchiveEngine
        engine = ArchiveEngine(vault_root=_backend.settings.paths.vault_root)
        return engine._render_md(item.record)
    except Exception as e:
        return f"*渲染失败: {e}*"


def _render_vault_tree_html(tree: dict) -> str:
    """Render vault directory tree as collapsible HTML with clickable files."""
    if not tree:
        return "<p style='color:#888;padding:12px;'>题库为空，请先归档题目</p>"

    total = 0
    parts = []

    for subject in sorted(tree.keys()):
        lectures = tree[subject]
        subj_count = sum(
            sum(len(files) for files in qtypes.values())
            for qtypes in lectures.values()
        )
        total += subj_count

        parts.append(f'<details open>')
        parts.append(f'<summary style="cursor:pointer;font-weight:bold;'
                     f'color:#6366f1;padding:4px 0;font-size:14px;">'
                     f'📂 {subject} ({subj_count})</summary>')

        for lecture in sorted(lectures.keys()):
            qtypes = lectures[lecture]
            lec_count = sum(len(files) for files in qtypes.values())

            parts.append(f'<details open style="margin-left:16px;">')
            parts.append(f'<summary style="cursor:pointer;padding:2px 0;'
                         f'font-size:13px;">'
                         f'📁 {lecture} ({lec_count})</summary>')

            for qtype in sorted(qtypes.keys()):
                files = qtypes[qtype]
                if not files:
                    continue

                parts.append(f'<details style="margin-left:16px;">')
                parts.append(f'<summary style="cursor:pointer;'
                             f'color:#888;font-size:12px;padding:2px 0;">'
                             f'📂 {qtype} ({len(files)})</summary>')

                for f in files:
                    filename = f["filename"]
                    display = filename.replace(".md", "")
                    # Truncate long names
                    if len(display) > 36:
                        display = display[:33] + "..."
                    rel = f["path"]  # relative to vault_root

                    parts.append(
                        f'<div style="margin-left:24px;padding:2px 0;'
                        f'cursor:pointer;font-size:12px;'
                        f'color:#d1d5db;'
                        f'" '
                        f'onclick="(function(e){{'
                        f"var el=document.querySelector('#vault_selector textarea, #vault_selector input');"
                        f'if(!el)return;'
                        f"var p=el.tagName==='TEXTAREA'?HTMLTextAreaElement.prototype:HTMLInputElement.prototype;"
                        f"Object.getOwnPropertyDescriptor(p,'value').set.call(el,`{rel}`);"
                        f"el.dispatchEvent(new InputEvent('input',{{bubbles:true,inputType:'insertText'}}));"
                        f'}})(event)"'
                        f'onmouseover="this.style.color=\'#fff\'" '
                        f'onmouseout="this.style.color=\'#d1d5db\'" '
                        f'>📄 {display}</div>'
                    )

                parts.append('</details>')

            parts.append('</details>')

        parts.append('</details>')

    header = (f'<div style="padding:4px 0 8px 0;font-size:13px;color:#888;">'
              f'📚 共 {total} 道题目</div>')
    return header + "\n".join(parts)


# ── Vault browser handlers ──────────────────────────────────────────────────


def handle_vault_select(path_str: str = "") -> tuple:
    """Select a vault file and return its rendered MD content."""
    if not path_str:
        return "*点击左侧文件查看内容*", ""
    content = _backend.read_vault_file(path_str)
    return content, path_str


def handle_vault_delete(current_path: str = "") -> tuple:
    """Delete the currently-selected vault file."""
    if not current_path:
        tree_html = _render_vault_tree_html(_backend.get_vault_tree())
        return "*请先在左侧选择要删除的题目*", "*点击左侧文件名查看题目内容*", "", tree_html
    result = _backend.delete_vault_file(current_path)
    tree_html = _render_vault_tree_html(_backend.get_vault_tree())
    if result["success"]:
        msg = "✅ 已删除"
        new_md = "*题目已删除*"
        label = ""
    else:
        msg = f"❌ {'; '.join(result.get('errors', ['未知错误']))}"
        new_md = _backend.read_vault_file(current_path)  # re-read to keep preview
        label = current_path
    return msg, new_md, label, tree_html


def handle_vault_refresh() -> tuple:
    """Refresh the vault tree."""
    tree = _backend.get_vault_tree()
    return _render_vault_tree_html(tree)


def _build_detail_from_state(state: dict) -> tuple:
    """Build all detail panel outputs (12-element tuple) from a state dict.

    Output order (matching the original Gradio outputs):
      qhtml, ocr_text, ocr_text, md, record_dict,
      subject, lecture, qtype, opd, key_insight, nav, qhtml
    """
    items = _queue_items_from_state(state)
    idx = state.get("selected_idx", 0)
    page = state.get("queue_page", 0)
    page_size = state.get("page_size", 10)
    item = items[idx] if 0 <= idx < len(items) else None
    qhtml = _render_queue_html(items, idx, page=page, page_size=page_size)
    nav = _nav_info(state)

    if item is None:
        return qhtml, "", "", "", {}, "高等数学", "", "解答题", "", "", nav, qhtml

    ocr_text = item.ocr_text or ""
    record_dict = item.record.model_dump() if item.record else {}
    md = _render_md_preview(item)

    if item.record:
        m = item.record.meta
        return (
            qhtml, ocr_text, ocr_text, md, record_dict,
            m.subject.value, m.lecture, m.question_type.value,
            m.opd.target or "",
            f"🔑 {item.record.solution.key_insight}" if item.record.solution.key_insight else "",
            nav, qhtml,
        )
    return (
        qhtml, ocr_text, ocr_text, md, record_dict,
        "高等数学", "", "解答题", "", "", nav, qhtml,
    )


# ── Event handlers ────────────────────────────────────────────────────────────


def handle_add_images(files: list[str] | None, notes: str) -> tuple:
    """Add images to queue via Backend. Fast — no blocking work."""
    if not files:
        state = _backend.get_state()
        return _render_queue_html([], 0), "⚠️ 请上传图片文件", None, notes

    file_list = [str(Path(f).resolve()) for f in files if f]
    try:
        _backend.add_images(file_list, notes)
    except ValueError as e:
        state = _backend.get_state()
        qhtml = _render_queue_from_state(state)
        return qhtml, f"⚠️ {e}", None, notes

    state = _backend.get_state()
    qhtml = _render_queue_from_state(state)
    total = state.get("total", 0)
    return qhtml, f"✅ 已添加第 {total} 题，共 {total} 题", None, ""


def handle_select_item(idx_str: str = "") -> tuple:
    """Select a queue item and return all detail panels."""
    if idx_str:
        try:
            _backend.select_item(int(idx_str))
        except (ValueError, TypeError):
            pass

    # Build 11-element tuple matching select_id.change outputs
    state = _backend.get_state()
    items = _queue_items_from_state(state)
    idx = state.get("selected_idx", 0)
    item = items[idx] if 0 <= idx < len(items) else None
    qhtml = _render_queue_from_state(state)
    nav = _nav_info(state)

    if item is None:
        return "", "", "", {}, "高等数学", "", "解答题", "", "", nav, qhtml

    ocr_text = item.ocr_text or ""
    record_dict = item.record.model_dump() if item.record else {}
    md = _render_md_preview(item)

    if item.record:
        m = item.record.meta
        return (
            ocr_text, ocr_text, md, record_dict,
            m.subject.value, m.lecture, m.question_type.value,
            m.opd.target or "",
            f"🔑 {item.record.solution.key_insight}" if item.record.solution.key_insight else "",
            nav, qhtml,
        )
    return (
        ocr_text, ocr_text, md, record_dict,
        "高等数学", "", "解答题", "", "", nav, qhtml,
    )


def handle_poll() -> tuple:
    """Called every 1.5s to refresh queue + detail panels (11 outputs)."""
    state = _backend.get_state()
    items = _queue_items_from_state(state)
    idx = state.get("selected_idx", 0)
    qhtml = _render_queue_from_state(state)
    nav = _nav_info(state)
    item = items[idx] if 0 <= idx < len(items) else None

    if item is None:
        return qhtml, nav, "", "", "*暂无内容*", {}, "", "高等数学", "", "解答题", ""

    ocr_text = item.ocr_text or ""
    record_dict = item.record.model_dump() if item.record else {}
    md = _render_md_preview(item)

    if item.record:
        m = item.record.meta
        return (
            qhtml, nav, ocr_text, ocr_text, md, record_dict,
            f"🔑 {item.record.solution.key_insight}" if item.record.solution.key_insight else "",
            m.subject.value, m.lecture, m.question_type.value,
            m.opd.target or "",
        )
    return (
        qhtml, nav, ocr_text, ocr_text, md, record_dict,
        "", "高等数学", "", "解答题", "",
    )


def handle_ocr_all(notes: str) -> tuple:
    """Trigger batch OCR via Backend. Non-blocking."""
    state = _backend.get_state()
    items = _queue_items_from_state(state)
    idle = [it for it in items if it.status == QueueStatus.IDLE]
    if not idle:
        qhtml = _render_queue_from_state(state)
        return qhtml, "⚠️ 没有待 OCR 的题目"

    result = _backend.run_ocr_batch(notes)
    state = _backend.get_state()
    qhtml = _render_queue_from_state(state)
    return qhtml, f"🔍 OCR 已开始（{result.get('idle_count', 0)} 题），后台处理中..."


def handle_llm_all(concurrency: int) -> tuple:
    """Trigger batch LLM via Backend. Non-blocking."""
    _backend.set_concurrency(int(concurrency))

    state = _backend.get_state()
    items = _queue_items_from_state(state)
    ready = [it for it in items if it.status == QueueStatus.OCR_DONE]
    if not ready:
        qhtml = _render_queue_from_state(state)
        return qhtml, "⚠️ 没有待整理的题目（请先 OCR）"

    result = _backend.run_llm_batch()
    state = _backend.get_state()
    qhtml = _render_queue_from_state(state)
    return qhtml, f"🤖 LLM 已开始（{result.get('ready_count', 0)} 题），后台处理中..."


def handle_review(action: str, subject_adj: str, lecture_adj: str,
                  qtype_adj: str, opd_adj: str) -> tuple:
    """Handle review action via Backend."""
    result = _backend.review(action, {
        "subject_adj": subject_adj,
        "lecture_adj": lecture_adj,
        "qtype_adj": qtype_adj,
        "opd_adj": opd_adj,
    })

    state = _backend.get_state()
    qhtml = _render_queue_from_state(state)
    nav = _nav_info(state)

    if result.get("status") == "error":
        return qhtml, f"❌ {result.get('msg', '未知错误')}", nav

    msgs = {
        "accept": "✅ 已归档",
        "skip": "⏭️ 已跳过",
        "delete": "🗑️ 已删除",
        "reprocess": "🔄 已重新提交 LLM",
    }
    return qhtml, msgs.get(action, "OK"), nav


def handle_nav_prev() -> tuple:
    """Navigate to previous WAITING_REVIEW item."""
    _backend.nav_prev()
    return _build_detail_from_state(_backend.get_state())


def handle_nav_next() -> tuple:
    """Navigate to next WAITING_REVIEW item."""
    _backend.nav_next()
    return _build_detail_from_state(_backend.get_state())


def handle_page_nav(direction: str = "") -> tuple:
    """Handle page navigation via JS bridge ('prev' or 'next')."""
    state = _backend.get_state()
    current_page = state.get("queue_page", 0)
    total_pages = state.get("total_pages", 1)

    if direction == "prev":
        _backend.set_queue_page(current_page - 1)
    elif direction == "next":
        _backend.set_queue_page(current_page + 1)

    return _build_detail_from_state(_backend.get_state())


def handle_clear_queue() -> tuple:
    """Clear the entire queue."""
    _backend.clear()
    empty_html = _render_queue_html([], 0)
    return (
        empty_html, "", "", "", {},
        "高等数学", "", "解答题", "", "",
        "队列已清空", empty_html,
    )


def handle_file_change(files: list[str] | None) -> tuple:
    """Auto-add files when auto_add is enabled."""
    if not files or not _backend.get_auto_add():
        # Use gr.skip() to leave UI components unchanged.
        # Returning None would clear queue_html, which is destructive
        # when triggered by the cascade: add_images clears file_input
        # → file_input.change fires again with files=None.
        return gr.skip(), gr.skip(), gr.skip(), gr.skip()
    return handle_add_images(files, "")


def handle_clipboard_paste(b64data: str) -> tuple:
    """Decode base64 clipboard image, save as temp file, display in upload area.

    Does NOT add to queue — the pasted image appears in the gr.File upload
    component so the user can type notes and manually click "添加到队列".
    """
    print(f"📋 [paste] received data: {len(b64data) if b64data else 0} chars, starts with image: {b64data.startswith('data:image') if b64data else False}", flush=True)
    if not b64data or not b64data.startswith("data:image"):
        state = _backend.get_state()
        return _render_queue_from_state(state), "⚠️ 粘贴板无图片", gr.skip(), gr.skip()

    try:
        # Decode base64 data URL → temp file
        header, encoded = b64data.split(",", 1)
        ext = header.split("/")[1].split(";")[0]  # e.g. "png", "jpeg"
        tmp = tempfile.NamedTemporaryFile(suffix=f".{ext}", delete=False)
        tmp.write(base64.b64decode(encoded))
        tmp.close()
        print(f"📋 [paste] decoded to temp file: {tmp.name}", flush=True)
    except Exception as e:
        print(f"❌ [paste] decode failed: {e}", flush=True)
        state = _backend.get_state()
        return _render_queue_from_state(state), f"❌ 粘贴解码失败: {e}", gr.skip(), gr.skip()

    # Return temp file path → appears in gr.File upload area.
    # gr.skip() for manual_notes preserves any text the user already typed.
    state = _backend.get_state()
    qhtml = _render_queue_from_state(state)
    return qhtml, "✅ 图片已粘贴到上传区，输入备注后点击添加", [tmp.name], gr.skip()


def handle_download_vault() -> str:
    """Create a zip of the vault and return the path for DownloadButton."""
    try:
        return _backend.create_vault_zip()
    except Exception as e:
        raise gr.Error(f"打包失败: {e}")


# ── Build UI ───────────────────────────────────────────────────────────────────

def create_app() -> gr.Blocks:
    with gr.Blocks(title=_backend.settings.gui.title) as app:
        gr.Markdown(f"# {_backend.settings.gui.title}")

        # ═══ Top Bar ═══
        with gr.Row():
            with gr.Column(scale=1, min_width=180):
                concurrency = gr.Slider(
                    label="⚡ 并发数", minimum=1, maximum=8, step=1,
                    value=_backend.settings.pipeline.max_concurrency,
                )
            with gr.Column(scale=1, min_width=100):
                auto_add_toggle = gr.Checkbox(
                    label="📥 自动入队", value=False,
                    info="选文件后自动添加到队列",
                )
            with gr.Column(scale=1, min_width=100):
                auto_ocr_toggle = gr.Checkbox(
                    label="🔍 自动 OCR", value=True,
                    info="添加图片后自动开始OCR",
                )
            with gr.Column(scale=1, min_width=100):
                auto_llm_toggle = gr.Checkbox(
                    label="🤖 自动 LLM", value=True,
                    info="OCR完成后自动进行LLM整理",
                )
            with gr.Column(scale=1, min_width=100):
                auto_archive_toggle = gr.Checkbox(
                    label="💾 自动归档", value=False,
                    info="⚠️ LLM完成后直接入库，跳过审核",
                )
            with gr.Column(scale=2):
                with gr.Row():
                    add_btn = gr.Button("➕ 添加到队列", variant="secondary")
                    ocr_all_btn = gr.Button("🔍 全部 OCR", variant="primary")
                    llm_all_btn = gr.Button("🤖 全部整理", variant="primary")
                    download_btn = gr.DownloadButton("📦 下载题库", variant="secondary", size="sm")
                    clear_btn = gr.Button("🗑️ 清空", variant="stop", size="sm")

            status_line = gr.Markdown("就绪")

        # ═══ Tabs: Queue + Vault Browser ═══
        with gr.Tabs():
            # ── Tab 1: Queue ──
            with gr.Tab("📋 队列"):
                with gr.Row():
                    # ── Left: Queue List ──
                    with gr.Column(scale=1, min_width=220):
                        gr.Markdown("### 📋 队列")
                        queue_html = gr.HTML(value="<p style='color:#888;'>请上传截图</p>")

                        # Hidden textbox for JS-driven selection
                        select_id = gr.Textbox(visible="hidden", elem_id="queue_selector")
                        # Hidden textbox for JS-driven pagination
                        page_selector = gr.Textbox(visible="hidden", elem_id="page_selector")

                        manual_notes = gr.Textbox(
                            label="📝 附加信息（添加到每题，含错因分析、题目来源、备注等）",
                            placeholder="例如：我把条件概率和联合概率搞混了 / 此题来自2024真题 / 注意区分拉格朗日和柯西中值定理...",
                            lines=2,
                        )
                        # Hidden textbox for JS-driven clipboard paste (Ctrl+V)
                        paste_input = gr.Textbox(visible="hidden", elem_id="paste_input")
                        gr.Markdown(
                            "💡 **提示**：截屏后在此页面按 **Ctrl+V** 即可粘贴图片入队",
                        )
                        file_input = gr.File(
                            label="📷 上传截图（可多选）",
                            file_types=["image"],
                            file_count="multiple",
                        )

                    # ── Right: Detail Panels ──
                    with gr.Column(scale=3):
                        nav_bar = gr.Markdown("")
                        with gr.Row():
                            prev_btn = gr.Button("◀ 上一题", size="sm", scale=1, elem_id="nav_prev")
                            next_btn = gr.Button("下一题 ▶", size="sm", scale=1, elem_id="nav_next")

                        # ② OCR Panel
                        with gr.Accordion("② OCR 识别 & 校对", open=True):
                            md_ocr_preview = gr.Markdown(
                                "请先上传图片并添加至队列",
                                latex_delimiters=[
                                    {"left": "$", "right": "$", "display": False},
                                    {"left": "$$", "right": "$$", "display": True},
                                ],
                            )
                            editable_source = gr.Textbox(
                                label="✏️ 源码编辑",
                                lines=6, interactive=True,
                            )

                        # ③ LLM Panel
                        with gr.Accordion("③ LLM 整理结果 & 调整"):
                            json_display = gr.JSON(label="结构化 JSON")
                            key_insight_display = gr.Markdown("")

                            # Review Actions — above text fields for easy access
                            with gr.Row():
                                accept_btn = gr.Button("✅ 通过（归档）", variant="primary", scale=2)
                                skip_btn = gr.Button("⏭️ 跳过", variant="secondary", scale=1)
                                reprocess_btn = gr.Button("🔄 重做", variant="stop", scale=1)
                                delete_btn = gr.Button("🗑️ 删除", variant="stop", scale=1)

                            with gr.Row():
                                adj_subject = gr.Dropdown(
                                    label="科目", choices=["高等数学", "线性代数", "概率统计"],
                                    value="高等数学", scale=1,
                                )
                                adj_lecture = gr.Textbox(
                                    label="讲次", placeholder="第1讲_函数极限与连续", scale=2,
                                )
                            with gr.Row():
                                adj_qtype = gr.Dropdown(
                                    label="题型", choices=["选择题", "填空题", "解答题"],
                                    value="解答题", scale=1,
                                )
                                adj_opd_target = gr.Textbox(
                                    label="OPD 目标", placeholder="O_极限", scale=1,
                                )

                        # ④ MD Preview
                        with gr.Accordion("④ 最终 MD 预览（LaTeX 渲染）", open=True):
                            md_final_preview = gr.Markdown(
                                "*暂无内容*",
                                latex_delimiters=[
                                    {"left": "$", "right": "$", "display": False},
                                    {"left": "$$", "right": "$$", "display": True},
                                ],
                            )

                        review_status = gr.Markdown("")

            # ── Tab 2: Vault Browser ──
            with gr.Tab("📚 题库"):
                with gr.Row():
                    with gr.Column(scale=1, min_width=240):
                        vault_refresh_btn = gr.Button("🔄 刷新", size="sm")
                        vault_tree_html = gr.HTML(
                            value=_render_vault_tree_html(_backend.get_vault_tree())
                        )
                        # Hidden textbox for JS-driven vault file selection
                        vault_selector = gr.Textbox(visible="hidden", elem_id="vault_selector")

                    with gr.Column(scale=3):
                        vault_md_preview = gr.Markdown(
                            "*点击左侧文件名查看题目内容*",
                            latex_delimiters=[
                                {"left": "$", "right": "$", "display": False},
                                {"left": "$$", "right": "$$", "display": True},
                            ],
                        )
                        vault_file_label = gr.Markdown("")
                        with gr.Row():
                            vault_delete_btn = gr.Button(
                                "🗑️ 删除此题", variant="stop", size="sm",
                                visible=True,
                            )
                            vault_delete_status = gr.Markdown("")

        # ── Polling timer for auto-refresh ──
        poll_timer = gr.Number(visible=False, value=0, every=1.5)

        # ═══ Wire Events ═══

        # Auto-config sync: toggle changes → Backend
        auto_add_toggle.change(
            fn=lambda v: _backend.set_auto_add(v),
            inputs=[auto_add_toggle],
            outputs=[],
        )
        auto_ocr_toggle.change(
            fn=lambda v: _backend.set_auto_ocr(v),
            inputs=[auto_ocr_toggle],
            outputs=[],
        )
        auto_llm_toggle.change(
            fn=lambda v: _backend.set_auto_llm(v),
            inputs=[auto_llm_toggle],
            outputs=[],
        )
        auto_archive_toggle.change(
            fn=lambda v: _backend.set_auto_archive(v),
            inputs=[auto_archive_toggle],
            outputs=[],
        )

        # Polling refresh — updates queue and detail panels
        poll_timer.change(
            fn=handle_poll,
            outputs=[
                queue_html, nav_bar,
                md_ocr_preview, editable_source, md_final_preview, json_display,
                key_insight_display,
                adj_subject, adj_lecture, adj_qtype, adj_opd_target,
            ],
        )

        # Queue click → select item
        select_id.change(
            fn=lambda idx: handle_select_item(idx_str=idx),
            inputs=[select_id],
            outputs=[
                md_ocr_preview, editable_source, md_final_preview, json_display,
                adj_subject, adj_lecture, adj_qtype, adj_opd_target,
                key_insight_display, nav_bar, queue_html,
            ],
        )

        # Pagination — JS bridge via hidden page_selector
        page_selector.change(
            fn=lambda d: handle_page_nav(direction=d or ""),
            inputs=[page_selector],
            outputs=[
                queue_html, md_ocr_preview, editable_source, md_final_preview,
                json_display, adj_subject, adj_lecture, adj_qtype, adj_opd_target,
                key_insight_display, nav_bar, queue_html,
            ],
        )

        # Add images
        add_btn.click(
            fn=handle_add_images,
            inputs=[file_input, manual_notes],
            outputs=[queue_html, status_line, file_input, manual_notes],
        ).then(
            fn=handle_select_item,
            outputs=[
                md_ocr_preview, editable_source, md_final_preview, json_display,
                adj_subject, adj_lecture, adj_qtype, adj_opd_target,
                key_insight_display, nav_bar, queue_html,
            ],
        )

        # Auto-add: file_input change → add to queue if auto_add is on
        file_input.change(
            fn=handle_file_change,
            inputs=[file_input],
            outputs=[queue_html, status_line, file_input, manual_notes],
        )

        # Clipboard paste: JS bridge via hidden paste_input.
        # Pasted image appears in file_input upload area; user types notes
        # then clicks "➕ 添加到队列" — no auto-add to queue.
        paste_input.change(
            fn=lambda d: handle_clipboard_paste(d or ""),
            inputs=[paste_input],
            outputs=[queue_html, status_line, file_input, manual_notes],
        ).then(
            fn=handle_select_item,
            outputs=[
                md_ocr_preview, editable_source, md_final_preview, json_display,
                adj_subject, adj_lecture, adj_qtype, adj_opd_target,
                key_insight_display, nav_bar, queue_html,
            ],
        )

        # OCR All
        ocr_all_btn.click(
            fn=handle_ocr_all,
            inputs=[manual_notes],
            outputs=[queue_html, status_line],
        )

        # LLM All
        llm_all_btn.click(
            fn=handle_llm_all,
            inputs=[concurrency],
            outputs=[queue_html, status_line],
        )

        # Navigation
        prev_btn.click(
            fn=handle_nav_prev,
            outputs=[
                queue_html, md_ocr_preview, editable_source, md_final_preview,
                json_display, adj_subject, adj_lecture, adj_qtype, adj_opd_target,
                key_insight_display, nav_bar, queue_html,
            ],
        )
        next_btn.click(
            fn=handle_nav_next,
            outputs=[
                queue_html, md_ocr_preview, editable_source, md_final_preview,
                json_display, adj_subject, adj_lecture, adj_qtype, adj_opd_target,
                key_insight_display, nav_bar, queue_html,
            ],
        )

        # Review actions
        for btn, action in [(accept_btn, "accept"), (skip_btn, "skip"),
                            (reprocess_btn, "reprocess"), (delete_btn, "delete")]:
            btn.click(
                fn=lambda *args, act=action: handle_review(act, *args),
                inputs=[adj_subject, adj_lecture, adj_qtype, adj_opd_target],
                outputs=[queue_html, review_status, nav_bar],
            ).then(
                fn=handle_select_item,
                outputs=[
                    md_ocr_preview, editable_source, md_final_preview, json_display,
                    adj_subject, adj_lecture, adj_qtype, adj_opd_target,
                    key_insight_display, nav_bar, queue_html,
                ],
            )

        # Clear queue
        clear_btn.click(
            fn=handle_clear_queue,
            outputs=[
                queue_html, md_ocr_preview, editable_source, md_final_preview,
                json_display, adj_subject, adj_lecture, adj_qtype, adj_opd_target,
                key_insight_display, nav_bar, queue_html,
            ],
        )

        # Download vault zip
        download_btn.click(
            fn=handle_download_vault,
            inputs=[],
            outputs=[download_btn],
        )

        # ── Vault Browser events ──
        vault_selector.change(
            fn=lambda p: handle_vault_select(path_str=p or ""),
            inputs=[vault_selector],
            outputs=[vault_md_preview, vault_file_label],
        )

        vault_delete_btn.click(
            fn=lambda p: handle_vault_delete(current_path=p or ""),
            inputs=[vault_selector],
            outputs=[vault_delete_status, vault_md_preview, vault_file_label, vault_tree_html],
        )

        vault_refresh_btn.click(
            fn=handle_vault_refresh,
            outputs=[vault_tree_html],
        )

    return app


if __name__ == "__main__":
    app = create_app()
    app.launch(
        server_name=_backend.settings.gui.host,
        server_port=_backend.settings.gui.port,
        head=_PASTE_JS,
    )
