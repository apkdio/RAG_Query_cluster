# query_core

固定阈值的词汇聚类与 QK 双路匹配，只依赖 Python 标准库。

- 输入只有一批词汇，用 `|` 分隔；
- 聚类结果输出 JSON，并生成一个可拖拽复核的 HTML；
- QK 侧输入单条 query，走稠密 + 关键词双路匹配；
- 阈值写死在代码里，不提供来源选择或调参参数。

## 快速开始

```bash
cd D:\query_core

# 聚类：读文件，或直接 --text "词1|词2|词3"
python -m query_core cluster --input examples/inputs.txt --out out

# 只用本地向量、不连 Ollama
python -m query_core cluster --input examples/inputs.txt --backend hash --out out

# 重新生成复核页
python -m query_core review --clusters out/clusters.json --out out/review.html

# QK 单条匹配
python -m query_core qk "苹果多少钱"
python -m query_core qk "苹果多少钱" --json
```

默认 `--backend auto`：优先调用本机 Ollama 的 `bge-m3`，不可用时退回哈希向量，流程不会中断。哈希向量只适合验证流程，语义聚类效果不如 `bge-m3`。

## 输入

`cluster` 接受 `--input` 文件或 `--text` 字符串，词汇之间用 `|` 分隔：

```
苹果|香蕉|橙子|苹果多少钱|香蕉价格|苹果怎么保存
```

空项会被丢弃，重复词只聚类一次，但会在输出里保留 `count`。

## 手动指定簇

需要先按条件归到指定簇时，加 `--rules`：

```bash
python -m query_core cluster --input examples/inputs.txt \
  --rules examples/rules.json --out out
```

规则文件用正则或关键词：

```json
{
  "clusters": [
    {
      "name": "价格相关",
      "keywords": ["价格"],
      "regex": ["多少钱|费用"],
      "match": "any",
      "exclude": ["免费"]
    },
    {
      "name": "保存相关",
      "regex": ["保存|保鲜"]
    }
  ]
}
```

- `keywords` 和 `regex` 是两个独立字段，可以只写一个，也可以同时写；
- `match: "any"`（默认）：任一关键词命中，或任一条正则命中，即算命中；
- `match: "all"`：所有关键词都要命中，并且所有正则都要命中；
- `exclude` 用来排除某些词，命中 exclude 的 query 不会进这条规则；
- 一条 query 命中多个规则时，按规则顺序取第一个；
- 没命中任何规则的 query 继续走自动聚类。

输出里每个簇多 `name` 和 `kind`（`manual` / `auto`），复核页标题会显示规则名。

## 输出 JSON

```json
{
  "meta": {
    "count": 8,
    "clusters": 6,
    "threshold": 0.62,
    "embedding": "hash",
    "manual_rules": ["价格相关", "保存相关"],
    "generated_at": "2026-11-10T16:02:39"
  },
  "clusters": [
    {
      "cluster_id": "C1",
      "name": "价格相关",
      "kind": "manual",
      "size": 2,
      "cohesion": 0.0,
      "terms": [
        {"query_id": "C1:Q1", "text": "苹果多少钱", "count": 1},
        {"query_id": "C1:Q2", "text": "香蕉价格", "count": 1}
      ]
    }
  ]
}
```

`query_id` 由簇编号和簇内顺序生成，只用于复核页定位，不依赖外部 ID。

## 复核页

`cluster` 会生成画布式 `out/review.html`，直接用浏览器打开：

- 簇以卡片/椭圆排在画布上，支持缩放、拖拽、适应宽度；
- 拖动词块可在簇之间移动，拖到垃圾桶删除；
- 可新建簇、删除整簇、合并、填写 slug 和关键词；
- 标签：正确 / 部分 / 不正确 / 新建，另有独立的“不作处理”；
- 改动自动存 localStorage，支持撤销/重做；
- 导出 CSV/JSON 时按当前顺序重新生成 `C1:Q1` 形式的 `query_id`。

## QK 双路匹配

词表是按行写的文本，`名称: 问句1##问句2`：

```
水果咨询: 苹果多少钱##香蕉价格
保存咨询: 苹果怎么保存##水果怎么保鲜
```

也兼容 `{名称: [问句...]}` 的 JSON。运行：

```bash
python -m query_core qk "苹果多少钱" --table examples/qk_table.txt
```

打分方式：

1. 稠密：`bge-m3` 余弦相似度排序；
2. 关键词：字符二元组 tf-idf 稀疏余弦，低于固定阈值 `0.35` 的条目不进入关键词榜；
3. 两路按 RRF（`1/(60+rank)`）融合，同一名称取最高分，输出前 5 个。

没有 `--s`、没有阈值参数，阈值固定在 `query_core/cluster.py` 和 `query_core/qk.py` 顶部。

## 结构

```
query_core/
├─ __main__.py       命令行入口
├─ normalize.py      归一化、停用二元组
├─ embed.py          Ollama / 哈希向量
├─ manual.py         手动规则簇
├─ cluster.py        固定阈值平均链接
├─ pipeline.py       输入解析与 JSON 组装
├─ canvas.py         复核页注入
└─ qk.py             QK 双路匹配

templates/review.html   复核页模板
examples/               示例输入、示例 QK 表、手动规则
tests/                  单元测试
```

## 测试

```bash
python -m pytest -q
```
