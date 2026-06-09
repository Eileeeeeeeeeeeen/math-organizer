# Math Organizer — 科目通用题目智能整理 Agent
# 单进程架构，无需 Redis/Celery/FastAPI
# 科目由 config/subject.yml 控制，切换配置文件即可换科目
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
# config/ → 挂载宿主机 config/（含 API key + subject.yml）
# vault/ → 挂载宿主机题库目录（路径由 subject.yml 控制）
RUN mkdir -p /app/config /app/vault

ENV PYTHONPATH=/app
EXPOSE 7880

CMD ["python", "gui/app.py"]
