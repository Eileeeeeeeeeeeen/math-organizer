# Math Organizer — 考研数学题目智能整理 Agent

## 项目概述

将考研数学题目截图通过 OCR + LLM 智能整理为 Obsidian 兼容的 Markdown 题库文件，支持自动分类、OPD 解题方法论标注、LaTeX 公式渲染。

**核心流程**：截图 → OCR (PaddleOCR) → LLM 整理 (DeepSeek) → 人工审核 → 归档入 Obsidian 题库

## Quick Start

```bash
# 单命令启动（无需 Redis/Celery/FastAPI）
PYTHONPATH=. conda run -n math-organizer python gui/app.py

# 运行测试（128 单元测试，< 3s）
PYTHONPATH=. conda run -n math-organizer python -m pytest tests/ -q -m "not integration"

# 集成测试（需要真实 API keys）
PYTHONPATH=. conda run -n math-organizer python -m pytest tests/ -q -m integration -s
```

## Architecture（单进程）

```
┌─────────────────────────────────────────────────┐
│  Gradio GUI (gui/app.py)                         │
│  - 薄 UI 层，Handler 直接调用 Backend               │
│  - gr.Number(every=1.5) 轮询刷新队列               │
│  - JS Bridge: queue 点击选择/翻页/粘贴板            │
└──────────────┬──────────────────────────────────┘
               │ 直接 Python 调用（同进程）
┌──────────────▼──────────────────────────────────┐
│  Backend (backend/engine.py)                     │
│  - _queue: list[QueueItem] + threading.RLock     │
│  - ThreadPoolExecutor 异步执行 OCR/LLM/Archive   │
│  - Auto modes: auto_ocr, auto_llm, auto_add,     │
│    auto_archive (独立开关)                        │
│  - 翻页: _queue_page, page_size=10               │
│  - 题库管理: create_vault_zip(), delete_from_vault│
└──────────────┬──────────────────────────────────┘
               │ 直接 Python 调用
┌──────────────▼──────────────────────────────────┐
│  Pipeline (src/pipeline.py)                      │
│  - OCR: PaddleOCR VL-1.6 API (job submit + poll) │
│  - LLM: DeepSeek v4-pro API (tool calling)       │
│  - ThreadPoolExecutor 并发 (cap: 5)              │
│  - _safe_json_loads(): LaTeX 反斜杠修复          │
│  - {"input": {...}} 自动解包                      │
└──────────────┬──────────────────────────────────┘
               │
┌──────────────▼──────────────────────────────────┐
│  ArchiveEngine (src/archive.py)                  │
│  - Jinja2 MD 渲染 (templates/md_template.j2)     │
│  - 目录自动创建 (subject/lecture/question_type)    │
│  - _index.md MOC 索引维护                        │
│  - 图片 assets 管理 + 删除                        │
│  - 题库树扫描 (get_vault_tree)                    │
└─────────────────────────────────────────────────┘
```

## Directory Structure

```
math-organizer/
├── gui/
│   └── app.py              # Gradio UI (~840 行)
├── backend/
│   └── engine.py           # Backend 引擎 (~620 行)
├── src/
│   ├── models.py           # Pydantic 数据模型
│   ├── config.py           # YAML 配置加载
│   ├── pipeline.py         # OCR + LLM 流水线 (~700 行)
│   ├── archive.py          # MD 渲染 + 题库文件管理 (~410 行)
│   └── validators/
│       ├── knowledge_tree_validator.py
│       ├── opd_validator.py
│       ├── naming_validator.py
│       ├── frontmatter_validator.py
│       ├── directory_validator.py
│       └── dedup.py
├── config/
│   ├── settings.yml        # API keys + 全局配置
│   ├── knowledge_tree.yml  # 3 科 × 36 讲次
│   └── opd_markers.yml     # O(30) P(11) D(16)
├── templates/
│   ├── LLM 输出 JSON Schema.json
│   └── md_template.j2
├── tests/                  # 128 单元测试（8 个测试文件）
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── CLAUDE.md
└── 考研数学题库/       # 用户数据（归档输出）
```

## 功能完成情况

### ✅ 已完成

| 功能 | 说明 |
|------|------|
| OCR 识别 | PaddleOCR VL-1.6 API，异步提交+轮询 |
| LLM 整理 | DeepSeek v4-pro Tool Calling，结构化 JSON 输出 |
| 多图片支持 | QueueItem.image_paths: list[str] |
| 队列管理 | 增删查改、状态机跟踪 |
| 自动 OCR | 开关控制，添加图片后自动 OCR |
| 自动 LLM | 开关控制，OCR 完成后自动 LLM |
| 自动入队 | 开关控制，选文件后自动添加 |
| 自动归档 | 开关控制，LLM 完成后直接入库（跳过审核）|
| 队列点击选择 | JS Bridge: Object.getOwnPropertyDescriptor + InputEvent |
| 队列翻页 | 10 条/页，上下页导航 |
| 审核面板 | 科目/讲次/题型/OPD 调整 + 通过/跳过/重做/删除 |
| OCR 校对 | 源码编辑 + Markdown 预览 |
| MD 预览 | LaTeX 渲染预览 |
| 题库浏览 | 可折叠目录树 + 点击查看 + 删除 |
| 题库下载 | ZIP 打包下载 |
| 队列清空 | 一键清空 |
| Ctrl+V 粘贴 | 粘贴板截图直接入队 |
| LLM JSON 修复 | LaTeX 反斜杠转义、{"input":{}} 解包 |
| key_insight 字段 | 解题关键点标注 |
| OPD 解题方法论 | 目标/思路/细节三级标注 |
| 重复检测 | 文件名冲突检测 |
| Docker 部署 | Dockerfile + compose |
| 单元测试 | 128 个，< 3s |

### ⏳ 待实施

| 功能 | 说明 |
|------|------|
| vault_index.json | 持久化题库索引 |
| Windows exe 打包 | PyInstaller 打包方案（需要 `__file__` → `get_bundle_path()` 改造）|
| 队列上限/清理 | 避免队列无限增长 |

### ❌ 已知限制

| 限制 | 原因 |
|------|------|
| 粘贴按钮不可用 | 浏览器安全策略阻止 `navigator.clipboard.read()` 和 `execCommand('paste')`，仅 Ctrl+V 可用 |
| 仅支持 DeepSeek API | LLM provider 硬编码 |
| 无用户认证 | 单用户桌面工具 |
| 进程重启丢失队列 | 内存队列，无持久化 |
| 无并发上传限制 | 大量图片可能占满 ThreadPoolExecutor |

## Queue State Machine

```
idle → ocr_running → ocr_done → llm_running → llm_done → waiting_review
                                                              │
                              ┌────────────────────────────────┼──────────────────────────────┐
                              ▼                                ▼                              ▼
                          accepted → archived              skipped                      llm_queued (reprocess)
                              │
                              ▼
                          deleted (手动删除)
```

错误状态：error_ocr / error_llm / error_archive

## Auto Pipeline Modes

4 个独立开关（默认值）：
```
📥 自动入队 (OFF)  → 选择文件后自动添加到队列
🔍 自动 OCR (ON)   → 添加图片后自动开始 OCR
🤖 自动 LLM (ON)   → OCR 完成后自动进行 LLM 整理
💾 自动归档 (OFF)  → LLM 完成后直接入库，跳过审核
```

全自动流（4 个全开）：截图 → Ctrl+V → OCR → LLM → 归档 → 题库。无需任何点击。

## 关键设计决策

- **无 exam_scope、无 difficulty 字段** — 从所有层移除
- **key_insight 无长度限制** — LLM 自由输出
- **solution.approach 无长度限制** — 修复了 DeepSeek 超 200 字报错
- **无 Redis / Celery / FastAPI** — 纯 Python 桌面应用，ThreadPoolExecutor 搞定一切
- **API keys 在 config/settings.yml** — 不设环境变量依赖
- **并发上限 5** — ThreadPoolExecutor max_workers=5

## Deployment Options

### 1. 原生 Python（开发/测试）
```bash
conda activate math-organizer
PYTHONPATH=. python gui/app.py
```
端口: 7880

### 2. Docker（生产）
```bash
./docker-start.sh          # 一键启动
docker compose logs -f     # 查看日志
docker compose down        # 停止
```
config/ 和 vault/ 外部挂载，代码内置镜像。

### 3. Windows exe（待实施）
PyInstaller 打包为独立 .exe。需先改造 `__file__` 路径为 `get_bundle_path()`（适配 `sys._MEIPASS`）。

## Recent Changes (2026-06-08)

### Bug 修复
- **自动入队反馈循环**: `handle_file_change` 返回 `None` 清空 `queue_html` → 改用 `gr.skip()`
- **自动归档永不触发**: status 先改为 WAITING_REVIEW 后检查 LLM_DONE，条件永为 False → 提前判断
- **LLM approach 超长**: `max_length=200` 限制导致 Pydantic 验证失败 → 移除限制
- **粘贴按钮不可用**: 浏览器阻止 Clipboard API → 移除按钮，保留 Ctrl+V + 提示文本
- **LLM key_insight 超长**: `max_length=80` → 移除
- **LLM JSON 非法 \\escape**: `\\s`/`\\p`/`\\u` → `_safe_json_loads()` 正则修复
- **LLM {"input": {}} 嵌套**: → 自动解包常见 wrapper key
- **下载按钮无响应**: `outputs=[]` → `outputs=[download_btn]`
- **队列点击无效**: `dispatchEvent(new Event('input'))` → `Object.getOwnPropertyDescriptor` + `InputEvent`

### 功能新增
- Ctrl+V 粘贴图片入队（paste 事件监听 + base64 bridge）
- 自动入队 / 自动归档 两个新开关
- 队列翻页（10 条/页）
- 题库浏览器（折叠树 + 点击查看 + 删除）
- 📦 下载题库 ZIP
- ❌ 错误输出到终端（3 个 except 块）

## Environment

- Python 3.12.13 (conda: `math-organizer`)
- 核心依赖: gradio 6.16, pydantic 2.13, jinja2 3.1, pyyaml 6.*, requests 2.*
- 开发依赖: pytest 9.0, pytest-cov 7.1
- 外部 API: PaddleOCR VL-1.6, DeepSeek v4-pro
- 端口: 7880

## Git Commit 署名

所有 git commit message 末尾使用：
Co-Authored-By: DeepSeek v4-pro <noreply@deepseek.com>

## Memory Files

项目记忆存储在 `/home/eileen/.claude/projects/-home-eileen-DockerFiles-math-organizer/memory/`:
- [[math-organizer-project]] — 当前架构
- [[over-engineering-lesson]] — 拒绝 Redis+Celery 的教训
- [[gui-bug-fixes]] — 10 个已修复 Bug
- [[user-preferences]] — 用户偏好
- [[docker-packaging-plan]] — Docker 已完成
- [[vault-index-plan]] — 待实施功能
- [[clipboard-paste-approach]] — 粘贴板方案总结
