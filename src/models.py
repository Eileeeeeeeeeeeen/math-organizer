"""Pydantic models for the math-organizer system.

These models serve as the single source of truth for all data validation.
They mirror the JSON Schema defined in template/LLM 输出 JSON Schema.json
and the YAML frontmatter spec from the planning document.
"""

from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Annotated, Optional

from pydantic import BaseModel, Field, StringConstraints, field_validator


# ── Enums ────────────────────────────────────────────────────────────────────


class Subject(str, Enum):
    GAO_SHU = "高等数学"
    XIAN_DAI = "线性代数"
    GAI_LV = "概率统计"


class QuestionType(str, Enum):
    XUAN_ZE = "选择题"
    TIAN_KONG = "填空题"
    JIE_DA = "解答题"


class KeyAbility(str, Enum):
    CONCEPT = "概念辨析"
    CALCULATION = "计算能力"
    PROOF = "证明推理"
    COMPREHENSIVE = "综合应用"


# ── Nested Models ────────────────────────────────────────────────────────────


class Source(BaseModel):
    """题目来源信息"""
    book: str = Field(default="", description="教材名称")
    year: str = Field(default="", description="出版年份")
    page: str = Field(default="", description="页码")
    example_id: str = Field(default="", description="例题编号，如'例1.3'")


class OpdMarkers(BaseModel):
    """OPD 解题方法论标注"""
    target: str = Field(
        default="",
        description="O_ 开头的目标代码，如 O_极限",
        pattern=r"^O_\w+$",
    )
    procedures: list[str] = Field(
        default_factory=list,
        description="P_ 开头的思路代码列表",
    )
    details: list[str] = Field(
        default_factory=list,
        description="D_ 开头的细节代码列表",
    )

    @field_validator("procedures")
    @classmethod
    def check_p_codes(cls, v: list[str]) -> list[str]:
        for item in v:
            if not item.startswith("P"):
                raise ValueError(f"Procedure code must start with 'P', got: {item}")
        return v

    @field_validator("details")
    @classmethod
    def check_d_codes(cls, v: list[str]) -> list[str]:
        for item in v:
            if not item.startswith("D"):
                raise ValueError(f"Detail code must start with 'D', got: {item}")
        return v


class Meta(BaseModel):
    """题目元数据 — 对应 YAML frontmatter"""
    subject: Subject
    lecture: str = Field(
        description="讲次名称，如 '第1讲_函数极限与连续'",
        min_length=1,
    )
    question_type: QuestionType
    source: Source = Field(default_factory=Source)
    opd: OpdMarkers = Field(default_factory=OpdMarkers)
    key_ability: list[KeyAbility] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)


class Solution(BaseModel):
    """解题信息"""
    approach: str = Field(
        default="",
        description="解题核心思路",
    )
    key_insight: str = Field(
        default="",
        description="解题关键——直截了当指出核心关键点",
    )
    steps: list[str] = Field(
        default_factory=list,
        description="详细解题步骤，每步一个元素",
    )


class Related(BaseModel):
    """关联信息"""
    knowledge_points: list[str] = Field(default_factory=list)
    linked_examples: list[str] = Field(default_factory=list)


class ProblemRecord(BaseModel):
    """LLM 输出的顶层模型 — 一道完整题目的结构化数据"""
    meta: Meta
    problem: str = Field(description="题目原文，数学公式用 LaTeX 格式")
    answer: str = Field(description="最终答案，数学公式用 LaTeX 格式")
    solution: Solution = Field(default_factory=Solution)
    related: Related = Field(default_factory=Related)


# ── Frontmatter Model (what goes into YAML frontmatter of MD files) ──────────


ChineseText = Annotated[str, StringConstraints(max_length=100)]


class Frontmatter(BaseModel):
    """YAML frontmatter of an Obsidian-compatible MD file.

    This model validates every field that appears in the frontmatter
    of a generated problem MD file.
    """
    subject: Subject
    lecture: str = Field(min_length=1)
    question_type: QuestionType
    opd_target: str = Field(
        default="",
        description="O_ 目标代码",
        pattern=r"^O_\w+$",
    )
    opd_procedures: list[str] = Field(default_factory=list)
    opd_details: list[str] = Field(default_factory=list)
    key_ability: list[KeyAbility] = Field(default_factory=list)
    source_book: str = Field(default="")
    source_example: str = Field(default="")
    source_year: str = Field(default="")
    tags: list[str] = Field(default_factory=list)
    summary: str = Field(
        default="",
        max_length=100,
        description="RAG专用纯中文摘要，≤100字，不含LaTeX",
    )
    created: date = Field(default_factory=lambda: date.today())
    updated: date = Field(default_factory=lambda: date.today())


# ── Config Models ────────────────────────────────────────────────────────────


class OcrConfig(BaseModel):
    provider: str = "paddleocr_vl"
    api_endpoint: str = ""
    api_key: str = ""
    model: str = "PaddleOCR-VL-1.6"
    output_format: str = "markdown"
    timeout: int = 30


class LlmConfig(BaseModel):
    provider: str = "deepseek"
    api_base: str = "https://api.deepseek.com/v1"
    api_key: str = ""
    model_default: str = "deepseek-v4-flash"
    model_complex: str = "deepseek-v4-pro"
    reasoning_effort: str = "high"
    max_retries: int = 2
    temperature: float = Field(default=0.1, ge=0.0, le=2.0)


class PathsConfig(BaseModel):
    vault_root: str = "./考研数学题库"
    assets_dir: str = "assets/images"
    config_dir: str = "config"


class GUIConfig(BaseModel):
    title: str = "📐 考研数学题目整理 Agent"
    port: int = 7860
    theme: str = "soft"
    host: str = "0.0.0.0"


class PipelineConfig(BaseModel):
    """Pipeline concurrency and mode settings."""
    max_concurrency: int = Field(default=3, ge=1, le=8, description="最大并发LLM请求数")
    auto_mode: bool = Field(default=False, description="全自动模式 — 跳过等待直接进入审核（已废弃，见 Redis 中的 auto_ocr/auto_llm）")


class Settings(BaseModel):
    """Top-level settings model matching config/settings.yml"""
    ocr: OcrConfig = Field(default_factory=OcrConfig)
    llm: LlmConfig = Field(default_factory=LlmConfig)
    paths: PathsConfig = Field(default_factory=PathsConfig)
    gui: GUIConfig = Field(default_factory=GUIConfig)
    pipeline: PipelineConfig = Field(default_factory=PipelineConfig)


# ── Queue Models ──────────────────────────────────────────────────────────────

from enum import Enum as _Enum


class QueueStatus(str, _Enum):
    """Status of a single item in the processing queue."""
    IDLE = "idle"
    OCR_QUEUED = "ocr_queued"
    OCR_RUNNING = "ocr_running"
    OCR_DONE = "ocr_done"
    LLM_QUEUED = "llm_queued"
    LLM_RUNNING = "llm_running"
    LLM_DONE = "llm_done"
    WAITING_REVIEW = "waiting_review"
    ACCEPTED = "accepted"
    ARCHIVED = "archived"
    SKIPPED = "skipped"
    DELETED = "deleted"
    ERROR_OCR = "error_ocr"
    ERROR_LLM = "error_llm"
    ERROR_ARCHIVE = "error_archive"


class QueueItem(BaseModel):
    """A single item in the batch processing queue."""
    id: int = Field(description="Queue index (0-based)")
    status: QueueStatus = Field(default=QueueStatus.IDLE)
    image_paths: list[str] = Field(default_factory=list, description="Original image file paths (may be multiple per problem)")
    ocr_text: str = Field(default="", description="OCR result text")
    user_notes: str = Field(default="", description="Manual notes added by user")
    record: Optional[ProblemRecord] = Field(default=None, description="LLM structured result")
    filename: str = Field(default="", description="Generated MD filename")
    archive_result: Optional[dict] = Field(default=None, description="Archive engine result")
    error_msg: str = Field(default="", description="Error message if failed")
