"""拆解 Rerank 的延迟构成，找可接受的落地形态。

上一轮实测中位延迟 ~20s/query，这不可能上线。拆解：
  · 模型加载（一次性）
  · 每次 predict 的固定开销（是否每次都在重建 DataLoader / 是否记录进度条）
  · 单对 (query,doc) 的前向成本
  · 候选数 N 的线性关系

并测三个降本方向：
  1. 候选数从 12 降到 6/8（线性降本）
  2. batch_size 显式设置
  3. **把同一轮多 query 合成一次 predict**（CrossEncoder 支持 list of pairs，批量更划算）
"""
import os
import statistics
import sys
import time
from pathlib import Path

BASE = Path(r'C:/Users/陈独秀/knowledge-base/backend')
sys.path.insert(0, str(BASE))
sys.stdout.reconfigure(encoding='utf-8')
os.environ.setdefault('HF_HUB_OFFLINE', '1')
os.environ.setdefault('TRANSFORMERS_OFFLINE', '1')

import importlib.util  # noqa: E402

from sentence_transformers import CrossEncoder  # noqa: E402

spec = importlib.util.spec_from_file_location('ev3', BASE / 'eval' / 'eval_set_v3.py')
ev3 = importlib.util.module_from_spec(spec)
sys.modules['ev3'] = ev3
spec.loader.exec_module(ev3)

QUERY = "为什么要三次握手，两次为什么不行"
DOC_SHORT = "三次刚好让双方都确认了彼此的收发能力。两次不够，四次多余。"
DOC_LONG = ("select/poll/epoll 是什么。它们都解决同一个问题：一个线程同时监控多个 fd，"
            "哪个有数据就处理哪个。" * 12)

t0 = time.perf_counter()
ce = CrossEncoder('BAAI/bge-reranker-v2-m3', max_length=512)
print(f'模型加载（一次性）: {time.perf_counter() - t0:.2f}s')

# 预热：排除首次前向的惰性初始化
ce.predict([(QUERY, DOC_SHORT)], show_progress_bar=False)

print('\n=== 单对前向成本 ===')
for label, doc in (('短文档(~40字)', DOC_SHORT), ('长文档(~500字)', DOC_LONG)):
    ts = []
    for _ in range(3):
        t0 = time.perf_counter()
        ce.predict([(QUERY, doc)], show_progress_bar=False)
        ts.append((time.perf_counter() - t0) * 1000)
    print(f'  {label:<16} 单对 {statistics.median(ts):.0f}ms')

print('\n=== 候选数 N 的总耗时（一次 predict，单 query）===')
for n in (3, 6, 12, 24):
    pairs = [(QUERY, DOC_SHORT)] * n
    ts = []
    for _ in range(3):
        t0 = time.perf_counter()
        ce.predict(pairs, show_progress_bar=False)
        ts.append((time.perf_counter() - t0) * 1000)
    per = statistics.median(ts) / n
    print(f'  N={n:<3} 总 {statistics.median(ts):>7.0f}ms   单对均摊 {per:>6.0f}ms')

print('\n=== batch_size 影响（N=12）===')
pairs = [(QUERY, DOC_SHORT)] * 12
for bs in (1, 4, 8, 16, 32):
    ts = []
    for _ in range(3):
        t0 = time.perf_counter()
        ce.predict(pairs, batch_size=bs, show_progress_bar=False)
        ts.append((time.perf_counter() - t0) * 1000)
    print(f'  batch_size={bs:<3} {statistics.median(ts):>7.0f}ms')

print('\n=== 批量跨 query：44 条 query × 12 候选 = 528 对，分几次 predict ===')
all_pairs = [(QUERY, DOC_SHORT)] * 528
t0 = time.perf_counter()
ce.predict(all_pairs, batch_size=32, show_progress_bar=False)
total = time.perf_counter() - t0
print(f'  528 对一次跑完 {total:.1f}s  → 每 query(12候选) 均摊 {total / 44 * 1000:.0f}ms')
