"""query_cluster 的路径入口；目录默认相对项目根，可用 QC_ROOT 覆盖。"""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(os.environ.get("QC_ROOT", Path(__file__).resolve().parents[2])).expanduser().resolve()
DATA_DIR = Path(os.environ.get("QC_DATA_DIR", ROOT / "data")).expanduser().resolve()
OUT_DIR = Path(os.environ.get("QC_OUT_DIR", ROOT / "out")).expanduser().resolve()
CONFIG_DIR = Path(os.environ.get("QC_CONFIG_DIR", ROOT / "config")).expanduser().resolve()
PROMPTS_DIR = Path(os.environ.get("QC_PROMPTS_DIR", ROOT / "prompts")).expanduser().resolve()
TEMPLATES_DIR = Path(os.environ.get("QC_TEMPLATES_DIR", ROOT / "templates")).expanduser().resolve()
