# 📐 Math Organizer

[![Python](https://img.shields.io/badge/Python-3.12+-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Docker](https://img.shields.io/badge/Docker-ready-2496ED?logo=docker&logoColor=white)](Dockerfile)

[中文版](README.zh-CN.md)

> Smart knowledge-base builder for graduate math exam prep — OCR → LLM → Obsidian vault, fully automated.

**Math Organizer** turns screenshots of math problems into a structured, searchable [Obsidian](https://obsidian.md/) vault. Snap a screenshot, paste it (Ctrl+V), and the pipeline does the rest: OCR recognition, LLM-powered classification & solution extraction, then archival into a clean Markdown knowledge base with LaTeX rendering and OPD (Objective–Plan–Detail) solution annotations.

## 🎯 What It Does

```
Screenshot → PaddleOCR → DeepSeek LLM → Human Review → Obsidian Vault
```

- **OCR** — [PaddleOCR VL-1.6](https://www.paddlepaddle.org.cn/en) extracts text & formulas from images
- **LLM** — [DeepSeek v4-pro](https://www.deepseek.com/) classifies topics, extracts solutions, and annotates key insights via tool-calling
- **Vault** — Generates an Obsidian-compatible folder structure with Jinja2 templates, MOC index pages, and linked assets

## ✨ Features

| Feature | Detail |
|---------|--------|
| 📸 **Screenshot → Vault** | End-to-end: paste screenshot, get a formatted Markdown problem entry |
| 🏷️ **Auto-Classification** | 3 subjects × 36 lectures × question types, driven by a configurable knowledge tree |
| 💡 **OPD Solution Method** | Objective–Plan–Detail structured solutions with `key_insight` highlights |
| 🧮 **LaTeX Rendering** | Full math formula support, rendered in Obsidian natively |
| ⚡ **4 Auto Modes** | Auto-add, auto-OCR, auto-LLM, auto-archive — toggle individually or go fully hands-off |
| 📋 **Review Panel** | Adjust subject/lecture/type/OPD before accepting — or skip/reprocess/delete |
| 📂 **Vault Browser** | Collapsible tree view, click-to-read, in-app delete |
| 📦 **ZIP Export** | One-click download of the entire vault |
| 🐳 **Docker** | Build once, run anywhere — config & vault mounted externally |
| ⌨️ **Ctrl+V Paste** | Clipboard screenshot directly into the queue |

## 🚀 Quick Start

### Prerequisites

- Python 3.12+ (conda environment recommended)
- PaddleOCR API key ([get one here](https://www.paddlepaddle.org.cn/en))
- DeepSeek API key ([get one here](https://platform.deepseek.com/))

### Install

```bash
git clone https://github.com/Eileeeeeeeeeeeen/math-organizer.git
cd math-organizer

# Create conda env
conda create -n math-organizer python=3.12 -y
conda activate math-organizer
pip install -r requirements.txt

# Copy the config template and fill in your API keys
cp config/settings.example.yml config/settings.yml
# Edit config/settings.yml with your API keys, then run:
PYTHONPATH=. python gui/app.py
```

Open `http://localhost:7880` — the Gradio UI loads in your browser.

### Docker

```bash
# Copy config template and edit with your API keys
cp config/settings.example.yml config/settings.yml
# Then edit settings.yml, then:
HOST_UID=$(id -u) HOST_GID=$(id -g) docker compose up -d
```

## 🧪 Tests

```bash
# Unit tests (128 tests, < 3s, no API keys needed)
PYTHONPATH=. python -m pytest tests/ -q -m "not integration"

# Integration tests (requires valid API keys)
PYTHONPATH=. python -m pytest tests/ -q -m integration -s
```

## 🏗️ Architecture

```
┌──────────────────────────────────────────────┐
│  Gradio GUI (gui/app.py)                     │
│  Thin UI layer, JS bridge for queue & paste  │
└──────────────┬───────────────────────────────┘
               │ in-process calls
┌──────────────▼───────────────────────────────┐
│  Backend Engine (backend/engine.py)          │
│  Queue state machine, auto-mode orchestrator │
│  ThreadPoolExecutor (max 5 workers)          │
└──────────────┬───────────────────────────────┘
               │
┌──────────────▼───────────────────────────────┐
│  Pipeline (src/pipeline.py)                  │
│  OCR job submission + polling                │
│  LLM structured output via tool-calling      │
└──────────────┬───────────────────────────────┘
               │
┌──────────────▼───────────────────────────────┐
│  Archive Engine (src/archive.py)             │
│  Jinja2 MD rendering, MOC index maintenance  │
│  Directory creation, asset management        │
└──────────────────────────────────────────────┘
```

**Key design decisions:**
- Single-process desktop app — no Redis, Celery, or FastAPI
- `ThreadPoolExecutor` for all async work (OCR, LLM, archive)
- API keys in `config/settings.yml` — no env var dependencies
- Fully in-memory queue (restart = fresh start)

## 📁 Vault Structure

```
考研数学题库/
├── _index.md                  # Master MOC index
├── 高等数学/
│   ├── _index.md              # Subject MOC
│   ├── 第1讲_函数与极限/
│   │   ├── _index.md          # Lecture MOC
│   │   ├── 选择题/
│   │   │   └── 2024-数学一-第3题.md
│   │   └── 解答题/
│   │       └── ...
│   └── ...
├── 线性代数/
└── 概率论与数理统计/
```

Each problem file includes YAML frontmatter (subject, lecture, type, OPD tags) + solution body with LaTeX — ready for Obsidian.

## ⚠️ Known Limitations

| Limitation | Reason |
|------------|--------|
| DeepSeek-only LLM | Provider is hardcoded |
| No auth / multi-user | Designed as a single-user desktop tool |
| In-memory queue | Restarting the app loses the queue |
| Clipboard button unavailable | Browser security model; use Ctrl+V |

## 📄 License

MIT — see [LICENSE](LICENSE) for details.
