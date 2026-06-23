"""
公司名 + 日期 对碰核心逻辑 (AND 逻辑)。

流程: 读取(Excel/CSV/PDF) -> 表头自动识别 -> 公司名规范化 / 日期解析
      -> 日期分桶(blocking) -> 桶内 rapidfuzz 名称匹配 -> 三档输出。

本模块与 MCP / DEAP 完全解耦, 可单独 import 测试。
"""
from __future__ import annotations

import io
import os
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Optional

import pandas as pd
from dateutil import parser as dateparser
from rapidfuzz import fuzz, process

# --------------------------------------------------------------------------- #
# 1. 表头别名词典 —— 用于"关键词提取表头"
# --------------------------------------------------------------------------- #
NAME_HEADER_ALIASES = [
    "公司名称", "公司名", "单位名称", "企业名称", "客户名称", "客户名",
    "供应商", "供应商名称", "名称", "单位", "企业", "公司", "name",
    "company", "company_name", "customer", "客户",
]
DATE_HEADER_ALIASES = [
    "日期", "时间", "签约日期", "成交日期", "下单日期", "开票日期",
    "录入日期", "业务日期", "交易日期", "date", "datetime", "time",
    "签订日期", "发生日期",
]

# 公司名规范化时要剥离的"组织形式"后缀 (仅用于宽松比对, 默认保留)
COMPANY_SUFFIXES = [
    "有限责任公司", "股份有限公司", "有限公司", "集团有限公司", "集团",
    "有限合伙", "合伙企业", "responsibility", "co.,ltd", "co.,ltd.",
    "co., ltd", "ltd.", "ltd", "inc.", "inc", "corp.", "corp",
    "company", "limited",
]

# --------------------------------------------------------------------------- #
# 2. 数据结构
# --------------------------------------------------------------------------- #
@dataclass
class TableSpec:
    """一张待对碰的表。"""
    rows: list[dict[str, Any]]          # 原始行
    name_col: str
    date_col: str


@dataclass
class MatchResult:
    matched: list[dict[str, Any]] = field(default_factory=list)
    to_review: list[dict[str, Any]] = field(default_factory=list)
    unmatched: list[dict[str, Any]] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)


# --------------------------------------------------------------------------- #
# 3. 读取: Excel / CSV / PDF -> DataFrame (含表头识别)
# --------------------------------------------------------------------------- #
def _read_raw(path_or_bytes: Any, filename: str) -> pd.DataFrame:
    """按扩展名读成"无表头"的二维 DataFrame, 后续再识别表头行。"""
    ext = os.path.splitext(filename)[1].lower()
    if ext in (".xlsx", ".xls", ".xlsm"):
        return pd.read_excel(path_or_bytes, header=None, dtype=object)
    if ext in (".csv", ".tsv", ".txt"):
        sep = "\t" if ext == ".tsv" else None
        if isinstance(path_or_bytes, (bytes, bytearray)):
            path_or_bytes = io.BytesIO(path_or_bytes)
        return pd.read_csv(path_or_bytes, header=None, dtype=object,
                           sep=sep, engine="python")
    if ext == ".pdf":
        return _read_pdf_table(path_or_bytes)
    raise ValueError(f"不支持的文件类型: {ext} (支持 .xlsx/.xls/.csv/.tsv/.pdf)")


def _read_pdf_table(path_or_bytes: Any) -> pd.DataFrame:
    """用 pdfplumber 抽取第一张可识别的表格 (电子版 PDF)。"""
    import pdfplumber
    src = io.BytesIO(path_or_bytes) if isinstance(path_or_bytes, (bytes, bytearray)) else path_or_bytes
    rows: list[list[Any]] = []
    with pdfplumber.open(src) as pdf:
        for page in pdf.pages:
            for table in page.extract_tables():
                rows.extend(table)
    if not rows:
        raise ValueError("PDF 中未识别到表格 (可能是扫描件, 需先 OCR)")
    width = max(len(r) for r in rows)
    rows = [r + [None] * (width - len(r)) for r in rows]
    return pd.DataFrame(rows)


def _detect_header_row(df: pd.DataFrame, max_scan: int = 15) -> int:
    """扫描前若干行, 命中表头别名最多的那行即表头行。"""
    aliases = {a.lower() for a in NAME_HEADER_ALIASES + DATE_HEADER_ALIASES}
    best_row, best_hits = 0, -1
    for i in range(min(max_scan, len(df))):
        cells = [str(c).strip().lower() for c in df.iloc[i] if pd.notna(c)]
        hits = sum(any(a in c or c in a for a in aliases) for c in cells)
        if hits > best_hits:
            best_row, best_hits = i, hits
    return best_row


def _pick_column(columns: list[str], aliases: list[str],
                 explicit: Optional[str]) -> Optional[str]:
    """从真实列名里挑出名称列 / 日期列。"""
    if explicit:
        for c in columns:
            if str(c).strip() == explicit.strip():
                return c
        # 显式列名按包含匹配兜底
        for c in columns:
            if explicit.strip() in str(c):
                return c
    norm = {c: str(c).strip().lower() for c in columns}
    for alias in aliases:                       # 别名优先级 = 列表顺序
        for c, cl in norm.items():
            if cl == alias.lower():
                return c
    for alias in aliases:
        for c, cl in norm.items():
            if alias.lower() in cl:
                return c
    return None


def load_table(path_or_bytes: Any, filename: str,
               name_col: Optional[str] = None,
               date_col: Optional[str] = None) -> TableSpec:
    """读取一张表并定位名称列 / 日期列。"""
    raw = _read_raw(path_or_bytes, filename)
    hdr = _detect_header_row(raw)
    header = [str(c).strip() if pd.notna(c) else f"col_{j}"
              for j, c in enumerate(raw.iloc[hdr])]
    body = raw.iloc[hdr + 1:].copy()
    body.columns = header
    body = body.dropna(how="all").reset_index(drop=True)

    n_col = _pick_column(header, NAME_HEADER_ALIASES, name_col)
    d_col = _pick_column(header, DATE_HEADER_ALIASES, date_col)
    if n_col is None:
        raise ValueError(f"未能识别名称列, 表头为: {header}。请显式指定 name_col。")
    if d_col is None:
        raise ValueError(f"未能识别日期列, 表头为: {header}。请显式指定 date_col。")

    rows = body.to_dict(orient="records")
    return TableSpec(rows=rows, name_col=n_col, date_col=d_col)


# --------------------------------------------------------------------------- #
# 4. 规范化: 公司名 / 日期
# --------------------------------------------------------------------------- #
_PUNCT_RE = re.compile(r"[\s\.\,\-_/\\()\[\]{}（）【】、，。·:：;；'\"“”’]+")


def normalize_company(name: Any, strip_suffix: bool = False) -> str:
    """全角转半角、去标点空格、大写化; 可选剥离组织形式后缀。"""
    if name is None or (isinstance(name, float) and pd.isna(name)):
        return ""
    s = unicodedata.normalize("NFKC", str(name)).strip()
    s = _PUNCT_RE.sub("", s)
    s = s.upper()
    if strip_suffix:
        low = s.lower()
        for suf in sorted(COMPANY_SUFFIXES, key=len, reverse=True):
            low2 = low.replace(suf.lower(), "")
            if low2 != low:
                low = low2
        s = low.upper()
    return s


def parse_date(value: Any) -> Optional[date]:
    """把各种日期写法统一成 date; 失败返回 None。"""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, (datetime, pd.Timestamp)):
        return value.date()
    if isinstance(value, date):
        return value
    # Excel 序列号 (1899-12-30 起算)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            return (datetime(1899, 12, 30) + timedelta(days=float(value))).date()
        except Exception:
            return None
    s = str(value).strip()
    if not s:
        return None
    s = re.sub(r"[年月]", "-", s).replace("日", "")
    s = unicodedata.normalize("NFKC", s)
    try:
        return dateparser.parse(s, fuzzy=True).date()
    except Exception:
        return None


# --------------------------------------------------------------------------- #
# 5. 对碰: AND 逻辑 (日期分桶 + 名称模糊)
# --------------------------------------------------------------------------- #
def reconcile(table_a: TableSpec, table_b: TableSpec,
              name_threshold: int = 85,
              review_margin: int = 10,
              date_tolerance_days: int = 0,
              strip_suffix: bool = False) -> MatchResult:
    """
    对每条 A 行, 在"日期容差内"的 B 行里找名称最相似者 (AND 逻辑)。

    - matched  : 日期满足 且 名称分 >= name_threshold
    - to_review: 日期满足 且 review 区间 [name_threshold-margin, name_threshold)
    - unmatched: 无日期候选, 或最佳名称分低于 review 下限
    """
    review_floor = max(0, name_threshold - review_margin)

    # 预处理 B: 规范名 + 解析日期, 并按日期建索引桶
    b_prepared = []
    b_buckets: dict[date, list[int]] = {}
    for idx, row in enumerate(table_b.rows):
        norm = normalize_company(row.get(table_b.name_col), strip_suffix)
        d = parse_date(row.get(table_b.date_col))
        b_prepared.append({"row": row, "norm": norm, "date": d})
        if d is not None:
            b_buckets.setdefault(d, []).append(idx)

    result = MatchResult()
    used_b: set[int] = set()

    for row in table_a.rows:
        a_norm = normalize_company(row.get(table_a.name_col), strip_suffix)
        a_date = parse_date(row.get(table_a.date_col))
        a_name_raw = row.get(table_a.name_col)
        a_date_raw = row.get(table_a.date_col)

        # ---- 取日期容差内的候选 B 行 ----
        cand_idx: list[int] = []
        if a_date is not None:
            for delta in range(-date_tolerance_days, date_tolerance_days + 1):
                cand_idx.extend(b_buckets.get(a_date + timedelta(days=delta), []))

        if not a_norm or a_date is None or not cand_idx:
            reason = ("名称为空" if not a_norm else
                      "日期无法解析" if a_date is None else "无日期匹配的候选")
            result.unmatched.append(_emit(row, table_a, a_name_raw, a_date_raw,
                                           None, None, None, 0, reason))
            continue

        # ---- 桶内 rapidfuzz 名称匹配 ----
        choices = {i: b_prepared[i]["norm"] for i in cand_idx if b_prepared[i]["norm"]}
        if not choices:
            result.unmatched.append(_emit(row, table_a, a_name_raw, a_date_raw,
                                           None, None, None, 0, "候选名称为空"))
            continue
        best = process.extractOne(a_norm, choices, scorer=fuzz.token_sort_ratio)
        if best is None:
            result.unmatched.append(_emit(row, table_a, a_name_raw, a_date_raw,
                                           None, None, None, 0, "无匹配"))
            continue
        _, score, b_i = best
        score = int(round(score))
        b_row = b_prepared[b_i]["row"]
        b_name_raw = b_row.get(table_b.name_col)
        b_date_raw = b_row.get(table_b.date_col)
        day_gap = abs((a_date - b_prepared[b_i]["date"]).days)

        emitted = _emit(row, table_a, a_name_raw, a_date_raw,
                        b_row, b_name_raw, b_date_raw, score,
                        reason="", day_gap=day_gap)
        if score >= name_threshold:
            result.matched.append(emitted)
            used_b.add(b_i)
        elif score >= review_floor:
            emitted["reason"] = f"名称相似度 {score} 处于复核区间"
            result.to_review.append(emitted)
        else:
            emitted["reason"] = f"日期匹配但名称相似度仅 {score}"
            result.unmatched.append(emitted)

    result.summary = {
        "table_a_rows": len(table_a.rows),
        "table_b_rows": len(table_b.rows),
        "matched": len(result.matched),
        "to_review": len(result.to_review),
        "unmatched": len(result.unmatched),
        "name_threshold": name_threshold,
        "review_floor": review_floor,
        "date_tolerance_days": date_tolerance_days,
        "strip_suffix": strip_suffix,
    }
    return result


def _emit(a_row, table_a, a_name, a_date, b_row, b_name, b_date,
          score, reason, day_gap=None) -> dict[str, Any]:
    return {
        "a_name": None if a_name is None else str(a_name),
        "a_date": None if a_date is None else str(a_date),
        "b_name": None if b_name is None else str(b_name),
        "b_date": None if b_date is None else str(b_date),
        "name_score": score,
        "day_gap": day_gap,
        "reason": reason,
    }


# --------------------------------------------------------------------------- #
# 6. 便捷入口: 直接给两个文件路径
# --------------------------------------------------------------------------- #
def reconcile_files(file_a: str, file_b: str, **kwargs) -> MatchResult:
    ta = load_table(file_a, os.path.basename(file_a),
                    kwargs.pop("name_col_a", None), kwargs.pop("date_col_a", None))
    tb = load_table(file_b, os.path.basename(file_b),
                    kwargs.pop("name_col_b", None), kwargs.pop("date_col_b", None))
    return reconcile(ta, tb, **kwargs)
