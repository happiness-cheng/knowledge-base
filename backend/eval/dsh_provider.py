"""DSH 自带 DeepSeek 通道（供生成层评测用）。

## 为什么单独一个文件
项目自己的 `claude_client` 走 Anthropic Messages API（cc-switch / sg.api.zhizengzeng.com），
两者现在都不可用（余额=0 / 连不上）。本模块提供一条**独立可用**的通道：
    OpenAI 兼容接口 + DSH 的 DeepSeek 平台密钥（~/.dsh/.credentials.yaml 的 refs）

## ⚠️ 成本交底（务必知道）
这个密钥是**用户 DeepSeek 官方平台的个人账号**（issuer: platform.deepseek.com），
调用会消耗**用户自己的账户额度**。它不是"免费额度"。
生成层评测的粗略用量：44 条用例 × (1 次生成 + 约 5 次判定) ≈ 260 次调用。

## 踩过的坑
`openai.OpenAI` / `httpx` 默认 trust_env=True，构造时读 NO_PROXY。本机 NO_PROXY 含
`[::1]`，httpx 会生成畸形模式 `all://*[::1]` → `httpx.InvalidURL: Invalid port: ':1]'`。
所以**必须在构造 client 之前**调用 `app.env_sanitize.sanitize_no_proxy()`。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# 直接运行本文件时（python eval/dsh_provider.py），backend 不在 sys.path 里，
# 需要补上才能 `from app...` 导入
_BACKEND = Path(__file__).resolve().parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.env_sanitize import sanitize_no_proxy  # noqa: E402

CRED_PATH = Path.home() / '.dsh' / '.credentials.yaml'
BASE_URL = 'https://api.deepseek.com'
GEN_MODEL = 'deepseek-flash'      # 生成用便宜的
JUDGE_MODEL = 'deepseek-v4-pro'   # 判定用更强的（避免"自己评自己"的偏好偏差）


def load_key() -> str:
    import yaml
    data = yaml.safe_load(CRED_PATH.read_text(encoding='utf-8'))
    key = (data.get('refs') or {}).get('DEEPSEEK_API_KEY', '')
    if not key:
        raise RuntimeError(f'未在 {CRED_PATH} 找到 DEEPSEEK_API_KEY')
    return key


_client = None


def get_client():
    """返回 OpenAI 兼容客户端。首次调用时才构造（并先净化环境）。"""
    global _client
    if _client is None:
        sanitize_no_proxy()
        from openai import OpenAI
        _client = OpenAI(api_key=load_key(), base_url=BASE_URL)
    return _client


def make_caller(model: str, max_tokens: int = 4096):
    """返回 (system, user) -> str 的调用器，可直接喂给 generation_eval 的 judge/generator。

    ## max_tokens 为什么必须给大（2026-10-10 实测，静默失败陷阱）
    DeepSeek 这两个模型的 completion token 计数**远大于可见输出**：
      输出只有 284 字符的 JSON，却消耗 844 completion_tokens（v4-pro），
      flash 更是超过 1024 —— 说明有**不计入 content 的 token 消耗**（推理/思考流）。
    后果：max_tokens 给小了会 `finish_reason='length'` 且 **content 为空字符串**
    （不是被截断的半截 JSON），spy 不出异常，指标直接变 None。
    所以这里默认 4096，并在 content 为空时**显式抛错**而不是返回空串。
    """
    client = get_client()

    def call(system: str, user: str) -> str:
        resp = client.chat.completions.create(
            model=model,
            max_tokens=max_tokens,
            temperature=0,                      # 评测要可复现
            messages=[{'role': 'system', 'content': system},
                      {'role': 'user', 'content': user}],
        )
        ch = resp.choices[0]
        content = ch.message.content or ''
        if not content:
            # 静默失败必须变成显式失败，否则指标会变成 None 而看不出原因
            raise RuntimeError(
                f'empty content: model={model} finish_reason={ch.finish_reason} '
                f'completion_tokens={resp.usage.completion_tokens} '
                f'(max_tokens={max_tokens})')
        return content
    call.model = model                      # 便于日志标注
    return call


if __name__ == '__main__':
    for m in (GEN_MODEL, JUDGE_MODEL):
        import time
        t0 = time.perf_counter()
        try:
            out = make_caller(m)('只输出 JSON: {"ok":true}', '测试')
            print(f'  {m:<18} OK {time.perf_counter() - t0:.1f}s  {out.strip()[:60]!r}')
        except Exception as e:
            print(f'  {m:<18} FAIL {type(e).__name__}: {str(e)[:140]}')
