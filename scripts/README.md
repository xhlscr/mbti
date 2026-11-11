# scripts · 内容与题库流水线

四个脚本，按「源文件 → 内容 JSON → SQL / 数据库」一条线走完，没有第五个。

```
根目录 *.md                 app/data/*.json                sql/*.sql                PostgreSQL
questions.md   ──①──▶  questions.json        ──②──▶  02_seed.sql   ──③──▶   question 表
types.md                types.json                            （首次初始化）
cognitive-functions.md  functions.json
                                     └──────④──────▶  publish_bank ──▶ 新版本（增量更新）
```

## 四个脚本

| # | 脚本 | 输入 → 输出 | 什么时候跑 |
|---|---|---|---|
| ① | `import_content.py` | 根目录 `*.md` → `app/data/{questions,types,functions}.json` | **改了 md 之后**。带校验，失败直接退出 |
| ② | `export_seed_sql.py` | `app/data/*.json` → `sql/02_seed.sql` | **改了题库之后**，想用 SQL 初始化数据库时 |
| ③ | `check_seed_sql.py` | `sql/02_seed.sql` → 校验报告 | 生成 SQL 后跑一次；不需要数据库 |
| ④ | `publish_bank.py` | `app/data/questions.json` → 数据库新版本 | **线上改题**。建新版本并发布，旧结果不受影响 |

## 常用命令

```bash
cd backend

# 内容有改动：md → JSON
python scripts/import_content.py --retag

# 想用 SQL 初始化：JSON → SQL，然后校验
python scripts/export_seed_sql.py
python scripts/check_seed_sql.py

# 只想校验题库、不写库
python scripts/publish_bank.py --dry-run

# 线上追加/更新题目（会生成新版本，不是覆盖）
python scripts/publish_bank.py
```

## 两条路径别混用

| 场景 | 用哪个 | 原因 |
|---|---|---|
| **首次**搭库 | `sql/01_schema.sql` + `sql/02_seed.sql` | 一次导入，不依赖应用启动 |
| **之后**改题 | `publish_bank.py` | 会建新版本；重复跑 SQL 因为 `ON CONFLICT` 不会更新内容 |

`02_seed.sql` 里主键是写死的（题 1–80、版本 1），设计成「只负责初始化」。
内容变了还跑它，只会 no-op，不会报错也不会更新——这是有意的，避免误把线上数据覆盖掉。

## 约定

- 脚本都自带 sys.path 引导，**可以从仓库根目录或 backend/ 目录执行**；
- 所有脚本失败时退出码为 1，方便 CI 串联；
- `--dry-run` 与 `--retag` 等开关在 `--help` 里；
- 生成物（`app/data/*.json`、`sql/02_seed.sql`）要提交进 git，它们是构建输入。
