"""Smoke tests for the Gradio GUI app (thin API-client architecture)."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.models import QueueItem, QueueStatus, ProblemRecord, Meta, Solution, Related, OpdMarkers, Source
from src.models import Subject, QuestionType, KeyAbility


@pytest.fixture
def sample_queue_item():
    """A sample QueueItem in WAITING_REVIEW state."""
    record = ProblemRecord(
        meta=Meta(
            subject=Subject.GAO_SHU, lecture="第1讲_函数极限与连续",
            question_type=QuestionType.XUAN_ZE,
            source=Source(example_id="例1.3"),
            opd=OpdMarkers(target="O_极限", procedures=["P11_正向思路"], details=["D22_转换等价表述"]),
            key_ability=[KeyAbility.CONCEPT],
            tags=["test"],
        ),
        problem="test problem",
        answer="42",
        solution=Solution(approach="test approach", key_insight="test insight", steps=["step1"]),
        related=Related(knowledge_points=["kp1"]),
    )
    return QueueItem(
        id=0, status=QueueStatus.WAITING_REVIEW,
        image_paths=["/tmp/test.png"],
        ocr_text="OCR text here",
        user_notes="user notes",
        record=record,
        filename="第1讲_选择题_例1-3_测试.md",
    )


def _make_state(items: list[QueueItem] | None = None, selected_idx: int = 0,
                auto_ocr: bool = False, auto_llm: bool = False, concurrency: int = 3) -> dict:
    """Build a state dict matching what /api/state returns."""
    q = items or []
    total = len(q)
    selected_item = q[selected_idx].model_dump() if 0 <= selected_idx < total else None
    return {
        "queue": [it.model_dump() for it in q],
        "selected_idx": selected_idx,
        "selected_item": selected_item,
        "auto_ocr": auto_ocr,
        "auto_llm": auto_llm,
        "concurrency": concurrency,
        "total": total,
        "waiting_review": sum(1 for it in q if it.status == QueueStatus.WAITING_REVIEW),
        "accepted": sum(1 for it in q if it.status in (QueueStatus.ACCEPTED, QueueStatus.ARCHIVED)),
        "skipped": sum(1 for it in q if it.status == QueueStatus.SKIPPED),
        "errors": sum(1 for it in q if it.status in (QueueStatus.ERROR_OCR, QueueStatus.ERROR_LLM)),
    }


class TestGuiApp:
    """Test that the GUI app builds and rendering works (no API needed)."""

    def test_create_app_returns_gradio_app(self):
        import gradio as gr
        from gui.app import create_app
        app = create_app()
        assert isinstance(app, gr.Blocks)

    def test_gui_imports_cleanly(self):
        import gui.app
        assert gui.app.create_app is not None

    def test_queue_item_status_icons(self):
        """All QueueStatus values should have icons."""
        from gui.app import STATUS_ICONS
        for status in QueueStatus:
            assert status in STATUS_ICONS, f"Missing icon for {status}"

    def test_render_md_preview_empty(self):
        from gui.app import _render_md_preview
        result = _render_md_preview(None)
        assert "暂无" in result

    def test_render_md_preview_with_record(self, sample_queue_item, tmp_path):
        from gui.app import _render_md_preview
        # _render_md_preview uses _settings.paths.vault_root from config
        result = _render_md_preview(sample_queue_item)
        assert "## ❓ 题目" in result
        assert "## ✅ 答案" in result
        assert "## 🔑 解题关键" in result

    def test_nav_info_empty(self):
        from gui.app import _nav_info
        state = _make_state([])
        assert _nav_info(state) == ""

    def test_nav_info_with_items(self, sample_queue_item):
        from gui.app import _nav_info
        state = _make_state([sample_queue_item], selected_idx=0)
        info = _nav_info(state)
        assert "1/1" in info
        assert "待审" in info

    def test_render_queue_html_empty(self):
        from gui.app import _render_queue_html
        html = _render_queue_html([], 0)
        assert "队列为空" in html

    def test_render_queue_html_with_items(self, sample_queue_item):
        from gui.app import _render_queue_html
        html = _render_queue_html([sample_queue_item], 0)
        assert "第1讲_函数极限与连续" in html

    def test_render_queue_html_selected_highlight(self, sample_queue_item):
        from gui.app import _render_queue_html
        items = [sample_queue_item]
        html = _render_queue_html(items, 0)
        # Selected item should have the indigo border-left
        assert "rgba(99,102,241,0.06)" in html

    def test_build_detail_from_state_empty(self):
        from gui.app import _build_detail_from_state
        state = _make_state([])
        result = _build_detail_from_state(state)
        assert len(result) == 12  # Returns full output tuple
        # First two: queue_html, ocr_text
        assert result[1] == ""  # ocr_text

    def test_build_detail_from_state_with_item(self, sample_queue_item):
        from gui.app import _build_detail_from_state
        state = _make_state([sample_queue_item], selected_idx=0)
        result = _build_detail_from_state(state)
        assert len(result) == 12
        assert result[1] == "OCR text here"  # ocr_text
        # subject
        assert result[5] == "高等数学"


class TestGuiBackendIntegration:
    """Tests for Backend integration (direct, no HTTP)."""

    def test_backend_state_empty(self):
        """Backend should return valid state dict."""
        from backend.engine import Backend
        b = Backend()
        state = b.get_state()
        assert "queue" in state
        assert "selected_idx" in state
        assert state["total"] == 0

    def test_add_and_clear_via_backend(self):
        """Add a fake item and clear the queue via Backend."""
        import tempfile
        from backend.engine import Backend

        b = Backend()
        # Add item (will fail because image doesn't exist — that's OK)
        try:
            b.add_images(["/tmp/nonexistent.png"], notes="test")
            assert False, "Should have raised"
        except ValueError as e:
            assert "No valid image files found" in str(e)

        # Create a temp file and add successfully
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(b"fake png")
            tmp_path = f.name

        b.add_images([tmp_path])
        state = b.get_state()
        assert state["total"] == 1

        # Clear
        b.clear()
        assert len(b.get_all()) == 0

        import os
        os.unlink(tmp_path)
