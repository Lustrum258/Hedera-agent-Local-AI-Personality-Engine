"""Application models"""
from dataclasses import dataclass, field
from typing import Optional
import time

from framework.database import Model, Field


@dataclass
class Article(Model):
    __tablename__ = "articles"
    
    id: Optional[int] = field(default=None, metadata={"field": Field(col_type="INTEGER", primary_key=True)})
    title: str = field(default="", metadata={"field": Field(col_type="TEXT", nullable=False)})
    slug: str = field(default="", metadata={"field": Field(col_type="TEXT", unique=True)})
    content: str = field(default="", metadata={"field": Field(col_type="TEXT")})
    author_id: int = field(default=0, metadata={"field": Field(col_type="INTEGER", nullable=False)})
    status: str = field(default="draft", metadata={"field": Field(col_type="TEXT", default="draft")})
    view_count: int = field(default=0, metadata={"field": Field(col_type="INTEGER", default="0")})
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def publish(self):
        self.status = "published"
        self.updated_at = time.time()

    def increment_views(self):
        self.view_count += 1


@dataclass 
class Comment(Model):
    __tablename__ = "comments"
    
    id: Optional[int] = field(default=None, metadata={"field": Field(col_type="INTEGER", primary_key=True)})
    article_id: int = field(default=0, metadata={"field": Field(col_type="INTEGER", nullable=False)})
    author_id: int = field(default=0, metadata={"field": Field(col_type="INTEGER", nullable=False)})
    content: str = field(default="", metadata={"field": Field(col_type="TEXT", nullable=False)})
    parent_id: Optional[int] = field(default=None, metadata={"field": Field(col_type="INTEGER")})
    created_at: float = field(default_factory=time.time)

    def is_reply(self) -> bool:
        return self.parent_id is not None
