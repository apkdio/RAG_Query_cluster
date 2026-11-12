# query_cluster

词表输入、自动聚类、LLM 初审与人工复核。

当前 S1/S2 已落地 `entities/` 和 `preprocess/`、`clustering/`：输入支持归一化去重、QID 分配，并产出新的 `ReviewState`。旧 `cluster` 链路暂时保留，供现有复核页和 patch 使用。

## 运行

```powershell
cd query_cluster
$env:PYTHONPATH = "src"

# 新状态链路：输出 state.json
python -m query_cluster cluster `
  --input examples/inputs.txt --backend hash --state --out out

# 旧链路：输出 clusters.json 和 review.html
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
│  ├─ preprocess/        归一化、去重、QID 分配
│  ├─ clustering/        向量、平均链接、ReviewState 组装
│  ├─ pipeline.py        旧链路兼容入口
│  └─ canvas.py          复核页注入
├─ templates/review.html
├─ tests/
├─ examples/
├─ config/              配置示例
├─ prompts/             LLM 提示词
├─ data/                本地输入（不入库）
└─ out/                 本地结果（不入库）
```
