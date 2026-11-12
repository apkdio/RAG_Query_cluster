"""工作区路径入口：所有本地目录从这里取，不在代码里写死绝对路径。"""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(os.environ.get("QC_ROOT", Path(__file__).resolve().parent)).expanduser().resolve()

QUERY_CLUSTER_DIR = ROOT / "query_cluster"
QK_VALIDATION_DIR = ROOT / "qk_validation"

DATA_DIR = Path(os.environ.get("QC_DATA_DIR", QUERY_CLUSTER_DIR / "data")).expanduser().resolve()
OUT_DIR = Path(os.environ.get("QC_OUT_DIR", QUERY_CLUSTER_DIR / "out")).expanduser().resolve()
CONFIG_DIR = Path(os.environ.get("QC_CONFIG_DIR", QUERY_CLUSTER_DIR / "config")).expanduser().resolve()
PROMPTS_DIR = Path(os.environ.get("QC_PROMPTS_DIR", QUERY_CLUSTER_DIR / "prompts")).expanduser().resolve()
TEMPLATES_DIR = Path(os.environ.get("QC_TEMPLATES_DIR", QUERY_CLUSTER_DIR / "templates")).expanduser().resolve()

QK_DATA_DIR = Path(os.environ.get("QK_DATA_DIR", QK_VALIDATION_DIR / "data")).expanduser().resolve()
QK_CONFIG_DIR = Path(os.environ.get("QK_CONFIG_DIR", QK_VALIDATION_DIR / "config")).expanduser().resolve()
