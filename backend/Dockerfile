# ---------------------------------------------------------------------------
# 离散制造车间生产管理系统 —— 后端 + 前端一体化镜像
#
# 多阶段构建：
#   阶段 1（node:22-alpine）  构建 Vue3 + Vite 前端，产出 frontend/dist
#   阶段 2（python:3.12-slim）安装后端依赖，并把前端产物一起打包
#
# 构建上下文必须是**仓库根目录**（docker-compose.yml 已配置）：
#   docker build -f backend/Dockerfile -t discrete-mes-api .
# ---------------------------------------------------------------------------

# ============================ 阶段 1：构建前端 ============================
FROM node:22-alpine AS frontend-builder

WORKDIR /web

# 先只拷贝依赖清单，最大化利用 Docker 层缓存
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund --registry=https://registry.npmmirror.com

COPY frontend/ ./
RUN npm run build


# ============================ 阶段 2：运行后端 ============================
FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app/backend \
    TZ=Asia/Shanghai

WORKDIR /app

# 依赖单独一层，源码变更时无需重装依赖
COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/requirements.txt \
        -i https://pypi.tuna.tsinghua.edu.cn/simple

COPY backend/ /app/backend/

# 前端产物：Vite 构建结果（首选）+ 免构建演示版（回退）
COPY --from=frontend-builder /web/dist /app/frontend/dist
COPY frontend/standalone /app/frontend/standalone

# SQLite 兜底模式下的数据目录（MySQL 模式不使用）
RUN mkdir -p /app/data

WORKDIR /app/backend

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=25s --retries=5 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4).status == 200 else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
