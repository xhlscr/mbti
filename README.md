# backend · MBTI 测试服务

FastAPI + SQLModel + PostgreSQL 16。分层：`api`（HTTP）→ `services`（业务）→ `models`（ORM）。

## 目录

```
backend/
├── app/
│   ├── main.py                 # 应用装配：路由、异常、CORS、启动钩子
│   ├── core/                   # 基础设施
│   │   ├── config.py           # pydantic-settings，环境变量 MBTI_*
│   │   ├── database.py         # engine / get_db / init_db
│   │   └── exceptions.py       # DomainError 及其子类（映射 HTTP 状态）
│   ├── models/                 # ORM 表
│   │   ├── base.py             # utcnow / json_column
│   │   ├── celebrity.py        # 历史人物 + 匹配快照（阶段二）
│   │   ├── question.py         # question_bank / bank_version / question
│   │   ├── session.py          # test_session / answer
│   │   └── result.py           # result
│   ├── schemas/                # Pydantic 出入参、题型判别联合
│   ├── api/
│   │   ├── deps.py             # get_db / 限流 / 客户端标识
│   │   └── v1/
│   │       ├── router.py       # /api/v1 聚合
│   │       └── endpoints/      # health / sessions / results / content / celebrities
│   ├── services/               # 业务逻辑（不依赖 FastAPI）
│   │   ├── draw.py             # 分层抽题
│   │   ├── scoring.py          # 聚合与判型
│   │   ├── settle.py           # 结算（compute 纯函数 + submit 落库）
│   │   ├── bank.py             # 题库发布、版本、首启播种
│   │   └── content_loader.py   # types/functions/questions 内存缓存
│   ├── scoring/                # 题型计分策略注册表
│   │   ├── registry.py         # Scorer(score, cap) + register
│   │   ├── likert5.py
│   │   └── choice2.py          # 用于验证"加题型不用改流程"
│   ├── matching/celebrity.py   # 名人匹配算法（纯函数）
│   └── data/                   # 内容产物（JSON）
├── scripts/                    # 内容流水线：import_content / export_seed_sql / check_seed_sql / publish_bank
├── tests/                      # 63 条
├── sql/                        # 01_schema / 02_seed / 03_verify（可手工导入）
├── requirements.txt            # 运行时依赖
├── requirements-dev.txt        # + 测试工具
├── pyproject.toml              # 包元数据（本项目不要求安装成包）
└── .env.example
```

## 命令

```bash
pip install -r requirements-dev.txt           # 8 个依赖；只跑服务用 requirements.txt
uvicorn app.main:app --reload --port 8000     # 首次启动自动建表 + 播种题库
python -m pytest                              # 全部测试（63 条）
python scripts/publish_bank.py --dry-run      # 校验题库，不写库
```

> 不用 `pip install -e ".[dev]"`：它会触发构建隔离、在临时环境重装 setuptools，
> 而 Python 3.12 的 venv 默认不带 setuptools，镜像抖动时必失败。详见 `docs/run-locally.md` §4.1.1。

## SQL 脚本（可选，用于手工初始化）

```
sql/01_schema.sql   建表 + 索引（幂等）
sql/02_seed.sql     题库 80 题 + 名人 64 位（幂等，ON CONFLICT DO NOTHING）
sql/03_verify.sql   导入后自检
```

```bash
psql "postgresql://mbti:mbti@localhost:5432/mbti" -f sql/01_schema.sql
psql "postgresql://mbti:mbti@localhost:5432/mbti" -f sql/02_seed.sql
psql "postgresql://mbti:mbti@localhost:5432/mbti" -f sql/03_verify.sql
```

改过 `app/data/*.json` 后重新生成：

```bash
python scripts/export_seed_sql.py    # 重新产出 02_seed.sql
python scripts/check_seed_sql.py     # 反向解析校验，无需数据库
```

应用启动时 `create_all` 与自动播种都是幂等的，**导过 SQL 也不会重复插入**。

## 分层约定

| 层 | 允许 | 禁止 |
|---|---|---|
| `api/` | 参数校验、调 service、拼响应 | 写 SQL、写业务规则 |
| `services/` | 业务规则、事务 | 依赖 FastAPI、返回 HTTP 响应 |
| `scoring/` | 纯计算 | 认识数据库 |
| `models/` | 表结构 | 业务逻辑 |

业务异常一律抛 `core.exceptions.DomainError` 子类，由 `main.py` 统一映射成 `{"detail": "<code>"}`。

## 历史名人模块

`app/matching/celebrity.py` + `app/data/celebrities.json`（64 位，16 型 × 4 人），阶段二接到结果页。
数据校验由 `tests/test_celebrity_match.py` 承担，DB 导入走 `sql/02_seed.sql`，没有单独的脚本。

## 脚本

内容与题库流水线见 [scripts/README.md](scripts/README.md)：四个脚本
（`import_content` / `export_seed_sql` / `check_seed_sql` / `publish_bank`），
从 md 一路走到数据库，没有第五个。
