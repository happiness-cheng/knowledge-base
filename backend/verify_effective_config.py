"""回读验证：`.env` 里的配置到底有没有生效（防"配置静默失效"）。

为什么必须有它：`.env` 有值 ≠ 代码读到了。本项目踩过两层：
  1. pydantic-settings 只把 .env 读进 Settings 对象，**不写 os.environ**
  2. rag_service 直接读 os.environ ⇒ 读到空值仍不报错，只是悄悄用旧集合
症状是"看起来配好了，实际没生效"，且没有任何异常。所以必须**打印实际生效值**。
"""
import sys
from pathlib import Path

BASE = Path(r'C:/Users/陈独秀/knowledge-base/backend')
sys.path.insert(0, str(BASE))
sys.stdout.reconfigure(encoding='utf-8')

from app import env_sanitize  # noqa: E402  触发 load_dotenv_keys / sanitize
from app.services import rag_service  # noqa: E402

print('=' * 64)
print('环境变量层')
print(f'  .env 文件路径            : {BASE / ".env"}')
print(f'  .env 存在                : {(BASE / ".env").exists()}')
print(f'  os.environ[NO_PROXY]     : {env_sanitize.os.environ.get("NO_PROXY")!r}')
print(f'  os.environ[HF_HUB_OFFLINE]: {env_sanitize.os.environ.get("HF_HUB_OFFLINE")!r}')

print('=' * 64)
print('业务层（rag_service 实际读到的值）')
print(f'  KB_CHROMA_SUFFIX 常量名  : {rag_service.KB_CHROMA_SUFFIX_ENV}')
print(f'  实际生效后缀 _SUFFIX     : {rag_service._SUFFIX!r}   ← 空字符串=回退旧集合')
print(f'  生效集合名               : {rag_service.get_collection_name(1)}')

col = rag_service._get_user_collection(1)
print(f'  集合实际 count           : {col.count()}')
print(f'  集合是否存在（读一次）   : {"是" if col.count() >= 0 else "否"}')

expect = (BASE / '.env').read_text(encoding='utf-8')
expect_val = ''
for line in expect.splitlines():
    if line.strip().startswith('KB_CHROMA_SUFFIX='):
        expect_val = line.split('=', 1)[1].strip()
print('=' * 64)
print(f'.env 期望值 = {expect_val!r}   实际生效 = {rag_service._SUFFIX!r}')
print('判定：', '✅ 一致，配置已生效' if expect_val == rag_service._SUFFIX
      else '❌ 不一致 —— 配置没生效，别以为改好了')
