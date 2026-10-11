import importlib.util, sys
from pathlib import Path
_B = Path(r"C:/Users/陈独秀/knowledge-base/backend")
sys.path.insert(0, str(_B)); sys.path.insert(0, str(_B/"eval"))
import _bootstrap
sys.stdout.reconfigure(encoding="utf-8")
from app.services import rag_service
from app.utils.markdown_cleaner import split_by_headings
spec = importlib.util.spec_from_file_location("ev3", _B/"eval"/"eval_set_v3.py")
ev3 = importlib.util.module_from_spec(spec); sys.modules["ev3"]=ev3; spec.loader.exec_module(ev3)

notes = ev3.load_notes()
split_cache = {nid: split_by_headings(c) for nid,(t,c) in notes.items()}
col = rag_service.chroma_client.get_collection(name=rag_service.get_collection_name(1, "_prod"))

def run(top_k, cpn):
    rows=[]
    for cid,nid,ntype,qsrc,q,head,tail in ev3.CASES:
        if nid is None: continue
        want = ev3.verify_evidence(split_cache[nid], head, tail)
        res = rag_service.retrieve_relevant_nodes(q, top_k=top_k, user_id=1, chunks_per_node=cpn)
        nodes=[]
        for r in res:
            if r["node_id"] not in nodes: nodes.append(r["node_id"])
        rank = nodes.index(nid)+1 if nid in nodes else None
        ch = any(r["node_id"]==nid and r.get("chunk_index")==want for r in res)
        nchunks = len(res)
        chars = sum(len(r.get("content","")) for r in res)
        rows.append((cid,qsrc,rank,ch,nchunks,chars))
    n=len(rows)
    h1=sum(1 for r in rows if r[2]==1); h3=sum(1 for r in rows if r[2] and r[2]<=3)
    mrr=sum(1/r[2] for r in rows if r[2])/n
    ch=sum(1 for r in rows if r[3])
    return rows, h1,h3,mrr,ch,n

print(f'{"配置":<34}{"Hit@1":<9}{"Hit@3":<9}{"MRR":<9}{"答案块进上下文":<16}{"平均块数":<10}{"平均上下文字符"}')
print("-"*104)
out={}
for top_k, cpn, label in [(3,2,"top_k=3 cpn=2  ← 我的评测一直用这个"),
                          (5,2,"top_k=5 cpn=2  ← **生产默认**"),
                          (5,3,"top_k=5 cpn=3"),
                          (10,2,"top_k=10 cpn=2")]:
    rows,h1,h3,mrr,ch,n = run(top_k,cpn)
    ac = sum(r[4] for r in rows)/n; ac2 = sum(r[5] for r in rows)/n
    print(f'{label:<34}{h1:>3}/{n:<5}{h3:>3}/{n:<5}{mrr:<9.4f}{ch:>3}/{n} = {ch/n:.3f}   {ac:<10.2f}{ac2:.0f}')
    out[(top_k,cpn)]=rows

print()
print("=== 按 query_source 分开看（我写的 query 是否虚高）===")
for top_k,cpn in [(3,2),(5,2)]:
    rows=out[(top_k,cpn)]
    print(f"  top_k={top_k} cpn={cpn}:")
    for src in ("chatlog","personal","authored"):
        sub=[r for r in rows if r[1]==src]
        if not sub: continue
        h1=sum(1 for r in sub if r[2]==1); ch=sum(1 for r in sub if r[3])
        print(f"    {src:<10} n={len(sub):<3} Hit@1 {h1}/{len(sub)}  答案块进上下文 {ch}/{len(sub)}")
print()
print("=== top_k=3 → 5 的逐条变化（只看是否有退化）===")
bad=[]
for a,b in zip(out[(3,2)], out[(5,2)]):
    if a[2]==1 and b[2]!=1: bad.append((a[0],a[1],a[2],b[2]))
    if a[3] and not b[3]: bad.append((a[0],a[1],"块"+str(a[2]),"块丢失"))
print("  退化:", bad if bad else "无")
