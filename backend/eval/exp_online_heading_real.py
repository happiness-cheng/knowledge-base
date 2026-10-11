import importlib.util, sys
from pathlib import Path
from collections import Counter
_B = Path(r"C:/Users/陈独秀/knowledge-base/backend")
sys.path.insert(0, str(_B)); sys.path.insert(0, str(_B/"eval"))
import _bootstrap
sys.stdout.reconfigure(encoding="utf-8")
import numpy as np
from app.services import rag_service
from app.utils.markdown_cleaner import split_by_headings
spec = importlib.util.spec_from_file_location("ev3", _B/"eval"/"eval_set_v3.py")
ev3 = importlib.util.module_from_spec(spec); sys.modules["ev3"]=ev3; spec.loader.exec_module(ev3)

col = rag_service.chroma_client.get_collection(name=rag_service.get_collection_name(1,"_prod"))
d = col.get(include=["documents","metadatas"]); metas, docs = d["metadatas"], d["documents"]
model = rag_service._get_model()
hc = Counter(m.get("heading","") for m in metas)
GEN = {h for h,c in hc.items() if c>=2 and h}
print("真实语料里的通用 heading:", {h:hc[h] for h in GEN})

T=[m.get("title","") for m in metas]; H=[m.get("heading","") for m in metas]
def enc(mode):
    if mode=="A": tx=[f"{t}\n{h}\n{b}" if t else f"{h}\n{b}" for t,h,b in zip(T,H,docs)]
    elif mode=="B": tx=[f"{t}\n{b}" if t else b for t,b in zip(T,docs)]
    elif mode=="D": tx=[f"{t}\n{b}" if h in GEN else (f"{t}\n{h}\n{b}" if t else f"{h}\n{b}") for t,h,b in zip(T,H,docs)]
    return np.asarray(model.encode(tx, normalize_embeddings=True, show_progress_bar=False), dtype=np.float32)
E={m:enc(m) for m in "ABD"}

def retr(mode, q, top_k=5, cpn=2):
    qv=np.asarray(rag_service.get_query_embedding(q),dtype=np.float32)
    dist=np.linalg.norm(E[mode]-qv[None,:],axis=1); order=np.argsort(dist)
    g,s={},[]
    for i in order:
        n=metas[i]["node_id"]
        if len(g.get(n,[]))>=cpn: continue
        if n not in g: g[n]=[]; s.append(n)
        g[n].append(int(i))
        if len(s)>=top_k and all(len(g[x])>=cpn for x in s[:top_k]): break
    out=[]
    for n in s[:top_k]:
        for i in g[n]: out.append((n, metas[i].get("chunk_index")))
    return out
notes=ev3.load_notes(); sc={nid: split_by_headings(c) for nid,(t,c) in notes.items()}
print()
print(f'{"变体":<22}{"答案块进上下文":<18}{"node Hit@1":<13}{"MRR"}')
print("-"*62)
for mode in "ABD":
    ch=h1=0; n=0; mrr=0.0
    for cid,nid,ntype,qsrc,q,head,tail in ev3.CASES:
        if nid is None: continue
        n+=1; want=ev3.verify_evidence(sc[nid],head,tail)
        res=retr(mode,q)
        if (nid,want) in res: ch+=1
        seen=[]
        for nid2,_ in res:
            if nid2 not in seen: seen.append(nid2)
        r = seen.index(nid)+1 if nid in seen else None
        if r==1: h1+=1
        if r: mrr += 1/r
    print(f'{mode:<22}{ch}/{n} = {ch/n:.3f}      {h1}/{n}{"":<8}{mrr/n:.4f}')
