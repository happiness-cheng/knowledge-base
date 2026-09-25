"""knowledge-base RAG 评测：语料导入 + 评测集 + 分层评测脚本
三类文档：本地短笔记(SQLite 12条) + 长文档(项目真实md) + 外部语料(GitHub CS知识库)
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')

CHROMA_BACKUP = True

def backup_chroma():
    """重嵌入前备份 chroma_db"""
    import shutil, os
    src = 'chroma_db'
    dst = 'chroma_db_backup_20260909'
    if not os.path.exists(dst):
        shutil.copytree(src, dst)
        print(f'已备份 {src} → {dst}')
    else:
        print(f'备份已存在: {dst}')


if __name__ == '__main__':
    backup_chroma()
