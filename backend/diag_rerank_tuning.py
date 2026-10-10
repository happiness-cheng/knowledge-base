"""Rerank 降本实验：找出可上线的配置。

上一轮：单对长文档(480token) 1527ms × 12 候选 ≈ 18s/query → 不可上线。
四个降本旋钮：
  1. max_length：512 → 256/128。Cross-Encoder 的算量随序列长度平方增长，
     截断能显著降本，但可能损失精度（末尾信息看不到）
  2. torch 线程数：CPU 上默认线程数=核数，长序列下线程争抢反而更慢
  3. 候选数 N：线性降本
  4. 是否只对"向量分接近"的候选做重排（分诊），而不是全量重排

本脚本只测**延迟**（精度由 exp_rerank.py 负责），用真实块文本。
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

from app.utils.markdown_cleaner import split_by_headings  # noqa: E402
import importlib.util  # noqa: E402

spec = importlib.util.spec_from_file_location('ev3', BASE / 'eval' / 'eval_set_v3.py')
ev3 = importlib.util.module_from_spec(spec)
sys.modules['ev3'] = ev3
spec.loader.exec_module(ev3)
nodes = ev3.load_notes()

# 取真实块（node5 的 8 块，典型 480 token 量级）
real_chunks = [b for h, b in split_by_headings(nodes[5][1])]
QUERY = "监控服务为什么用无锁计数器而不是互斥锁"
print(f'真实块 {len(real_chunks)} 个，字符数 {[len(c) for c in real_chunks]}')

import torch  # noqa: E402
from sentence_transformers import CrossEncoder  # noqa: E402

print(f'torch 默认线程数 = {torch.get_num_threads()}')


def bench(ce, pairs, batch_size=32, repeat=3):
    ce.predict(pairs[:2], show_progress_bar=False)          # 预热
    ts = []
    for _ in range(repeat):
        t0 = time.perf_counter()
        ce.predict(pairs, batch_size=batch_size, show_progress_bar=False)
        ts.append((time.perf_counter() - t0) * 1000)
    return statistics.median(ts)


print('\n=== 旋钮1：max_length（候选=全部 8 个真实块）===')
for ml in (512, 256, 128, 64):
    ce = CrossEncoder('BAAI/bge-reranker-v2-m3', max_length=ml)
    pairs = [(QUERY, c) for c in real_chunks]
    ms = bench(ce, pairs)
    print(f'  max_length={ml:<4} 8 对共 {ms:>7.0f}ms   单对 {ms / len(pairs):>6.0f}ms')

print('\n=== 旋钮2：torch 线程数（max_length=512）===')
ce = CrossEncoder('BAAI/bge-reranker-v2-m3', max_length=512)
pairs = [(QUERY, c) for c in real_chunks]
for nt in (torch.get_num_threads(), 8, 4, 2, 1):
    torch.set_num_threads(nt)
    ms = bench(ce, pairs)
    print(f'  threads={nt:<3} 8 对共 {ms:>7.0f}ms   单对 {ms / len(pairs):>6.0f}ms')
torch.set_num_threads(torch.get_num_threads())

print('\n=== 旋钮3：候选数（max_length=256, threads=4）===')
torch.set_num_threads(4)
ce = CrossEncoder('BAAI/bge-reranker-v2-m3', max_length=256)
for n in (3, 6, 8, 12):
    p = [(QUERY, c) for c in (real_chunks * 3)[:n]]
    ms = bench(ce, p)
    print(f'  N={n:<3} 共 {ms:>7.0f}ms   单对 {ms / n:>6.0f}ms   → 单 query 估算 {ms:.0f}ms')
