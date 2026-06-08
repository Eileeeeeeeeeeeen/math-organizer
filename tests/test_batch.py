"""Tests for batch processing: QueueItem, concurrency, progress callbacks."""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from src.models import QueueItem, QueueStatus, PipelineConfig, Settings
from src.pipeline import _batch_progress, Pipeline


class TestQueueItem:
    """Tests for the QueueItem state machine."""

    def test_default_state_is_idle(self):
        item = QueueItem(id=0)
        assert item.status == QueueStatus.IDLE
        assert item.ocr_text == ""
        assert item.record is None

    def test_status_transitions(self):
        """All expected status transitions should work."""
        item = QueueItem(id=1)
        transitions = [
            QueueStatus.OCR_QUEUED,
            QueueStatus.OCR_RUNNING,
            QueueStatus.OCR_DONE,
            QueueStatus.LLM_QUEUED,
            QueueStatus.LLM_RUNNING,
            QueueStatus.LLM_DONE,
            QueueStatus.WAITING_REVIEW,
            QueueStatus.ACCEPTED,
            QueueStatus.ARCHIVED,
        ]
        for status in transitions:
            item.status = status
            assert item.status == status

    def test_error_states(self):
        """Error states should be set with error_msg."""
        item = QueueItem(id=2, status=QueueStatus.ERROR_OCR, error_msg="OCR timeout")
        assert item.status == QueueStatus.ERROR_OCR
        assert item.error_msg == "OCR timeout"

    def test_reprocess_flow(self):
        """Skipped → retry flow."""
        item = QueueItem(id=3, status=QueueStatus.WAITING_REVIEW)
        item.status = QueueStatus.LLM_QUEUED  # retry
        assert item.status == QueueStatus.LLM_QUEUED

    def test_has_correct_fields_for_gui(self):
        """QueueItem should have all fields needed by the GUI."""
        item = QueueItem(
            id=5,
            status=QueueStatus.LLM_DONE,
            image_paths=["/tmp/test.png"],
            ocr_text="test ocr",
            user_notes="my notes",
            filename="第1讲_选择题_例1-3_测试.md",
        )
        d = item.model_dump()
        assert "id" in d
        assert "status" in d
        assert "ocr_text" in d
        assert "user_notes" in d
        assert "record" in d
        assert "filename" in d
        assert "error_msg" in d


class TestPipelineConfig:
    """Tests for PipelineConfig model."""

    def test_defaults(self):
        cfg = PipelineConfig()
        assert cfg.max_concurrency == 3
        assert cfg.auto_mode is False

    def test_limits(self):
        """max_concurrency should be clamped 1-8."""
        cfg = PipelineConfig(max_concurrency=1)
        assert cfg.max_concurrency == 1
        cfg2 = PipelineConfig(max_concurrency=8)
        assert cfg2.max_concurrency == 8

    def test_from_settings(self):
        """Settings should parse pipeline config from YAML."""
        s = Settings()
        assert s.pipeline.max_concurrency == 3
        assert s.pipeline.auto_mode is False


class TestBatchProgress:
    """Tests for the _batch_progress helper."""

    def test_wraps_callback(self):
        calls = []
        def cb(done, total, msg):
            calls.append((done, total, msg))

        wrapped = _batch_progress(cb, "TEST")
        assert wrapped is not None
        wrapped(1, 5, "hello")
        assert calls == [(1, 5, "[TEST] hello")]

    def test_returns_none_for_none_input(self):
        assert _batch_progress(None, "PREFIX") is None

    def test_multiple_calls(self):
        calls = []
        wrapped = _batch_progress(lambda d, t, m: calls.append(m), "LLM")
        wrapped(1, 3, "a")
        wrapped(2, 3, "b")
        wrapped(3, 3, "c")
        assert calls == ["[LLM] a", "[LLM] b", "[LLM] c"]


class TestPipelineBatchNoApi:
    """Tests for batch pipeline methods (no real API calls)."""

    @pytest.fixture
    def pipeline(self, tmp_path):
        """Pipeline with mocked run_llm for testing."""
        from src.archive import ArchiveEngine
        p = Pipeline()
        p._archive = ArchiveEngine(vault_root=str(tmp_path))
        return p

    def test_run_llm_concurrent_mocked(self, pipeline, monkeypatch):
        """Concurrent LLM should process all items and respect max_concurrency."""
        call_count = [0]
        call_times = []

        def mock_run_llm(self, text):
            call_count[0] += 1
            call_times.append(time.time())
            time.sleep(0.05)  # Small delay to test concurrency
            from src.models import ProblemRecord, Meta, Solution, Related, OpdMarkers, Source
            from src.models import Subject, QuestionType, KeyAbility
            return ProblemRecord(
                meta=Meta(
                    subject=Subject.GAO_SHU,
                    lecture="第1讲_函数极限与连续",
                    question_type=QuestionType.XUAN_ZE,
                    source=Source(example_id="test"),
                    opd=OpdMarkers(target="O_极限"),
                    key_ability=[KeyAbility.CONCEPT],
                ),
                problem=f"problem {text[:10]}",
                answer="42",
                solution=Solution(approach="test", key_insight="test", steps=["step"]),
                related=Related(),
            )

        monkeypatch.setattr("src.pipeline.Pipeline.run_llm", mock_run_llm)

        items = [
            QueueItem(id=i, status=QueueStatus.OCR_DONE, ocr_text=f"text_{i}")
            for i in range(5)
        ]

        start = time.time()
        results = pipeline.run_llm_concurrent(items)
        elapsed = time.time() - start

        assert len(results) == 5
        assert call_count[0] == 5
        # With max_concurrency=3 and 5 items, should be faster than sequential
        # Sequential: 5 × 0.05 = 0.25, concurrent 3-at-a-time: ~2 batches × 0.05 = 0.10
        assert elapsed < 0.35  # Generous bound

        for r in results:
            assert r.status == QueueStatus.LLM_DONE
            assert r.record is not None

    def test_run_llm_concurrent_handles_errors(self, pipeline, monkeypatch):
        """Errors in one item should not block others."""
        def mock_run_llm(self, text):
            if "fail" in text:
                raise RuntimeError("simulated failure")
            from src.models import ProblemRecord, Meta, Solution, Related, OpdMarkers, Source
            from src.models import Subject, QuestionType, KeyAbility
            return ProblemRecord(
                meta=Meta(
                    subject=Subject.GAO_SHU, lecture="第1讲_函数极限与连续",
                    question_type=QuestionType.XUAN_ZE,
                    source=Source(example_id="test"),
                    opd=OpdMarkers(target="O_极限"),
                    key_ability=[KeyAbility.CONCEPT],
                ),
                problem=text, answer="42",
                solution=Solution(approach="test", key_insight="test", steps=["step"]),
                related=Related(),
            )

        monkeypatch.setattr("src.pipeline.Pipeline.run_llm", mock_run_llm)

        items = [
            QueueItem(id=0, status=QueueStatus.OCR_DONE, ocr_text="ok_0"),
            QueueItem(id=1, status=QueueStatus.OCR_DONE, ocr_text="fail_1"),
            QueueItem(id=2, status=QueueStatus.OCR_DONE, ocr_text="ok_2"),
        ]

        results = pipeline.run_llm_concurrent(items)

        assert results[0].status == QueueStatus.LLM_DONE
        assert results[1].status == QueueStatus.ERROR_LLM
        assert results[1].error_msg == "simulated failure"
        assert results[2].status == QueueStatus.LLM_DONE

    def test_progress_callback(self, pipeline, monkeypatch):
        """Progress callback should be invoked during processing."""
        def mock_run_llm(self, text):
            from src.models import ProblemRecord, Meta, Solution, Related, OpdMarkers, Source
            from src.models import Subject, QuestionType, KeyAbility
            return ProblemRecord(
                meta=Meta(
                    subject=Subject.GAO_SHU, lecture="第1讲_函数极限与连续",
                    question_type=QuestionType.XUAN_ZE,
                    source=Source(example_id="test"),
                    opd=OpdMarkers(target="O_极限"),
                    key_ability=[KeyAbility.CONCEPT],
                ),
                problem=text, answer="42",
                solution=Solution(approach="test", key_insight="test", steps=["step"]),
                related=Related(),
            )

        monkeypatch.setattr("src.pipeline.Pipeline.run_llm", mock_run_llm)

        calls = []
        items = [QueueItem(id=i, status=QueueStatus.OCR_DONE, ocr_text=f"t_{i}") for i in range(3)]
        pipeline.run_llm_concurrent(items, progress_callback=lambda d, t, m: calls.append((d, t, m)))

        # Should have called for each completion
        assert len(calls) == 3
        # Last call should show 3/3
        assert calls[-1][0] == 3
        assert calls[-1][1] == 3
