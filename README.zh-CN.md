# 📐 考研数学题目智能整理 Agent

[![Python](https://img.shields.io/badge/Python-3.12+-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Docker](https://img.shields.io/badge/Docker-ready-2496ED?logo=docker&logoColor=white)](Dockerfile)

[English](README.md)

> 截图 → OCR → LLM → Obsidian 题库，全流程自动化的考研数学题目整理工具。

**Math Organizer** 将考研数学题目截图转化为结构化、可检索的 [Obsidian](https://obsidian.md/) 知识库。截图、粘贴（Ctrl+V），流水线自动完成剩余工作：OCR 识别、LLM 分类与解答提取，然后归档为带有 LaTeX 公式渲染和 OPD（目标-思路-细节）解题方法论标注的 Markdown 文件。

## 🎯 工作流程

```
截图 → PaddleOCR → DeepSeek LLM → 人工审核 → Obsidian 题库
```

- **OCR** — [PaddleOCR VL-1.6](https://www.paddlepaddle.org.cn/) 从图片中提取文字和公式
- **LLM** — [DeepSeek v4-pro](https://www.deepseek.com/) 通过 Tool Calling 进行题目分类、解答提取和关键点标注
- **题库** — 基于 Jinja2 模板生成 Obsidian 兼容的目录结构，含 MOC 索引和资源文件管理

## ✨ 功能特性

| 功能 | 说明 |
|------|------|
| 📸 **截图→题库** | 端到端：粘贴截图，获得格式化的 Markdown 题目文件 |
| 🏷️ **自动分类** | 3 科目 × 36 讲次 × 题型，由知识树配置驱动 |
| 💡 **OPD 解题法** | 目标-思路-细节三级标注 + `key_insight` 关键点 |
| 🧮 **LaTeX 渲染** | 完整数学公式支持，Obsidian 原生渲染 |
| ⚡ **4 种自动模式** | 自动入队/自动 OCR/自动 LLM/自动归档，可独立开关 |
| 📋 **审核面板** | 接受前调整科目/讲次/题型/OPD，或跳过/重做/删除 |
| 📂 **题库浏览** | 可折叠目录树，点击查看，应用内删除 |
| 📦 **ZIP 导出** | 一键下载完整题库 |
| 🐳 **Docker** | 一次构建，到处运行 — config 和 vault 外部挂载 |
| ⌨️ **Ctrl+V 粘贴** | 剪贴板截图直接入队 |

## 🚀 快速开始

### 环境要求

- Python 3.12+（推荐使用 conda 环境）
- PaddleOCR API key（[点此获取](https://www.paddlepaddle.org.cn/)）
- DeepSeek API key（[点此获取](https://platform.deepseek.com/)）

### 安装

```bash
git clone https://github.com/Eileeeeeeeeeeeen/math-organizer.git
cd math-organizer

# 创建 conda 环境
conda create -n math-organizer python=3.12 -y
conda activate math-organizer
pip install -r requirements.txt

# 复制配置模板并填入 API keys
cp config/settings.example.yml config/settings.yml
# 编辑 config/settings.yml 填入你的 API keys，然后运行：
PYTHONPATH=. python gui/app.py
```

打开浏览器访问 `http://localhost:7880`，即可看到 Gradio 界面。

### Docker 部署

```bash
# 先复制配置模板并编辑
cp config/settings.example.yml config/settings.yml
# 编辑 settings.yml 填入 API keys，然后：
HOST_UID=$(id -u) HOST_GID=$(id -g) docker compose up -d
```

## 🧪 测试

```bash
# 单元测试（无需 API keys）
PYTHONPATH=. python -m pytest tests/ -q -m "not integration"

# 集成测试（需要有效 API keys）
PYTHONPATH=. python -m pytest tests/ -q -m integration -s
```

## 🏗️ 架构

```
┌──────────────────────────────────────────────┐
│  Gradio GUI (gui/app.py)                     │
│  薄 UI 层，JS Bridge 处理队列选择和粘贴        │
└──────────────┬───────────────────────────────┘
               │ 同进程调用
┌──────────────▼───────────────────────────────┐
│  Backend 引擎 (backend/engine.py)            │
│  队列状态机，自动模式编排                     │
│  ThreadPoolExecutor（最大 5 线程）            │
└──────────────┬───────────────────────────────┘
               │
┌──────────────▼───────────────────────────────┐
│  流水线 (src/pipeline.py)                    │
│  OCR 作业提交 + 轮询                          │
│  LLM 结构化输出（Tool Calling）                │
└──────────────┬───────────────────────────────┘
               │
┌──────────────▼───────────────────────────────┐
│  归档引擎 (src/archive.py)                   │
│  Jinja2 MD 渲染，MOC 索引维护                 │
│  目录创建，资源文件管理                        │
└──────────────────────────────────────────────┘
```

**关键设计决策：**
- 单进程桌面应用 — 无需 Redis、Celery、FastAPI
- `ThreadPoolExecutor` 处理所有异步任务（OCR、LLM、归档）
- API keys 存放于 `config/settings.yml` — 不依赖环境变量
- 全内存队列（重启即清空）

## 📁 题库结构

```
考研数学题库/
├── _index.md                  # 主 MOC 索引
├── 高等数学/
│   ├── _index.md              # 科目 MOC
│   ├── 第1讲_函数与极限/
│   │   ├── _index.md          # 讲次 MOC
│   │   ├── 选择题/
│   │   │   └── 2024-数学一-第3题.md
│   │   └── 解答题/
│   │       └── ...
│   └── ...
├── 线性代数/
└── 概率论与数理统计/
```

每道题目的 Markdown 文件包含 YAML frontmatter（科目、讲次、题型、OPD 标签）+ LaTeX 解答正文，可直接在 Obsidian 中使用。

## ⚠️ 已知限制

| 限制 | 原因 |
|------|------|
| 仅支持 DeepSeek API | LLM provider 硬编码 |
| 无用户认证 | 定位为单用户桌面工具 |
| 内存队列 | 重启应用会丢失队列 |
| 粘贴按钮不可用 | 浏览器安全策略限制，请使用 Ctrl+V |

## 📄 许可证

MIT — 详见 [LICENSE](LICENSE)。
