"""Query × Key 相关性矩阵（知识库召回口径 demo）。

纯标准库实现：不依赖 numpy / jieba（装了 jieba 会自动用，没装退回中文 bigram 分词）。

融合公式为 RRF（倒数排名融合）：
    rrf = sum(1 / (60 + rank)) * 10
    ranks (0,0) -> 0.3333333333333333
    ranks (0,1) -> 0.3306010928961749

用法：
    # 临时对比（不写配置）
    python relevance_matrix.py query "因天气要求改期" key "说明：不可转让、不可退款"

    # 多 key / 多 query
    python relevance_matrix.py query "Q1" query "Q2" key "K1" key "K2" key "K3"

    # 持久化配置
    python relevance_matrix.py add query "因天气要求改期"
    python relevance_matrix.py add key "规则：取消后的处理方式"
    python relevance_matrix.py add key "文本" --id my_key
    python relevance_matrix.py clear query
    python relevance_matrix.py clear keys
    python relevance_matrix.py                      # 跑 config.json 矩阵

    # 其他
    python relevance_matrix.py --self-check         # 校验 RRF 公式
    python relevance_matrix.py --config c.json --normalize

注意：
- 稠密通道默认用「哈希 n-gram」占位（离线可跑，非语义向量）。
  有真实向量时用 --embeddings vec.json：{"key_id": [float, ...]}。
- BM25 为本地实现（k1=1.5, b=0.75），分数只用于相对比较。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sys
import unicodedata
from dataclasses import dataclass
from typing import Any

try:  # 可选依赖
    import jieba
except Exception:  # pragma: no cover
    jieba = None

RRF_K = 60
RRF_SCALE = 10.0
DIM = 512

_CJK = r"\u4e00-\u9fff"


# ────────────────────────── 配置 ──────────────────────────
@dataclass
class KeyItem:
    key_id: str
    text: str


def load_raw(path: str) -> dict:
    if not os.path.isfile(path):
        return {"queries": [], "keys": []}
    with open(path, "r", encoding="utf-8") as fh:
        cfg = json.load(fh)
    if not isinstance(cfg, dict):
        raise ValueError(f"配置文件格式错误（应为 JSON 对象）: {path}")
    cfg.setdefault("queries", [])
    cfg.setdefault("keys", [])
    return cfg


def save_raw(path: str, cfg: dict) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, ensure_ascii=False, indent=2)
        fh.write("\n")


def load_config(path: str) -> tuple[list[str], list[KeyItem]]:
    cfg = load_raw(path)
    queries = [str(q) for q in (cfg.get("queries") or []) if str(q).strip()]

    keys: list[KeyItem] = []
    for i, raw in enumerate(cfg.get("keys") or [], 1):
        if isinstance(raw, str):
            keys.append(KeyItem(key_id=f"k{i}", text=raw))
        elif isinstance(raw, dict):
            text = str(raw.get("text") or raw.get("content") or "").strip()
            if not text:
                continue
            keys.append(KeyItem(key_id=str(raw.get("id") or raw.get("key") or f"k{i}"), text=text))
        else:
            continue

    seen: set[str] = set()
    for k in keys:
        if k.key_id in seen:
            raise ValueError(f"key id 重复: {k.key_id}")
        seen.add(k.key_id)
    return queries, keys


def _next_key_id(cfg: dict) -> str:
    n = 0
    for raw in cfg.get("keys") or []:
        if isinstance(raw, dict):
            kid = str(raw.get("id") or "")
            if len(kid) > 1 and kid[0] == "k" and kid[1:].isdigit():
                n = max(n, int(kid[1:]))
    return f"k{n + 1}"


def cmd_add(path: str, target: str, text: str, key_id: str = "") -> int:
    cfg = load_raw(path)
    text = (text or "").strip()
    if not text:
        print('用法: add key "文本" [--id k1]   或   add query "文本"')
        return 2
    if target in ("query", "queries"):
        if text in cfg["queries"]:
            print(f"query 已存在，跳过: {text}")
            return 0
        cfg["queries"].append(text)
        save_raw(path, cfg)
        print(f"已添加 query（共 {len(cfg['queries'])} 条）: {text}")
        return 0
    if target in ("key", "keys"):
        kid = key_id or _next_key_id(cfg)
        if any(isinstance(r, dict) and str(r.get("id")) == kid for r in cfg["keys"]):
            print(f"key id 已存在，跳过: {kid}（可用 --id 指定新 id）")
            return 1
        cfg["keys"].append({"id": kid, "text": text})
        save_raw(path, cfg)
        print(f"已添加 key {kid}（共 {len(cfg['keys'])} 条）: {text}")
        return 0
    print(f"未知类型: {target}（只支持 key / query）")
    return 2


def cmd_clear(path: str, target: str) -> int:
    cfg = load_raw(path)
    if target in ("query", "queries"):
        n = len(cfg["queries"])
        cfg["queries"] = []
    elif target in ("key", "keys"):
        n = len(cfg["keys"])
        cfg["keys"] = []
    else:
        print(f"未知类型: {target}（只支持 query / keys）")
        return 2
    save_raw(path, cfg)
    print(f"已清空 {target}（删除 {n} 条）⇒ queries={len(cfg['queries'])} keys={len(cfg['keys'])}")
    return 0


# ────────────────────────── 分词 / 向量 ──────────────────────────
def tokenize(text: str) -> list[str]:
    if jieba is not None:
        return [t for t in jieba.lcut(text) if t.strip()]
    # 无 jieba：英文/数字按词，中文按单字 + 二元组（保证「退款」「改期」这类词能被匹配）
    words = re.findall(r"[A-Za-z0-9_]+", text)
    chars = re.findall(f"[{_CJK}]", text)
    bigrams = ["".join(chars[i : i + 2]) for i in range(len(chars) - 1)]
    return words + chars + bigrams


def _hash_idx(token: str) -> int:
    return int(hashlib.md5(token.encode("utf-8")).hexdigest()[:8], 16) % DIM


# ────────────────────────── 向量后端 ──────────────────────────
# auto   : 优先 Ollama（bge-m3），失败退回哈希占位
# ollama : 强制 Ollama
# lite   : 强制哈希占位
_BACKEND = "auto"
_EMB_MODEL = os.environ.get("QK_EMBED_MODEL", "bge-m3")
_OLLAMA_URL = os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
_CACHE: dict[str, Any] = {}
_WARNED = False


def set_backend(name: str) -> None:
    global _BACKEND
    _BACKEND = (name or "auto").strip().lower()
    _CACHE.clear()


def backend_name() -> str:
    return _BACKEND


def _hash_vec(text: str) -> dict[int, float]:
    vec: dict[int, float] = {}
    for t in tokenize(text):
        idx = _hash_idx(t)
        vec[idx] = vec.get(idx, 0.0) + 1.0
    norm = math.sqrt(sum(v * v for v in vec.values()))
    return {k: v / norm for k, v in vec.items()} if norm else {}


def _normalize(vec: list[float]) -> list[float]:
    norm = math.sqrt(sum(float(x) * float(x) for x in vec))
    return [float(x) / norm for x in vec] if norm else [0.0] * len(vec)


def _post_json(url: str, payload: dict, timeout: int = 60) -> dict:
    import urllib.request

    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _ollama_embed(texts: list[str]) -> list[list[float]]:
    """优先 /api/embed（批量）；老版本回退 /api/embeddings（单条）。"""
    try:
        data = _post_json(f"{_OLLAMA_URL}/api/embed", {"model": _EMB_MODEL, "input": texts})
        emb = data.get("embeddings")
        if isinstance(emb, list) and len(emb) == len(texts):
            return emb
        raise ValueError(f"/api/embed 返回异常: keys={list(data)}")
    except Exception:
        out = []
        for t in texts:
            data = _post_json(f"{_OLLAMA_URL}/api/embeddings", {"model": _EMB_MODEL, "prompt": t})
            out.append(data["embedding"])
        return out


def embed_batch(texts: list[str]) -> list[Any]:
    """批量取向量（带缓存）。返回 list[list[float]] 或 list[dict]（lite）。"""
    global _WARNED
    missing = [t for t in texts if t not in _CACHE]
    if missing:
        if _BACKEND in ("auto", "ollama"):
            try:
                for t, v in zip(missing, _ollama_embed(missing)):
                    _CACHE[t] = _normalize(v)
            except Exception as exc:
                if _BACKEND == "ollama":
                    raise SystemExit(f"Ollama embedding 失败（{_OLLAMA_URL}/{_EMB_MODEL}）: {exc}")
                if not _WARNED:
                    print(f"[warn] Ollama 不可用，改用哈希占位向量: {exc}", file=sys.stderr)
                    _WARNED = True
                for t in missing:
                    _CACHE[t] = _hash_vec(t)
        else:
            for t in missing:
                _CACHE[t] = _hash_vec(t)
    return [_CACHE[t] for t in texts]


def cosine(a: Any, b: Any) -> float:
    """支持 list 向量与 dict（稀疏）向量。"""
    if not a or not b:
        return 0.0
    if isinstance(a, dict) or isinstance(b, dict):
        if not isinstance(a, dict):
            a = {i: v for i, v in enumerate(a)}
        if not isinstance(b, dict):
            b = {i: v for i, v in enumerate(b)}
        if len(a) > len(b):
            a, b = b, a
        return sum(v * b.get(k, 0.0) for k, v in a.items())
    return sum(x * y for x, y in zip(a, b))


# 便捷包装：单条文本向量、统一余弦入口
def lite_embed(text: str) -> Any:
    return embed_batch([text])[0]


def cosine_sparse(a: Any, b: Any) -> float:
    return cosine(a, b)


# ────────────────────────── BM25 ──────────────────────────
class BM25:
    def __init__(self, docs: list[list[str]], k1: float = 1.5, b: float = 0.75):
        self.k1, self.b = k1, b
        self.n = len(docs)
        self.tf: list[dict[str, int]] = []
        self.len: list[int] = []
        self.df: dict[str, int] = {}
        for toks in docs:
            counts: dict[str, int] = {}
            for t in toks:
                counts[t] = counts.get(t, 0) + 1
            self.tf.append(counts)
            self.len.append(len(toks))
            for t in counts:
                self.df[t] = self.df.get(t, 0) + 1
        self.avg_len = (sum(self.len) / self.n) if self.n else 0.0

    def _idf(self, term: str) -> float:
        df = self.df.get(term, 0)
        return math.log(1 + (self.n - df + 0.5) / (df + 0.5))

    def scores(self, query_tokens: list[str]) -> list[float]:
        out = [0.0] * self.n
        for i in range(self.n):
            s = 0.0
            for t in query_tokens:
                f = self.tf[i].get(t, 0)
                if not f:
                    continue
                denom = f + self.k1 * (1 - self.b + self.b * self.len[i] / (self.avg_len or 1))
                s += self._idf(t) * f * (self.k1 + 1) / denom
            out[i] = s
        return out


# ────────────────────────── 融合 ──────────────────────────
def ranks_desc(scores: list[float], top_n: int = 20) -> list[int]:
    """0 起的位次；只为真正召回的候选排名（未命中记 -1）。"""
    idx = [i for i, s in enumerate(scores) if abs(s) > 1e-12]
    idx.sort(key=lambda i: -scores[i])
    out = [-1] * len(scores)
    for pos, i in enumerate(idx[:top_n]):
        out[i] = pos
    return out


def rrf_scores(rank_lists: list[list[int]]) -> list[float]:
    n = len(rank_lists[0])
    out = [0.0] * n
    for ranks in rank_lists:
        for i, r in enumerate(ranks):
            if r >= 0:
                out[i] += 1.0 / (RRF_K + r)
    return [x * RRF_SCALE for x in out]


def normalize01(scores: list[float]) -> list[float]:
    lo, hi = min(scores), max(scores)
    if hi - lo < 1e-12:
        return [0.0] * len(scores)
    return [(s - lo) / (hi - lo) for s in scores]


def self_check() -> int:
    cases = [
        ([0, 0], 0.3333333333333333),
        ([0, 1], 0.3306010928961749),
        ([0], 1 / 60 * RRF_SCALE),
        ([1], 1 / 61 * RRF_SCALE),
    ]
    ok = True
    print("RRF 公式自检（1/(60+rank) 求和 ×10）")
    print(f"  分词器: {'jieba' if jieba is not None else 'bigram 回退'}")
    for ranks, expect in cases:
        got = sum(1.0 / (RRF_K + r) for r in ranks) * RRF_SCALE
        flag = abs(got - expect) < 1e-15
        ok &= flag
        print(f"  ranks={ranks}  got={got:.16f}  expect={expect:.16f}  {'OK' if flag else 'MISMATCH'}")
    return 0 if ok else 1


# ────────────────────────── 输出 ──────────────────────────
def display_width(text: str) -> int:
    return sum(2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1 for ch in text)


def pad(text: str, width: int) -> str:
    return text + " " * max(0, width - display_width(text))


def clip(text: str, limit: int = 18) -> str:
    return text if display_width(text) <= limit else text[: max(1, limit // 2)] + "…"


def print_matrix(
    title: str,
    row_labels: list[str],
    col_labels: list[str],
    matrix: list[list[float]],
    ranks: list[list[int]] | None = None,
    digits: int = 4,
) -> None:
    print()
    print(f"── {title} ──")
    row_w = max(display_width(r) for r in row_labels) + 2
    col_w = max(display_width(c) for c in col_labels) + 3
    print(" " * row_w + "".join(pad(c, col_w) for c in col_labels))
    for i, rlab in enumerate(row_labels):
        cells = []
        for j in range(len(col_labels)):
            val = f"{matrix[i][j]:.{digits}f}"
            if ranks is not None:
                val += f"#{ranks[i][j] + 1}" if ranks[i][j] >= 0 else "  -"
            cells.append(pad(val, col_w))
        print(pad(rlab, row_w) + "".join(cells))


def _load_embeddings(path: str) -> dict[str, list[float]]:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _dense_scores(
    query: str, key_texts: list[str], key_ids: list[str], embeddings: dict[str, list[float]] | None
) -> list[float]:
    qv = lite_embed(query)
    if not embeddings:
        kvecs = embed_batch(key_texts)
        return [cosine(qv, v) for v in kvecs]

    out = []
    for text, kid in zip(key_texts, key_ids):
        raw = embeddings.get(kid)
        if raw is None:
            out.append(cosine_sparse(qv, lite_embed(text)))
            continue
        norm = math.sqrt(sum(float(v) * float(v) for v in raw))
        vec = {i: float(v) / norm for i, v in enumerate(raw)} if norm else {}
        out.append(cosine_sparse(qv, vec))
    return out


# ────────────────────────── 模式：query/key 临时对比 ──────────────────────────
def cmd_pair(argv: list[str]) -> int:
    qs: list[str] = []
    ks: list[str] = []
    emb_path = ""
    i = 0
    while i < len(argv):
        token = argv[i]
        if token in ("query", "q") and i + 1 < len(argv):
            qs.append(argv[i + 1])
            i += 2
        elif token in ("key", "k") and i + 1 < len(argv):
            ks.append(argv[i + 1])
            i += 2
        elif token == "--embeddings" and i + 1 < len(argv):
            emb_path = argv[i + 1]
            i += 2
        else:
            i += 1

    if not qs or not ks:
        print('用法: python relevance_matrix.py query "你的问题" key "候选文本"')
        return 2

    embeddings = _load_embeddings(emb_path) if emb_path else None
    key_ids = [str(j + 1) for j in range(len(ks))]
    bm25 = BM25([tokenize(k) for k in ks])

    for q in qs:
        qt = tokenize(q)
        s_bm25 = bm25.scores(qt)
        s_dense = _dense_scores(q, ks, key_ids, embeddings)
        rb = ranks_desc(s_bm25, top_n=len(ks))
        rd = ranks_desc(s_dense, top_n=len(ks))
        s_rrf = rrf_scores([rd, rb])

        print()
        print(f"query: {q}")
        for j, k in enumerate(ks):
            print(f"key[{j + 1}]: {k}")
            hit_terms = [t for t in sorted(set(qt)) if bm25.tf[j].get(t, 0) > 0]
            print(
                f"  BM25   = {s_bm25[j]:.6f}"
                f"   (命中词: {', '.join(hit_terms) if hit_terms else '无'})"
            )
            print(f"  dense  = {s_dense[j]:.6f}")
            print(
                f"  RRF    = {s_rrf[j]:.6f}"
                f"   (bm25_rank={'-' if rb[j] < 0 else rb[j]}, dense_rank={'-' if rd[j] < 0 else rd[j]})"
            )
        if len(ks) > 1:
            best = max(range(len(ks)), key=lambda j: s_rrf[j])
            print(f"  ⇒ 最相关: key[{best + 1}] (RRF={s_rrf[best]:.6f})")
    return 0


# ────────────────────────── 模式：配置矩阵 ──────────────────────────
def run(args: argparse.Namespace) -> int:
    queries, keys = load_config(args.config)
    if not queries or not keys:
        print(f"配置不完整：queries={len(queries)}  keys={len(keys)}")
        print('先添加：  add query "你的问题"    add key "候选文本"')
        return 1

    key_texts = [k.text for k in keys]
    key_ids = [k.key_id for k in keys]
    key_tokens = [tokenize(t) for t in key_texts]
    bm25 = BM25(key_tokens)
    embeddings = _load_embeddings(args.embeddings) if args.embeddings else None

    m_bm25: list[list[float]] = []
    m_dense: list[list[float]] = []
    m_rrf: list[list[float]] = []
    r_bm25: list[list[int]] = []
    r_dense: list[list[int]] = []
    r_rrf: list[list[int]] = []

    for q in queries:
        s_bm25 = bm25.scores(tokenize(q))
        s_dense = _dense_scores(q, key_texts, key_ids, embeddings)
        rb = ranks_desc(s_bm25, args.top_n)
        rd = ranks_desc(s_dense, args.top_n)
        s_rrf = rrf_scores([rd, rb])
        rr = ranks_desc(s_rrf, args.top_n)

        if args.normalize:
            s_bm25, s_dense, s_rrf = normalize01(s_bm25), normalize01(s_dense), normalize01(s_rrf)

        m_bm25.append(s_bm25)
        m_dense.append(s_dense)
        m_rrf.append(s_rrf)
        r_bm25.append(rb)
        r_dense.append(rd)
        r_rrf.append(rr)

    q_labels = [clip(q) for q in queries]
    k_labels = [clip(k) for k in key_ids]

    print(f"queries={len(queries)}  keys={len(keys)}  normalize={args.normalize}")
    print(f"分词器: {'jieba' if jieba is not None else 'bigram 回退'}")
    if args.metric in ("all", "bm25"):
        print_matrix("BM25（关键词）", q_labels, k_labels, m_bm25, r_bm25)
    if args.metric in ("all", "dense"):
        print_matrix("稠密（占位向量）", q_labels, k_labels, m_dense, r_dense)
    if args.metric in ("all", "rrf"):
        print_matrix("RRF 融合（k=60, ×10）", q_labels, k_labels, m_rrf, r_rrf)

    print()
    print("── 每个 query 的 Top-3 ──")
    for i, q in enumerate(queries):
        order = sorted(range(len(keys)), key=lambda j: -m_rrf[i][j])[:3]
        parts = [f"{key_ids[j]}({m_rrf[i][j]:.4f})" for j in order if m_rrf[i][j] > 0]
        print(f"  {q}  ->  {' | '.join(parts) if parts else '(无匹配)'}")

    return 0


def main() -> int:
    argv = sys.argv[1:]

    if argv and argv[0] in ("query", "q"):
        return cmd_pair(argv)

    if argv and argv[0] in ("add", "clear"):
        config_path = "config.json"
        if "--config" in argv:
            i = argv.index("--config")
            if i + 1 < len(argv):
                config_path = argv[i + 1]
                del argv[i : i + 2]
        cmd, rest = argv[0], argv[1:]
        if not rest:
            print('用法: add key "文本" [--id k1] | add query "文本" | clear query | clear keys')
            return 2
        target = rest[0]
        if cmd == "add":
            key_id = ""
            if "--id" in rest:
                j = rest.index("--id")
                if j + 1 < len(rest):
                    key_id = rest[j + 1]
                    del rest[j : j + 2]
            text = rest[1] if len(rest) > 1 else ""
            return cmd_add(config_path, target, text, key_id)
        return cmd_clear(config_path, target)

    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.json")
    ap.add_argument("--metric", choices=["all", "bm25", "dense", "rrf"], default="all")
    ap.add_argument("--normalize", action="store_true", help="每个 query 内做 min-max 归一化到 0~1")
    ap.add_argument("--embeddings", default="", help="可选：{key_id: [float,...]} 真实向量")
    ap.add_argument("--top-n", type=int, default=20, help="每路进入融合的候选数（对齐 retrieveCount）")
    ap.add_argument("--embedding", choices=["auto", "ollama", "lite"], default="auto",
                    help="向量后端：auto=优先 Ollama bge-m3；lite=哈希占位")
    ap.add_argument("--self-check", action="store_true")
    args = ap.parse_args()
    set_backend(args.embedding)
    if args.self_check:
        return self_check()
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
