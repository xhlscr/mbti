# syntax=docker/dockerfile:1
# 与本地 venv 保持一致：Python 3.13
FROM python:3.13-slim-bookworm
LABEL org.opencontainers.image.title="mbti-api" \
      org.opencontainers.image.description="MBTI 测试站后端（FastAPI）" \
      org.opencontainers.image.licenses="MIT"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TZ=Asia/Shanghai

WORKDIR /srv/app

# slim 镜像默认 UTC 且没有 tzdata，只设 TZ 不生效，必须装
RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata ca-certificates \
    && ln -sf /usr/share/zoneinfo/Asia/Shanghai /etc/localtime \
    && echo "Asia/Shanghai" > /etc/timezone \
    && rm -rf /var/lib/apt/lists/*

# 依赖层单独缓存：只改代码不会触发重装
COPY requirements.txt ./
RUN pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/

# 非 root 运行
RUN useradd --create-home --uid 10001 appuser

COPY --chown=appuser:appuser app ./app
COPY --chown=appuser:appuser scripts ./scripts

USER appuser

EXPOSE 8000

# 探活：3 秒超时，避免探针本身挂住
HEALTHCHECK --interval=30s --timeout=5s --start-period=45s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=3).status==200 else 1)"

# --workers 2：两个进程各有一份内存态限流计数器（app/api/deps.py），
# 实际每 IP 上限约为配置值的 2 倍（40 次/小时）。这是当前接受的取舍；
# 需要严格限流时改成 1，或把计数器挪到 Redis。
# 首次启动两个 worker 会并发建表/播种，IF NOT EXISTS 能兜住，
# 其中一个可能各打一条 WARNING，属正常噪音。
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", \
     "--workers", "2", "--proxy-headers", "--forwarded-allow-ips", "*"]
