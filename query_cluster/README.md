# query_cluster

词表输入、自动聚类、LLM 初审与人工复核。


## 运行

```powershell
cd query_cluster
$env:PYTHONPATH = "src"

# 算法结果：输出 state.clustering.json
python -m query_cluster cluster `
  --input examples/inputs.txt --backend hash --out out/run1

# LLM 两阶段复核：state.llm.json 写回同一个 run 目录
python -m query_cluster llm-review `
  --state out/run1/state.clustering.json --out out/run1

# 本地复核服务：加载任意阶段 JSON
python -m query_cluster serve --state out/run1/state.llm.json --port 8765

# 旧 clusters.json 迁移
python -m query_cluster migrate `
  --input old/clusters.json --out out/run1/state.clustering.json

# 在仓库根目录测试
uv run --package query-cluster python -m pytest -q
```

默认 `--backend auto` 优先调用本机 Ollama 的 `bge-m3`，不可用时退回哈希向量。

## 复核标签

复核页的标签是叠加显示的，不是单选状态：

- `Auto`：算法聚类产生的簇。
- `LLM`：LLM 复核阶段改动过成员的簇；LLM 新建簇直接显示 `LLM`。
- `Manual`：人工新建的簇。
- `Human`：复核页上簇对象与载入时的基线不同（成员、名称、slug、keywords 等）；改回基线后自动撤销。

## 结构

```text
query_cluster/
├─ src/query_cluster/
│  ├─ entities/          Query / Cluster / ReviewState / QID / 事件
│  ├─ preprocess/        归一化、去重、QID 分配
│  ├─ clustering/        向量、平均链接、ReviewState 组装
│  ├─ llm/               客户端、prompt、patch、两阶段复核
│  ├─ review/            复核动作、导出、diff、本地服务
│  ├─ tools/             旧结果迁移
│  ├─ paths.py           包内路径入口
│  └─ state_files.py     统一 state 文件名
├─ templates/review.html
├─ tests/
├─ examples/
├─ config/              配置示例
├─ prompts/             LLM 提示词
├─ data/                本地输入（不入库）
└─ out/                 本地结果（不入库）
```
