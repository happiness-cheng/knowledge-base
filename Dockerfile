# 阶段 1: 编译前端
FROM node:20-alpine AS frontend-build
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# 阶段 2: Python 后端
FROM python:3.11-slim
WORKDIR /app

# 安装系统依赖（MySQL 客户端、jieba 需要的）
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc default-libmysqlclient-dev pkg-config \
    && rm -rf /var/lib/apt/lists/*

# 安装 Python 依赖
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# 复制后端代码
COPY backend/ ./

# 复制前端构建产物
COPY --from=frontend-build /app/frontend/dist ./frontend/dist

# 预加载 jieba 字典（避免首次请求延迟）
RUN python -c "import jieba; jieba.initialize()" 2>/dev/null || true

EXPOSE 8766

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8766", "--workers", "2"]
