# query_cluster

词表输入、自动聚类、LLM 初审与人工复核。

当前 S1 已落地 `entities/`（Query / Cluster / ReviewState / QID / 事件）；聚类链仍沿用旧 `C1:Q1` 标识和旧 patch 操作，按 `../DESIGN_LLM_REVIEW.md` 在后续阶段重构。

## 运行

```powershell
cd query_cluster
$env:PYTHONPATH = "src"

python -m query_cluster cluster `
  --input examples/inputs.txt --backend hash --out out

# 重新生成复核页
python -m query_cluster review --clusters out/clusters.json --out out/review.html

# 在仓库根目录测试
uv run --package query-cluster python -m pytest -q
```

默认 `--backend auto` 优先调用本机 Ollama 的 `bge-m3`，不可用时退回哈希向量。

## 结构

```text
query_cluster/
├─ src/query_cluster/
│  ├─ entities/          Query / Cluster / ReviewState / QID / 事件
│  ├─ cluster.py         聚类算法
│  ├─ pipeline.py        输入与结果组装
│  └─ canvas.py          复核页注入
├─ templates/review.html
├─ tests/
├─ examples/
├─ config/              配置示例
├─ prompts/             LLM 提示词
├─ data/                本地输入（不入库）
└─ out/                 本地结果（不入库）
```
