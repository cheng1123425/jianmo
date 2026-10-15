# -*- coding: utf-8 -*-
r"""Zero-to-CAD 100k —— 只抓【文本列】的抽取器（独立工具，不接项目主干）。

背景：全量在 HF `ADSKAILab/Zero-To-CAD-100k`（28.3GB / 210 分片）。
但"挖算子"只需 `cadquery_ops_json` 一列（占全量 ~0.3%）。

做法：走 hf-mirror + pyarrow【列投影】(HTTP Range)，逐分片只拉需要的列，
合并成本地一个轻量 parquet（~65–90MB），再交给 tools/z2c_mine_ops.py 统计。

用法：
  python tools/z2c_fetch_ops.py --out 验证报告/z2c_ops_only.parquet
"""
import argparse
import concurrent.futures as cf
import json
import os
import sys
import time

import fsspec
import pyarrow as pa
import pyarrow.parquet as pq

META = "验证报告/z2c_100k.json"          # HF 元数据卡（含分片清单）
BASE = "https://hf-mirror.com/datasets/ADSKAILab/Zero-To-CAD-100k/resolve/main/"
COLS = ["uuid", "cadquery_ops_json", "cadquery_ops_count"]

RETRY = 3
BLOCK = 1 << 18   # 256KB 块（实测最优：1MB 块反而更慢）
WORKERS = 4       # 实测最优并发；>4 会被 hf-mirror 限流


def list_shards():
    d = json.load(open(META, encoding="utf-8"))
    return [s["rfilename"] for s in d.get("siblings", [])
            if isinstance(s, dict) and s.get("rfilename", "").endswith(".parquet")]


def fetch_one(fs, name):
    url = BASE + name
    last = None
    for k in range(RETRY):
        try:
            with fs.open(url, "rb") as f:
                t = pq.read_table(f, columns=COLS)
            return name, t
        except Exception as e:                      # noqa: BLE001
            last = e
            time.sleep(1.5 * (k + 1))
    return name, last


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="验证报告/z2c_ops_only.parquet")
    ap.add_argument("--workers", type=int, default=WORKERS)
    ap.add_argument("--limit", type=int, default=0, help="只跑前 N 个分片(调试用)")
    a = ap.parse_args()

    shards = list_shards()
    if a.limit:
        shards = shards[:a.limit]
    print("[fetch] 分片数: %d（列: %s）" % (len(shards), COLS), flush=True)

    fs = fsspec.filesystem("http", block_size=BLOCK)
    tables, failed, done, t0 = [], [], 0, time.time()
    with cf.ThreadPoolExecutor(max_workers=a.workers) as ex:
        futs = {ex.submit(fetch_one, fs, s): s for s in shards}
        for fut in cf.as_completed(futs):
            name, res = fut.result()
            done += 1
            if isinstance(res, pa.Table):
                tables.append(res)
            else:
                failed.append((name, str(res)[:80]))
            if done % 20 == 0 or done == len(shards):
                dt = time.time() - t0
                print("[fetch] %d/%d  用时%.0fs  ETA%.0fs  失败%d"
                      % (done, len(shards), dt, dt / done * (len(shards) - done),
                         len(failed)), flush=True)

    if not tables:
        print("[fetch] 全部失败", failed[:5]); sys.exit(1)

    merged = pa.concat_tables(tables, promote_options="default")
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    pq.write_table(merged, a.out, compression="zstd")
    sz = os.path.getsize(a.out)
    print("[fetch] 完成: %d 行 → %s (%.1f MB), 失败 %d 片, 总用时%.0fs"
          % (merged.num_rows, a.out, sz / 1024 / 1024, len(failed), time.time() - t0),
          flush=True)
    if failed:
        print("[fetch] 失败样例:", failed[:5], flush=True)


if __name__ == "__main__":
    main()
