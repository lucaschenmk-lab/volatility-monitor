# 使用轻量级 Python 镜像
FROM python:3.11-slim

WORKDIR /app

# 安装依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制代码
COPY monitor_core.py .
COPY monitor_server.py .

# 健康检查
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s \
  CMD python3 -c "import urllib.request; urllib.request.urlopen('http://localhost:$PORT/api/data')"

# 启动命令
ENV HOST=0.0.0.0
ENV PORT=8080
EXPOSE 8080
CMD ["python3", "-W", "ignore", "monitor_server.py"]
