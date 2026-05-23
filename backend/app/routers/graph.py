from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session, joinedload
from app.database import get_db
from app.models.node import KnowledgeNode
from app.models.relationship import Relationship
from app.models.user import User
from app.auth import get_current_user
from app.schemas.graph import GraphData, GraphNode, GraphLink

router = APIRouter(prefix="/graph", tags=["graph"])


@router.get("", response_model=GraphData)
def get_graph(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    nodes = db.query(KnowledgeNode).options(joinedload(KnowledgeNode.tags)).filter(
        KnowledgeNode.user_id == current_user.id).all()
    rels = db.query(Relationship).filter(Relationship.user_id == current_user.id).all()
    graph_nodes = [GraphNode(id=n.id, title=n.title, category=n.category, tags=[t.name for t in n.tags], importance=n.importance) for n in nodes]
    graph_links = [GraphLink(source=r.source_id, target=r.target_id, source_topic=r.source_topic, target_topic=r.target_topic, rel_type=r.rel_type, label=r.label) for r in rels]
    return GraphData(nodes=graph_nodes, links=graph_links)


@router.get("/node/{node_id}", response_model=GraphData)
def get_subgraph(node_id: int, hops: int = Query(1, ge=1, le=3),
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    node_ids = {node_id}
    for _ in range(hops):
        rels = db.query(Relationship).filter(
            Relationship.user_id == current_user.id,
            (Relationship.source_id.in_(node_ids)) | (Relationship.target_id.in_(node_ids))
        ).all()
        for r in rels:
            node_ids.add(r.source_id)
            node_ids.add(r.target_id)
    nodes = db.query(KnowledgeNode).filter(
        KnowledgeNode.id.in_(node_ids), KnowledgeNode.user_id == current_user.id
    ).all()
    graph_nodes = [GraphNode(id=n.id, title=n.title, category=n.category, tags=[t.name for t in n.tags], importance=n.importance) for n in nodes]
    graph_links = [GraphLink(source=r.source_id, target=r.target_id, source_topic=r.source_topic, target_topic=r.target_topic, rel_type=r.rel_type, label=r.label) for r in rels]
    return GraphData(nodes=graph_nodes, links=graph_links)
