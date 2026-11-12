# query_core

Query 聚类复核与 QK 召回验证的工作区，包含两个互不依赖的软件包：

- `query_cluster/`：词表输入、自动聚类、LLM 初审、人工复核；
- `qk_validation/`：QK 词表匹配与召回验证。

当前 S0 目录搬迁、S1 实体层已落地；聚类链仍按 `DESIGN_LLM_REVIEW.md` 在后续阶段重构。

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

# 聚类
uv run --package query-cluster python -m query_cluster cluster `
  --input query_cluster/examples/inputs.txt --backend hash `
  --out query_cluster/out

# QK 单条匹配
uv run --package qk-validation python -m qk_validation.qk_query "苹果多少钱"
```

没有 uv 时，可把 `query_cluster/src` 或 `qk_validation/src` 加入 `PYTHONPATH` 后运行。

## 设计

阶段、实体、LLM patch、复核页和排期见 [DESIGN_LLM_REVIEW.md](DESIGN_LLM_REVIEW.md)。
