# query_core

Query 聚类复核与 QK 召回验证的工作区，包含两个互不依赖的软件包：

- `query_cluster/`：词表输入、自动聚类、LLM 初审、人工复核；
- `qk_validation/`：QK 词表匹配与召回验证。

当前 S0–S8 已完成并通过全量验收；算法、LLM、人工三类结果统一放在同一个 run 目录，使用 `state.clustering.json / state.llm.json / state.human.json` 命名。

## 目录

```text
query_core/
├─ DESIGN_LLM_REVIEW.md
├─ paths.py
├─ query_cluster/
│  ├─ src/query_cluster/
│  ├─ templates/review.html
│  ├─ tests/
│  ├─ examples/
│  ├─ config/
│  └─ prompts/
└─ qk_validation/
   ├─ src/qk_validation/
   ├─ config/
   ├─ data/
   └─ tests/
```

`data/`、`out/`、`temp/`、实际 `config/*.json` 不进入版本管理；真实数据只通过本地目录注入。

## 快速开始

```powershell
# 在仓库根目录
uv sync --all-packages

# 算法结果：输出 state.clustering.json
uv run --package query-cluster python -m query_cluster cluster `
  --input query_cluster/examples/inputs.txt --backend hash `
  --out query_cluster/out/run1

# LLM 两阶段复核：输出 state.llm.json 到同一个 run 目录
uv run --package query-cluster python -m query_cluster llm-review `
  --state query_cluster/out/run1/state.clustering.json `
  --out query_cluster/out/run1

# 本地复核服务：加载任意阶段 JSON
uv run --package query-cluster python -m query_cluster serve `
  --state query_cluster/out/run1/state.llm.json

# 旧 clusters.json 迁移
uv run --package query-cluster python -m query_cluster migrate `
  --input old/clusters.json --out query_cluster/out/run1/state.clustering.json

# QK 单条匹配
uv run --package qk-validation python -m qk_validation.match "苹果多少钱"
```

没有 uv 时，可把 `query_cluster/src` 或 `qk_validation/src` 加入 `PYTHONPATH` 后运行。

## 设计

阶段、实体、LLM patch、复核页和排期见 [DESIGN_LLM_REVIEW.md](DESIGN_LLM_REVIEW.md)。
