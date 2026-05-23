from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.database import get_db
from app.models.tag import Tag
from app.models.user import User
from app.models.node import node_tags
from app.auth import get_current_user
from app.schemas.tag import TagCreate, TagOut

router = APIRouter(prefix="/tags", tags=["tags"])


@router.get("", response_model=list[TagOut])
def list_tags(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    rows = (
        db.query(Tag, func.count(node_tags.c.node_id).label("node_count"))
        .outerjoin(node_tags, Tag.id == node_tags.c.tag_id)
        .filter(Tag.user_id == current_user.id)
        .group_by(Tag.id)
        .all()
    )
    return [TagOut(id=tag.id, name=tag.name, color=tag.color, is_ai_generated=tag.is_ai_generated, node_count=count)
        for tag, count in rows]


@router.post("", response_model=TagOut)
def create_tag(body: TagCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    existing = db.query(Tag).filter(Tag.name == body.name, Tag.user_id == current_user.id).first()
    if existing:
        raise HTTPException(409, f"Tag '{body.name}' already exists")
    tag = Tag(name=body.name, color=body.color, user_id=current_user.id)
    db.add(tag)
    db.commit()
    db.refresh(tag)
    return TagOut(id=tag.id, name=tag.name, color=tag.color, is_ai_generated=tag.is_ai_generated, node_count=0)


@router.delete("/{tag_id}")
def delete_tag(tag_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    tag = db.query(Tag).filter(Tag.id == tag_id, Tag.user_id == current_user.id).first()
    if not tag:
        raise HTTPException(404, "Tag not found")
    db.delete(tag)
    db.commit()
    return {"ok": True}
