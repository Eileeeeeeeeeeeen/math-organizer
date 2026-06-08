# Math Organizer — 考研数学题目智能整理 Agent
# 单进程架构，无需 Redis/Celery/FastAPI
FROM python:3.12-slim

WORKDIR /app

# ── 安装系统依赖 ──
# （python:3.12-slim 已包含所需的一切，无需额外 apt-get）

# ── 安装 Python 依赖 ──
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ── 复制应用代码 ──
COPY src/ src/
COPY backend/ backend/
COPY gui/ gui/
COPY templates/ templates/
COPY pyproject.toml .
COPY tests/ tests/

# ── 创建运行时挂载点 ──
# config/ → 挂载宿主机 config/（含 API key）
# 考研数学题库/ → 挂载宿主机 vault（用户数据）
RUN mkdir -p /app/config /app/考研数学题库

ENV PYTHONPATH=/app
EXPOSE 7880

CMD ["python", "gui/app.py"]
