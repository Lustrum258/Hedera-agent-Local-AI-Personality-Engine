"""FastAPI-like web framework (simplified for testing)"""
import json
import re
from typing import Callable, Dict, List, Optional, Any
from dataclasses import dataclass, field


@dataclass
class Request:
    method: str
    path: str
    headers: Dict[str, str]
    body: Optional[str] = None
    query_params: Dict[str, str] = field(default_factory=dict)
    path_params: Dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_raw(cls, raw: str) -> "Request":
        lines = raw.split("\r\n")
        first_line = lines[0].split(" ")
        method = first_line[0]
        path = first_line[1] if len(first_line) > 1 else "/"
        
        headers = {}
        body = None
        i = 1
        while i < len(lines):
            if lines[i] == "":
                body = "\r\n".join(lines[i+1:])
                break
            if ":" in lines[i]:
                key, val = lines[i].split(":", 1)
                headers[key.strip()] = val.strip()
            i += 1
        
        # Parse query params
        query_params = {}
        if "?" in path:
            path, qs = path.split("?", 1)
            for pair in qs.split("&"):
                if "=" in pair:
                    k, v = pair.split("=", 1)
                    query_params[k] = v
        
        return cls(method=method, path=path, headers=headers, body=body, query_params=query_params)


@dataclass
class Response:
    status: int = 200
    headers: Dict[str, str] = field(default_factory=lambda: {"Content-Type": "application/json"})
    body: Any = None

    def to_raw(self) -> str:
        status_lines = {200: "OK", 201: "Created", 400: "Bad Request", 404: "Not Found", 500: "Internal Server Error"}
        status_text = status_lines.get(self.status, "Unknown")
        body_str = json.dumps(self.body) if isinstance(self.body, (dict, list)) else str(self.body or "")
        self.headers["Content-Length"] = str(len(body_str.encode()))
        header_lines = "\r\n".join(f"{k}: {v}" for k, v in self.headers.items())
        return f"HTTP/1.1 {self.status} {status_text}\r\n{header_lines}\r\n\r\n{body_str}"


class Middleware:
    def __init__(self):
        self._before: List[Callable] = []
        self._after: List[Callable] = []

    def before(self, fn: Callable):
        self._before.append(fn)
        return fn

    def after(self, fn: Callable):
        self._after.append(fn)
        return fn

    async def run_before(self, req: Request):
        for fn in self._before:
            result = fn(req)
            if isinstance(result, Response):
                return result
        return None

    async def run_after(self, req: Request, resp: Response):
        for fn in self._after:
            resp = fn(req, resp)
        return resp


class Router:
    def __init__(self, prefix: str = ""):
        self.prefix = prefix
        self._routes: Dict[str, Dict[str, Callable]] = {}
        self._middleware = Middleware()
        self._before_middlewares: List[Callable] = []
        self._after_middlewares: List[Callable] = []
        self._error_handlers: Dict[int, Callable] = {}
        self._sub_routers: List["Router"] = []

    def _add_route(self, method: str, path: str, handler: Callable):
        full_path = self.prefix + path
        if full_path not in self._routes:
            self._routes[full_path] = {}
        self._routes[full_path][method.upper()] = handler

    def get(self, path: str):
        def decorator(fn):
            self._add_route("GET", path, fn)
            return fn
        return decorator

    def post(self, path: str):
        def decorator(fn):
            self._add_route("POST", path, fn)
            return fn
        return decorator

    def put(self, path: str):
        def decorator(fn):
            self._add_route("PUT", path, fn)
            return fn
        return decorator

    def delete(self, path: str):
        def decorator(fn):
            self._add_route("DELETE", path, fn)
            return fn
        return decorator

    def include_router(self, router: "Router"):
        self._sub_routers.append(router)

    def middleware(self, fn: Callable):
        self._before_middlewares.append(fn)
        return fn

    def error_handler(self, status_code: int):
        def decorator(fn):
            self._error_handlers[status_code] = fn
            return fn
        return decorator

    def _match_path(self, pattern: str, path: str) -> Optional[Dict[str, str]]:
        # Convert path pattern to regex: /users/{id} -> /users/([^/]+)
        regex = re.sub(r"\{(\w+)\}", r"(?P<\1>[^/]+)", pattern)
        regex = f"^{regex}$"
        match = re.match(regex, path)
        if match:
            return match.groupdict()
        return None

    async def handle(self, request: Request) -> Response:
        # Check own routes
        for pattern, methods in self._routes.items():
            path_params = self._match_path(pattern, request.path)
            if path_params is not None:
                handler = methods.get(request.method)
                if handler:
                    request.path_params = path_params
                    try:
                        # Run before middlewares
                        for mw in self._before_middlewares:
                            result = mw(request)
                            if isinstance(result, Response):
                                return result
                        
                        # Call handler
                        result = handler(request)
                        if isinstance(result, Response):
                            resp = result
                        else:
                            resp = Response(body=result)
                        
                        # Run after middlewares
                        for mw in self._after_middlewares:
                            resp = mw(request, resp)
                        
                        return resp
                    except Exception as e:
                        if 500 in self._error_handlers:
                            return self._error_handlers[500](request, e)
                        return Response(status=500, body={"error": str(e)})
                else:
                    return Response(status=405, body={"error": "Method not allowed"})
        
        # Check sub-routers
        for sub in self._sub_routers:
            if request.path.startswith(sub.prefix):
                resp = await sub.handle(request)
                if resp.status != 404:
                    return resp
        
        return Response(status=404, body={"error": "Not found"})


class App(Router):
    def __init__(self, title: str = "Hedera API", version: str = "1.0.0"):
        super().__init__()
        self.title = title
        self.version = version
        self._startup_hooks: List[Callable] = []
        self._shutdown_hooks: List[Callable] = []
        self._exception_handlers: Dict[type, Callable] = {}

    def on_startup(self, fn: Callable):
        self._startup_hooks.append(fn)
        return fn

    def on_shutdown(self, fn: Callable):
        self._shutdown_hooks.append(fn)
        return fn

    def exception_handler(self, exc_type: type):
        def decorator(fn):
            self._exception_handlers[exc_type] = fn
            return fn
        return decorator

    async def __call__(self, scope: dict, receive: Callable, send: Callable):
        """ASGI interface"""
        raw = await receive()
        request = Request.from_raw(raw)
        response = await self.handle(request)
        await send(response.to_raw())
