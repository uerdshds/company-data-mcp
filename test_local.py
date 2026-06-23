"""本地验证核心匹配逻辑 (不依赖 MCP / DEAP)。

用法:
    .venv/Scripts/python.exe test_local.py
    .venv/Scripts/python.exe test_local.py 路径A 路径B --tol 1 --threshold 85
"""
import argparse
import json
import os

from matcher import reconcile_files

HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("file_a", nargs="?", default=os.path.join(HERE, "samples", "table_a.csv"))
    ap.add_argument("file_b", nargs="?", default=os.path.join(HERE, "samples", "table_b.csv"))
    ap.add_argument("--threshold", type=int, default=85)
    ap.add_argument("--tol", type=int, default=0, help="日期容差天数")
    ap.add_argument("--strip-suffix", action="store_true", help="比对时剥离公司组织形式后缀")
    args = ap.parse_args()

    res = reconcile_files(
        args.file_a, args.file_b,
        name_threshold=args.threshold,
        date_tolerance_days=args.tol,
        strip_suffix=args.strip_suffix,
    )

    print("=== 汇总 ===")
    print(json.dumps(res.summary, ensure_ascii=False, indent=2))
    for title, items in (("已匹配", res.matched), ("待复核", res.to_review), ("未匹配", res.unmatched)):
        print(f"\n=== {title} ({len(items)}) ===")
        for it in items:
            print(json.dumps(it, ensure_ascii=False))


if __name__ == "__main__":
    main()
