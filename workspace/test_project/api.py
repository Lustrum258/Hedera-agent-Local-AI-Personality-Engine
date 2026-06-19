"""API route handlers"""
import json
import time
from typing import Optional

from framework.app import Request, Response
from framework.auth import AuthManager, Role
from framework.validation import Schema, ValidationError, field, validate_email
from models import Article, Comment


# Global instances
auth = AuthManager(secret="hedera-api-secret-2024")


class CreateArticleSchema(Schema):
    title = field(required=True, type=str, min_length=1, max_length=200)
    content = field(required=True, type=str, min_length=1)
    status = field(default="draft", enum=["draft", "published"])


class UpdateArticleSchema(Schema):
    title = field(type=str, min_length=1, max_length=200)
    content = field(type=str, min_length=1)
    status = field(enum=["draft", "published", "archived"])


class CreateUserSchema(Schema):
    username = field(required=True, type=str, min_length=3, max_length=30)
    email = field(required=True, type=str, validator=validate_email)
    password = field(required=True, type=str, min_length=8)


class LoginSchema(Schema):
    username = field(required=True, type=str)
    password = field(required=True, type=str)


def register_user(req: Request) -> Response:
    """POST /api/auth/register"""
    try:
        data = CreateUserSchema.validate(json.loads(req.body))
    except (json.JSONDecodeError, ValidationError) as e:
        return Response(status=400, body={"error": str(e)})
    
    try:
        user = auth.register(data["username"], data["email"], data["password"])
        return Response(status=201, body=user.to_dict())
    except ValueError as e:
        return Response(status=409, body={"error": str(e)})


def login_user(req: Request) -> Response:
    """POST /api/auth/login"""
    try:
        data = LoginSchema.validate(json.loads(req.body))
    except (json.JSONDecodeError, ValidationError) as e:
        return Response(status=400, body={"error": str(e)})
    
    token = auth.login(data["username"], data["password"])
    if not token:
        return Response(status=401, body={"error": "Invalid credentials"})
    return Response(body={"token": token})


def list_articles(req: Request) -> Response:
    """GET /api/articles"""
    page = int(req.query_params.get("page", 1))
    limit = int(req.query_params.get("limit", 20))
    status = req.query_params.get("status", "published")
    
    query = Article.query()
    if status != "all":
        query = query.where("status = ?", status)
    
    total = query.count()
    articles = query.order_by("created_at", desc=True).limit(limit).offset((page - 1) * limit).all()
    
    return Response(body={
        "articles": articles,
        "total": total,
        "page": page,
        "limit": limit,
    })


def get_article(req: Request) -> Response:
    """GET /api/articles/{article_id}"""
    article_id = int(req.path_params["article_id"])
    article = Article.get_by_id(article_id)
    if not article:
        return Response(status=404, body={"error": "Article not found"})
    return Response(body=article)


def create_article(req: Request) -> Response:
    """POST /api/articles"""
    try:
        data = CreateArticleSchema.validate(json.loads(req.body))
    except (json.JSONDecodeError, ValidationError) as e:
        return Response(status=400, body={"error": str(e)})
    
    from utils.helpers import slugify
    article = Article(
        title=data["title"],
        slug=slugify(data["title"]),
        content=data["content"],
        author_id=getattr(req, "user", {}).get("id", 0),
        status=data.get("status", "draft"),
    )
    article.save()
    return Response(status=201, body={"id": article.id, "slug": article.slug})


def update_article(req: Request) -> Response:
    """PUT /api/articles/{article_id}"""
    article_id = int(req.path_params["article_id"])
    article = Article.get_by_id(article_id)
    if not article:
        return Response(status=404, body={"error": "Article not found"})
    
    try:
        data = UpdateArticleSchema.validate(json.loads(req.body))
    except (json.JSONDecodeError, ValidationError) as e:
        return Response(status=400, body={"error": str(e)})
    
    Article.query().where("id = ?", article_id).update(**data)
    return Response(body={"status": "updated"})


def delete_article(req: Request) -> Response:
    """DELETE /api/articles/{article_id}"""
    article_id = int(req.path_params["article_id"])
    if not Article.get_by_id(article_id):
        return Response(status=404, body={"error": "Article not found"})
    Article.delete_by_id(article_id)
    return Response(body={"status": "deleted"})


def list_comments(req: Request) -> Response:
    """GET /api/articles/{article_id}/comments"""
    article_id = int(req.path_params["article_id"])
    comments = Comment.query().where("article_id = ?", article_id).order_by("created_at").all()
    return Response(body={"comments": comments})


def add_comment(req: Request) -> Response:
    """POST /api/articles/{article_id}/comments"""
    article_id = int(req.path_params["article_id"])
    if not Article.get_by_id(article_id):
        return Response(status=404, body={"error": "Article not found"})
    
    try:
        data = json.loads(req.body)
        content = data.get("content", "").strip()
        if not content:
            return Response(status=400, body={"error": "Content is required"})
    except json.JSONDecodeError:
        return Response(status=400, body={"error": "Invalid JSON"})
    
    comment = Comment(
        article_id=article_id,
        author_id=getattr(req, "user", {}).get("id", 0),
        content=content,
        parent_id=data.get("parent_id"),
    )
    comment.save()
    return Response(status=201, body={"id": comment.id})
