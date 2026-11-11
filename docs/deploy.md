# 后端发布说明

> 后端跑在 Docker 容器里，构建镜像即可，不需要在服务器上装 Python 依赖。
> 服务器整体流程（装 Docker、Nginx、HTTPS）见 [../../docs/deploy.md](../../docs/deploy.md)。

---

## 1. 镜像里有什么

`backend/Dockerfile` 做四件事：

```dockerfile
FROM python:3.12-slim                    # 1. 基础镜像
COPY requirements.txt ./                 # 2. 先装依赖（这层可缓存）
RUN pip install -r requirements.txt
COPY app ./app                           # 3. 复制代码（工作目录直接可导入）
COPY scripts ./scripts                   # 4. 复制运维脚本
CMD uvicorn app.main:app --host 0.0.0.0 --port 8000
```

**不带 `--reload`**（那是开发用的），容器内是单进程前台运行，靠 Docker 的 `restart: unless-stopped` 保活。

镜像里**不包含** `pyproject.toml`、`tests/`、`backend/.env`——依赖来自 `requirements.txt`，配置来自 compose 注入的环境变量。

---

## 2. 环境变量

由 `docker-compose.prod.yml` 注入，**不需要 `backend/.env`**（那是本地开发用的）。

| 变量 | 生产值 | 说明 |
|---|---|---|
| `MBTI_DATABASE_URL` | `postgresql+psycopg://mbti:${DB_PASSWORD}@db:5432/mbti` | 主机名是 `db`（容器网络），不是 localhost |
| `MBTI_SESSION_TTL_MINUTES` | `120` | 会话有效期 |
| `MBTI_PER_DIM` | `10` | 每维度抽题数 |
| `MBTI_RATE_LIMIT_PER_HOUR` | `20` | 每 IP 建会话上限 |
| `MBTI_CORS_ORIGINS` | 空 | 同域反代，不需要 CORS |
| `MBTI_DB_CONNECT_TIMEOUT` | `3` | 连不上库时快速失败 |
| `MBTI_DB_INIT_TIMEOUT_SECONDS` | `8` | 建表超时；超时只警告不阻塞启动 |

密码只出现在仓库根目录的 `.env` 里（`DB_PASSWORD=...`，权限 600，不进 git）。

---

## 3. 首次启动做了什么

```
容器启动
  ├─ 建 8 张表（create_all，幂等）
  ├─ 播种题库：80 题 → 版本 v1（已存在则跳过）
  └─ 开始监听 :8000
```

日志里能看到：

```
INFO:     数据库已就绪
INFO:     Application startup complete.
```

**如果数据库没起来**：打一条 `WARNING 数据库初始化跳过`，服务仍然启动（`/healthz` 可用），但答题接口返回 `503 database_unavailable`。这样排障时至少能访问健康检查。

> 也可以不用自动播种，手工导入 `backend/sql/01_schema.sql` + `02_seed.sql`，效果一样。

---

## 4. 发布

### 4.1 完整重建（改了代码）

```bash
ssh mbti@服务器
cd /srv/mbti
git pull
docker compose -f docker-compose.prod.yml up -d --build api
```

`--build` 会重新构建镜像，`-d` 后台运行。只重建 api，不动 db 和 web。

### 4.2 只更新题库（不改代码）

题目数据在 `app/data/questions.json` 里，有两种方式：

**方式 A：重新构建镜像**（`git pull` 后 `--build`），适合题目随代码一起提交的情况。

**方式 B：直接调发布脚本**（不重启服务）：

```bash
cd /srv/mbti
docker compose -f docker-compose.prod.yml exec api \
  python scripts/publish_bank.py --file app/data/questions.json --yes
```

方式 B 直接跑容器里的脚本，**不重启服务**，适合只换题目的场景。
前提是镜像里有 `scripts/`——`backend/Dockerfile` 已经 `COPY scripts ./scripts`。

`publish_bank` 会建**新版本**并归档旧版：已分享的结果链接不受影响（`result` 表存的是快照）。

---

## 5. 健康检查

```bash
curl -s http://127.0.0.1:8080/healthz
# {"status":"ok"}
```

| 返回 | 含义 |
|---|---|
| `200 {"status":"ok"}` | 进程活着（**不代表数据库通**） |
| `503 {"detail":"database_unavailable"}` | 进程活着但连不上 PG |
| 连不上 | 容器挂了，`docker compose ps` 看状态 |

真正验证业务是否可用：

```bash
curl -s -X POST http://127.0.0.1:8080/api/v1/sessions \
  -H 'content-type: application/json' -d '{"bank":"mbti-v1"}' | head -c 200
# 期望：40 道题，且没有 weights 字段
```

---

## 6. 日志与排障

```bash
# 实时
docker compose -f docker-compose.prod.yml logs -f api

# 最近 200 行
docker compose -f docker-compose.prod.yml logs --tail=200 api

# 进容器排查
docker compose -f docker-compose.prod.yml exec api sh
```

| 现象 | 原因 | 处理 |
|---|---|---|
| 启动即退出 | 依赖装错 / 端口占用 | `logs api` 看 traceback |
| `数据库初始化跳过` | PG 没起或密码错 | `ps` 看 db 是否 healthy；核对 `.env` 的 `DB_PASSWORD` |
| 接口 503 | 同上 | 同上 |
| 接口 500 | 业务异常 | 看日志堆栈；`detail` 字段会给错误码 |
| 镜像构建很慢 | 每次都重装依赖 | 先 COPY `pyproject.toml` 再 COPY 代码（Dockerfile 已这样分层） |
| 容器内存涨 | 会话表累积 | 加清理任务：`DELETE FROM test_session WHERE started_at < now() - interval '7 days'` |

---

## 7. 回滚

```bash
cd /srv/mbti
git log --oneline -5
git checkout <上一个提交>
docker compose -f docker-compose.prod.yml up -d --build api
```

更稳的做法是给镜像打 tag：

```bash
# 发布前
docker tag mbti-prod-api:latest mbti-prod-api:2026-11-11
# 回滚时
docker compose -f docker-compose.prod.yml stop api
docker tag mbti-prod-api:2026-11-11 mbti-prod-api:latest
docker compose -f docker-compose.prod.yml up -d api
```

**数据库回滚**：结构变更（DDL）不随代码回滚，需要单独恢复备份，见 `docs/deploy.md` §6。

---

## 8. 检查清单

- [ ] `docker compose -f docker-compose.prod.yml ps` 里 api 是 `Up (healthy)`
- [ ] `logs api` 有 `数据库已就绪` 且无报错
- [ ] `/healthz` 返回 200
- [ ] `POST /sessions` 能拿到 40 道题
- [ ] 容器日志有轮转配置（`max-size=20m`），不会把磁盘写满
- [ ] `.env` 权限 600，`DB_PASSWORD` 不是默认值
