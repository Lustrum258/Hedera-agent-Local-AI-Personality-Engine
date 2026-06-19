"""Authentication & Authorization middleware"""
import hashlib
import hmac
import json
import time
from typing import Callable, Dict, List, Optional, Set
from dataclasses import dataclass, field


@dataclass
class User:
    id: int
    username: str
    email: str
    password_hash: str
    roles: Set[str] = field(default_factory=set)
    is_active: bool = True
    created_at: float = field(default_factory=time.time)
    last_login: Optional[float] = None

    def check_password(self, password: str) -> bool:
        return hash_password(password) == self.password_hash

    def has_role(self, role: str) -> bool:
        return role in self.roles

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "username": self.username,
            "email": self.email,
            "roles": list(self.roles),
            "is_active": self.is_active,
            "created_at": self.created_at,
        }


def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


def verify_token(token: str, secret: str) -> Optional[Dict]:
    """Simple token verification (not JWT, just for testing)"""
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None
        header_b64, payload_b64, signature = parts
        expected = hmac.new(
            secret.encode(),
            f"{header_b64}.{payload_b64}".encode(),
            hashlib.sha256
        ).hexdigest()[:32]
        if not hmac.compare_digest(signature, expected):
            return None
        import base64
        payload = json.loads(base64.urlsafe_b64decode(payload_b64 + "=="))
        if payload.get("exp", 0) < time.time():
            return None
        return payload
    except Exception:
        return None


class Permission:
    READ = "read"
    WRITE = "write"
    DELETE = "delete"
    ADMIN = "admin"


class Role:
    USER = "user"
    EDITOR = "editor"
    ADMIN = "admin"

    DEFAULT_PERMISSIONS = {
        USER: {Permission.READ},
        EDITOR: {Permission.READ, Permission.WRITE},
        ADMIN: {Permission.READ, Permission.WRITE, Permission.DELETE, Permission.ADMIN},
    }


class AuthManager:
    def __init__(self, secret: str = "hedera-secret-key"):
        self.secret = secret
        self._users: Dict[int, User] = {}
        self._tokens: Dict[str, Dict] = {}  # token -> payload
        self._rate_limits: Dict[str, List[float]] = {}
        self._max_requests_per_minute = 60

    def register(self, username: str, email: str, password: str, roles: Set[str] = None) -> User:
        # Check duplicate
        for u in self._users.values():
            if u.username == username:
                raise ValueError(f"Username '{username}' already exists")
            if u.email == email:
                raise ValueError(f"Email '{email}' already registered")

        user_id = len(self._users) + 1
        user = User(
            id=user_id,
            username=username,
            email=email,
            password_hash=hash_password(password),
            roles=roles or {Role.USER},
        )
        self._users[user_id] = user
        return user

    def login(self, username: str, password: str) -> Optional[str]:
        user = None
        for u in self._users.values():
            if u.username == username:
                user = u
                break
        if not user or not user.check_password(password):
            return None
        if not user.is_active:
            return None

        import base64
        header = base64.urlsafe_b64encode(json.dumps({"alg": "HS256"}).encode()).decode().rstrip("=")
        payload_data = {"sub": user.id, "username": user.username, "roles": list(user.roles), "exp": time.time() + 3600}
        payload = base64.urlsafe_b64encode(json.dumps(payload_data).encode()).decode().rstrip("=")
        signature = hmac.new(self.secret.encode(), f"{header}.{payload}".encode(), hashlib.sha256).hexdigest()[:32]

        token = f"{header}.{payload}.{signature}"
        self._tokens[token] = payload_data
        user.last_login = time.time()
        return token

    def verify(self, token: str) -> Optional[User]:
        payload = verify_token(token, self.secret)
        if not payload:
            return None
        user_id = payload.get("sub")
        user = self._users.get(user_id)
        if not user or not user.is_active:
            return None
        return user

    def check_rate_limit(self, user_id: int) -> bool:
        key = str(user_id)
        now = time.time()
        if key not in self._rate_limits:
            self._rate_limits[key] = []
        # Clean old entries
        self._rate_limits[key] = [t for t in self._rate_limits[key] if now - t < 60]
        if len(self._rate_limits[key]) >= self._max_requests_per_minute:
            return False
        self._rate_limits[key].append(now)
        return True

    def require_permission(self, permission: str):
        """Decorator factory for permission checking"""
        def decorator(fn: Callable):
            def wrapper(request, *args, **kwargs):
                auth_header = request.headers.get("Authorization", "")
                if not auth_header.startswith("Bearer "):
                    return {"error": "Unauthorized"}, 401
                token = auth_header[7:]
                user = self.verify(token)
                if not user:
                    return {"error": "Invalid token"}, 401
                if not self.check_rate_limit(user.id):
                    return {"error": "Rate limit exceeded"}, 429
                user_permissions = set()
                for role in user.roles:
                    user_permissions |= Role.DEFAULT_PERMISSIONS.get(role, set())
                if permission not in user_permissions and Permission.ADMIN not in user_permissions:
                    return {"error": "Forbidden"}, 403
                request.user = user
                return fn(request, *args, **kwargs)
            return wrapper
        return decorator

    def get_user(self, user_id: int) -> Optional[User]:
        return self._users.get(user_id)

    def list_users(self) -> List[User]:
        return list(self._users.values())

    def deactivate_user(self, user_id: int) -> bool:
        user = self._users.get(user_id)
        if user:
            user.is_active = False
            return True
        return False
