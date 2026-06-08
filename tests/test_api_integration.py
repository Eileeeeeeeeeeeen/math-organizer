"""End-to-end API integration test.

Pipes a test problem image through the full pipeline:
  1. PaddleOCR VL-1.6 API → OCR → Markdown with LaTeX
  2. DeepSeek v4-pro API → structured JSON (Tool Call with JSON Schema)
  3. Validate output against Pydantic models & frontmatter rules
"""

from __future__ import annotations

import base64
import json
import os
import re
from datetime import date
from pathlib import Path

import pytest
import requests
import yaml

from src.models import ProblemRecord, Frontmatter
from src.validators.frontmatter_validator import validate_frontmatter
from src.validators.naming_validator import generate_filename, validate_filename
from src.validators.dedup import compute_problem_hash

# ── API credentials loaded from config/settings.yml ──
from src.config import load_settings as _load_settings
_settings = _load_settings()
PADDLEOCR_API_KEY = _settings.ocr.api_key
DEEPSEEK_API_KEY = _settings.llm.api_key
PADDLEOCR_JOB_URL = _settings.ocr.api_endpoint
PADDLEOCR_MODEL = _settings.ocr.model
DEEPSEEK_URL = f"{_settings.llm.api_base}/chat/completions"

# ── Paths ──
PROJECT_ROOT = Path(__file__).resolve().parent.parent
TEST_IMAGE = Path(__file__).resolve().parent / "test1.png"
CONFIG_DIR = PROJECT_ROOT / "config"
OUTPUT_DIR = Path(__file__).resolve().parent / "output"


def load_json_schema() -> dict:
    """Load the LLM output JSON Schema from template/."""
    schema_path = PROJECT_ROOT / "templates" / "LLM 输出 JSON Schema.json"
    with open(schema_path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_knowledge_tree_text() -> str:
    """Load knowledge_tree.yml as text for the system prompt."""
    kt_path = CONFIG_DIR / "knowledge_tree.yml"
    with open(kt_path, "r", encoding="utf-8") as f:
        return f.read()


def load_opd_markers_text() -> str:
    """Load opd_markers.yml as text for the system prompt."""
    opd_path = CONFIG_DIR / "opd_markers.yml"
    with open(opd_path, "r", encoding="utf-8") as f:
        return f.read()


def build_system_prompt() -> str:
    """Build the full system prompt with knowledge tree + OPD markers."""
    knowledge_tree = load_knowledge_tree_text()
    opd_markers = load_opd_markers_text()

    return f"""你是考研数学辅导专家，精通考研数学知识体系。你的任务是将用户提供的数学题目整理为结构化的 JSON 格式。

## 知识体系（只能从中选择知识点）

{knowledge_tree}

## 解题方法论（OPD）记号体系（只能从中选择 O/P/D 代码）

{opd_markers}

## 输出要求

1. 使用 organize_math_problem 函数输出结构化 JSON
2. 所有数学公式必须使用 LaTeX 格式
3. subject 必须从 [高等数学, 线性代数, 概率统计] 中选择
4. lecture 必须从知识体系中的讲次名称中选择（如"第1讲_函数极限与连续"）
5. question_type 必须从 [选择题, 填空题, 解答题] 中选择
6. OPD 标记只能从上述记号体系中选择
7. key_ability 从 [概念辨析, 计算能力, 证明推理, 综合应用] 中选择
8. solution.approach 不超过 200 字
9. solution.key_insight 不超过 80 字，直截了当指出该题的核心关键
10. 解题步骤清晰，每步一个字符串元素"""


# ── Phase 1: OCR ────────────────────────────────────────────────────────────


def call_paddleocr(image_path: Path) -> str:
    """Send image to PaddleOCR VL-1.6 API (v2 job-based), return Markdown text.

    Flow (from template/paddleAPI.py):
      1. POST job with multipart form data (file upload, NOT base64)
      2. Poll GET {JOB_URL}/{jobId} until state == "done"
      3. Download JSONL result, extract layoutParsingResults[0].markdown.text

    Auth: "bearer {TOKEN}" (lowercase, per official template)

    Returns:
        OCR result as Markdown string (may contain LaTeX formulas).
    """
    import time

    print(f"\n📷 Phase 1: OCR — sending {image_path.name} to PaddleOCR VL-1.6 API...")

    headers = {
        "Authorization": f"bearer {PADDLEOCR_API_KEY}",
    }

    optional_payload = {
        "useDocOrientationClassify": False,
        "useDocUnwarping": False,
        "useChartRecognition": False,
    }

    # ── Step 1: Submit job with multipart file upload (NOT base64 JSON) ──
    data = {
        "model": PADDLEOCR_MODEL,
        "optionalPayload": json.dumps(optional_payload),
    }

    with open(image_path, "rb") as f:
        files = {"file": f}
        print(f"  POST {PADDLEOCR_JOB_URL} (multipart upload)")
        response = requests.post(
            PADDLEOCR_JOB_URL,
            headers=headers,
            data=data,
            files=files,
            timeout=60,
        )

    print(f"  Status: {response.status_code}")

    if response.status_code != 200:
        error_body = response.text[:800]
        raise RuntimeError(
            f"PaddleOCR job submission failed (HTTP {response.status_code}):\n{error_body}"
        )

    resp_json = response.json()
    job_id = resp_json["data"]["jobId"]
    print(f"  Job ID: {job_id}")

    # ── Step 2: Poll for completion ──
    poll_url = f"{PADDLEOCR_JOB_URL}/{job_id}"
    for attempt in range(60):  # Up to 5 min
        time.sleep(5)
        poll_resp = requests.get(poll_url, headers=headers, timeout=30)
        if poll_resp.status_code != 200:
            print(f"  Poll {attempt+1}: HTTP {poll_resp.status_code}")
            continue

        poll_data = poll_resp.json()
        state = poll_data["data"]["state"]
        print(f"  Poll {attempt+1}: state={state}")

        if state == "done":
            jsonl_url = poll_data["data"]["resultUrl"]["jsonUrl"]
            print(f"  Done! Downloading result from JSONL...")
            break
        elif state == "failed":
            error_msg = poll_data["data"].get("errorMsg", "Unknown error")
            raise RuntimeError(f"OCR job failed: {error_msg}")
        elif state in ("pending", "running"):
            continue
        else:
            raise RuntimeError(f"Unknown job state: {state}")
    else:
        raise RuntimeError(f"OCR job {job_id} timed out after 5 minutes")

    # ── Step 3: Download and parse JSONL result ──
    jsonl_resp = requests.get(jsonl_url, timeout=60)
    jsonl_resp.raise_for_status()

    # JSONL: one JSON object per line (per page)
    lines = jsonl_resp.text.strip().split("\n")
    markdown_parts = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        page_result = json.loads(line)
        layout_results = page_result["result"]["layoutParsingResults"]
        for lr in layout_results:
            md_text = lr["markdown"]["text"]
            if md_text:
                markdown_parts.append(md_text)

    markdown_text = "\n\n".join(markdown_parts)
    print(f"  OCR text preview: {markdown_text[:200]}...")
    return markdown_text


def _extract_markdown_from_ocr_response(result: dict) -> str:
    """Extract Markdown text from various PaddleOCR API response formats."""
    # Format 1: Standard PaddleOCR cloud API
    if "data" in result and isinstance(result["data"], dict):
        data = result["data"]
        if "text" in data:
            return data["text"]
        if "markdown" in data:
            return data["markdown"]

    # Format 2: layoutParsingResults (self-hosted format)
    if "result" in result:
        r = result["result"]
        if "layoutParsingResults" in r and len(r["layoutParsingResults"]) > 0:
            lpr = r["layoutParsingResults"][0]
            if "markdown" in lpr and "text" in lpr["markdown"]:
                return lpr["markdown"]["text"]

    # Format 3: Direct text/markdown field
    if "text" in result:
        return result["text"]
    if "markdown" in result:
        return result["markdown"]

    # Format 4: result is a string
    if isinstance(result, str):
        return result

    # Last resort: return raw JSON so we can debug
    return json.dumps(result, ensure_ascii=False, indent=2)


# ── Phase 2: LLM Structuring ────────────────────────────────────────────────


def call_deepseek(ocr_text: str) -> dict:
    """Send OCR text to DeepSeek v4-pro, get structured JSON via Tool Call.

    Returns:
        Parsed JSON dict matching the ProblemRecord schema.
    """
    print("\n🤖 Phase 2: LLM — sending to DeepSeek v4-pro with Tool Call...")

    json_schema = load_json_schema()
    system_prompt = build_system_prompt()

    # Convert JSON Schema to the OpenAI Tool format
    # Remove $schema key which is not needed
    tool_parameters = {k: v for k, v in json_schema.items() if k != "$schema"}

    payload = {
        "model": "deepseek-v4-pro",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"请整理以下考研数学题目：\n\n{ocr_text}"},
        ],
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": "organize_math_problem",
                    "description": "整理考研数学题目，输出结构化 JSON",
                    "parameters": tool_parameters,
                },
            }
        ],
        # Note: DeepSeek thinking mode doesn't support tool_choice at all.
        # Without tool_choice the model naturally calls the only available tool.
        "reasoning_effort": "high",
        "temperature": 0.1,
    }

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
    }

    response = requests.post(
        DEEPSEEK_URL,
        json=payload,
        headers=headers,
        timeout=120,
    )

    print(f"  Status: {response.status_code}")

    if response.status_code != 200:
        raise RuntimeError(
            f"DeepSeek API failed with status {response.status_code}:\n"
            f"{response.text[:500]}"
        )

    result = response.json()
    _print_usage(result)

    # Extract the tool call response
    choice = result["choices"][0]
    message = choice["message"]

    # Check for tool_calls
    if "tool_calls" in message and len(message["tool_calls"]) > 0:
        tool_call = message["tool_calls"][0]
        json_str = tool_call["function"]["arguments"]
        parsed = json.loads(json_str)
        print(f"  Tool call succeeded, got {len(json.dumps(parsed, ensure_ascii=False))} chars of JSON")
        return parsed

    # Fallback: try to parse content as JSON
    content = message.get("content", "")
    if content:
        # Try to extract JSON from markdown code block
        json_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", content, re.DOTALL)
        if json_match:
            return json.loads(json_match.group(1))
        # Try direct parse
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            pass

    raise RuntimeError(f"No tool call or parseable JSON in DeepSeek response")


def _print_usage(result: dict) -> None:
    """Print token usage from API response."""
    usage = result.get("usage", {})
    if usage:
        prompt_tokens = usage.get("prompt_tokens", 0)
        completion_tokens = usage.get("completion_tokens", 0)
        total = usage.get("total_tokens", 0)
        print(f"  Tokens: {prompt_tokens} prompt + {completion_tokens} completion = {total}")


# ── Phase 3: Validation ─────────────────────────────────────────────────────


def validate_llm_output(data: dict) -> ProblemRecord:
    """Validate the LLM JSON output against Pydantic models."""
    print("\n✅ Phase 3: Validation — checking against Pydantic models...")
    record = ProblemRecord(**data)
    print(f"  Subject: {record.meta.subject.value}")
    print(f"  Lecture: {record.meta.lecture}")
    print(f"  Type: {record.meta.question_type.value}")
    print(f"  OPD Target: {record.meta.opd.target}")
    print(f"  OPD Procedures: {record.meta.opd.procedures}")
    print(f"  OPD Details: {record.meta.opd.details}")
    print(f"  Key Abilities: {[a.value for a in record.meta.key_ability]}")
    print(f"  Approach: {record.solution.approach[:100]}...")
    print(f"  Steps: {len(record.solution.steps)} steps")
    return record


# ── Tests ────────────────────────────────────────────────────────────────────


@pytest.mark.integration
class TestPaddleOcrApi:
    """Test PaddleOCR VL-1.6 API integration."""

    def test_ocr_returns_markdown(self):
        """OCR should return non-empty markdown text."""
        if not TEST_IMAGE.exists():
            pytest.skip(f"Test image not found: {TEST_IMAGE}")
        text = call_paddleocr(TEST_IMAGE)
        assert text, "OCR returned empty text"
        assert len(text) > 5, f"OCR text too short: {text}"
        print(f"OCR SUCCESS: {len(text)} characters")


@pytest.mark.integration
class TestDeepSeekApi:
    """Test DeepSeek v4-pro API integration with Tool Calls."""

    def test_llm_returns_valid_json(self):
        """DeepSeek should return valid structured JSON."""
        if not TEST_IMAGE.exists():
            pytest.skip(f"Test image not found: {TEST_IMAGE}")
        # Use a sample math problem text
        sample_text = r"""设函数 $f(x) = \begin{cases} x^2\sin\frac{1}{x}, & x \neq 0 \\ 0, & x = 0 \end{cases}$，讨论 $f(x)$ 在 $x=0$ 处的连续性与可导性。"""
        result = call_deepseek(sample_text)
        assert result is not None
        assert "meta" in result
        assert "problem" in result
        assert "solution" in result


@pytest.mark.integration
class TestFullPipeline:
    """End-to-end test: image → OCR → LLM → validated MD."""

    def test_full_pipeline(self):
        """Run the full pipeline and validate every stage."""
        if not TEST_IMAGE.exists():
            pytest.skip(f"Test image not found: {TEST_IMAGE}")

        # Phase 1: OCR
        ocr_text = call_paddleocr(TEST_IMAGE)
        assert ocr_text, "OCR failed — no text returned"
        assert len(ocr_text) > 10, f"OCR text suspiciously short: {ocr_text}"

        # Phase 2: LLM structuring
        llm_output = call_deepseek(ocr_text)
        assert llm_output is not None, "LLM returned None"
        assert "meta" in llm_output, "LLM output missing 'meta'"
        assert "problem" in llm_output, "LLM output missing 'problem'"
        assert "solution" in llm_output, "LLM output missing 'solution'"

        # Phase 3: Pydantic validation
        record = validate_llm_output(llm_output)
        assert record.meta.subject.value in ("高等数学", "线性代数", "概率统计")

        # Phase 4: Generate filename & validate naming convention
        meta_dict = llm_output["meta"]
        filename = generate_filename(meta_dict, llm_output.get("problem", ""))
        name_result = validate_filename(filename)
        assert name_result["valid"], f"Generated filename invalid: {name_result['errors']}"
        print(f"\n📄 Filename: {filename}")

        # Phase 5: SHA256 hash for dedup
        problem_hash = compute_problem_hash(llm_output["problem"])
        print(f"🔑 SHA256: {problem_hash[:16]}...")

        # Phase 6: Save outputs
        OUTPUT_DIR.mkdir(exist_ok=True)
        _save_outputs(ocr_text, llm_output, filename, record)

        print("\n" + "=" * 60)
        print("🎉 Full pipeline SUCCESS!")
        print(f"   OCR: {len(ocr_text)} chars")
        print(f"   LLM: {record.meta.subject.value} / {record.meta.lecture}")
        print(f"   File: {filename}")
        print(f"   Validation: ALL PASSED")
        print("=" * 60)


def _save_outputs(
    ocr_text: str,
    llm_output: dict,
    filename: str,
    record: ProblemRecord,
) -> None:
    """Save pipeline outputs to the output directory."""
    # Save OCR result
    (OUTPUT_DIR / "ocr_result.md").write_text(ocr_text, encoding="utf-8")
    # Save LLM JSON
    (OUTPUT_DIR / "llm_output.json").write_text(
        json.dumps(llm_output, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # Build and save the final MD file with frontmatter
    md_content = _render_markdown(record, filename)
    (OUTPUT_DIR / filename).write_text(md_content, encoding="utf-8")

    print(f"\n📁 Outputs saved to: {OUTPUT_DIR}")
    for f in sorted(OUTPUT_DIR.iterdir()):
        if f.is_file():
            print(f"   - {f.name} ({f.stat().st_size} bytes)")


def _render_markdown(record: ProblemRecord, filename: str) -> str:
    """Render a ProblemRecord to the final Obsidian-compatible MD format."""
    meta = record.meta
    today = date.today().isoformat()

    # Build YAML frontmatter
    fm_lines = [
        "---",
        f"subject: {meta.subject.value}",
        f"lecture: {meta.lecture}",
        f"question_type: {meta.question_type.value}",
        f"opd_target: {meta.opd.target}",
        "opd_procedures:",
    ]
    for p in meta.opd.procedures:
        fm_lines.append(f"  - {p}")
    fm_lines.append("opd_details:")
    for d in meta.opd.details:
        fm_lines.append(f"  - {d}")
    fm_lines.append("key_ability:")
    for ka in meta.key_ability:
        fm_lines.append(f"  - {ka.value}")
    fm_lines.extend([
        f"source_book: {meta.source.book}",
        f"source_example: {meta.source.example_id}",
        f"source_year: \"{meta.source.year}\"",
        "tags:",
    ])
    for tag in meta.tags:
        fm_lines.append(f"  - {tag}")
    fm_lines.extend([
        f"summary: {record.solution.approach[:100]}",
        f"created: {today}",
        f"updated: {today}",
        "---",
    ])

    # Build Markdown body
    body_lines = [
        "",
        f"# 📐 {filename.replace('.md', '')}",
        "",
        "## ❓ 题目",
        "",
        record.problem,
        "",
        "## ✅ 答案",
        "",
        record.answer,
        "",
        "## 📝 解题思路",
        "",
        record.solution.approach,
        "",
        "## 🔑 解题关键",
        "",
        record.solution.key_insight,
        "",
        "## 🔍 解题过程",
        "",
    ]
    for i, step in enumerate(record.solution.steps, 1):
        body_lines.append(f"{i}. {step}")
    body_lines.append("")

    if record.related.knowledge_points:
        body_lines.append("## 🔗 相关知识点")
        body_lines.append("")
        for kp in record.related.knowledge_points:
            body_lines.append(f"- [[{kp}]]")
        body_lines.append("")

    return "\n".join(fm_lines) + "\n".join(body_lines)


# ── Run directly ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    print("=" * 60)
    print("🧪 Math Organizer — Full Pipeline Test")
    print("=" * 60)

    test = TestFullPipeline()
    try:
        test.test_full_pipeline()
    except Exception as e:
        print(f"\n❌ Pipeline FAILED: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
