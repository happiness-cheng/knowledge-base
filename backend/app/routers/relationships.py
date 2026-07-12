from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.node import KnowledgeNode
from app.models.relationship import Relationship
from app.models.user import User
from app.auth import get_current_user
from app.schemas.relationship import RelationshipCreate, RelationshipOut

router = APIRouter(prefix="/relationships", tags=["relationships"])


@router.get("", response_model=list[RelationshipOut])
def list_relationships(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return db.query(Relationship).filter(Relationship.user_id == current_user.id).all()


@router.post("", response_model=RelationshipOut)
def create_relationship(body: RelationshipCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    node_ids = {body.source_id, body.target_id}
    owned_node_ids = {
        node_id
        for (node_id,) in db.query(KnowledgeNode.id).filter(
            KnowledgeNode.id.in_(node_ids),
            KnowledgeNode.user_id == current_user.id,
        )
    }
    if owned_node_ids != node_ids:
        raise HTTPException(404, "Node not found")

    rel = Relationship(
        user_id=current_user.id,
        source_id=body.source_id,
        target_id=body.target_id,
        source_topic=body.source_topic,
        target_topic=body.target_topic,
        rel_type=body.rel_type,
        label=body.label,
    )
    db.add(rel)
    db.commit()
    db.refresh(rel)
    return rel


@router.delete("/{rel_id}")
def delete_relationship(rel_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    rel = db.query(Relationship).filter(Relationship.id == rel_id, Relationship.user_id == current_user.id).first()
    if not rel:
        raise HTTPException(404, "Relationship not found")
    db.delete(rel)
    db.commit()
    return {"ok": True}
