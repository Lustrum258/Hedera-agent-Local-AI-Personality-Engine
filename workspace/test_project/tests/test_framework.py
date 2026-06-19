"""Tests for the framework"""
import json
import sys
import os
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from framework.app import App, Router, Request, Response
from framework.auth import AuthManager, hash_password, Role
from framework.config import Config
from framework.validation import Schema, ValidationError, validate_email


class TestRequest(unittest.TestCase):
    def test_parse_get_request(self):
        raw = "GET /users?page=1&limit=10 HTTP/1.1\r\nHost: localhost\r\n\r\n"
        req = Request.from_raw(raw)
        self.assertEqual(req.method, "GET")
        self.assertEqual(req.path, "/users")
        self.assertEqual(req.query_params["page"], "1")
        self.assertEqual(req.query_params["limit"], "10")

    def test_parse_post_with_body(self):
        raw = 'POST /api/data HTTP/1.1\r\nContent-Type: application/json\r\n\r\n{"key": "value"}'
        req = Request.from_raw(raw)
        self.assertEqual(req.method, "POST")
        self.assertEqual(req.body, '{"key": "value"}')
        self.assertEqual(req.headers["Content-Type"], "application/json")


class TestResponse(unittest.TestCase):
    def test_json_response(self):
        resp = Response(status=200, body={"message": "ok"})
        raw = resp.to_raw()
        self.assertIn("200 OK", raw)
        self.assertIn('"message": "ok"', raw)

    def test_404_response(self):
        resp = Response(status=404, body={"error": "not found"})
        raw = resp.to_raw()
        self.assertIn("404 Not Found", raw)


class TestRouter(unittest.TestCase):
    def setUp(self):
        self.router = Router()

    def test_simple_route(self):
        @self.router.get("/hello")
        def hello(req):
            return {"greeting": "world"}

        import asyncio
        req = Request(method="GET", path="/hello", headers={})
        resp = asyncio.run(self.router.handle(req))
        self.assertEqual(resp.status, 200)
        self.assertEqual(resp.body, {"greeting": "world"})

    def test_path_params(self):
        @self.router.get("/users/{user_id}")
        def get_user(req):
            return {"user_id": req.path_params["user_id"]}

        import asyncio
        req = Request(method="GET", path="/users/42", headers={})
        resp = asyncio.run(self.router.handle(req))
        self.assertEqual(resp.body["user_id"], "42")

    def test_404(self):
        import asyncio
        req = Request(method="GET", path="/nonexistent", headers={})
        resp = asyncio.run(self.router.handle(req))
        self.assertEqual(resp.status, 404)

    def test_sub_router(self):
        api = Router(prefix="/api")

        @api.get("/items")
        def list_items(req):
            return [{"id": 1}, {"id": 2}]

        self.router.include_router(api)

        import asyncio
        req = Request(method="GET", path="/api/items", headers={})
        resp = asyncio.run(self.router.handle(req))
        self.assertEqual(resp.status, 200)
        self.assertEqual(len(resp.body), 2)


class TestAuth(unittest.TestCase):
    def setUp(self):
        self.auth = AuthManager(secret="test-secret")

    def test_register_and_login(self):
        user = self.auth.register("testuser", "test@example.com", "password123")
        self.assertEqual(user.username, "testuser")
        self.assertEqual(user.email, "test@example.com")
        self.assertTrue(user.check_password("password123"))

        token = self.auth.login("testuser", "password123")
        self.assertIsNotNone(token)

        verified = self.auth.verify(token)
        self.assertIsNotNone(verified)
        self.assertEqual(verified.id, user.id)

    def test_duplicate_username(self):
        self.auth.register("user1", "a@test.com", "pass")
        with self.assertRaises(ValueError):
            self.auth.register("user1", "b@test.com", "pass")

    def test_wrong_password(self):
        self.auth.register("user2", "c@test.com", "correct")
        token = self.auth.login("user2", "wrong")
        self.assertIsNone(token)

    def test_roles(self):
        user = self.auth.register("admin", "admin@test.com", "pass", roles={Role.ADMIN})
        self.assertTrue(user.has_role(Role.ADMIN))
        self.assertFalse(user.has_role(Role.EDITOR))


class TestConfig(unittest.TestCase):
    def test_defaults(self):
        config = Config()
        self.assertEqual(config.get("app_name"), "Hedera Test App")
        self.assertEqual(config.get("port"), 8000)
        self.assertFalse(config.get("debug"))

    def test_nested_get(self):
        config = Config()
        self.assertEqual(config.get("database.url"), "sqlite:///app.db")
        self.assertEqual(config.get("auth.token_expire_seconds"), 3600)

    def test_set_value(self):
        config = Config()
        config.set("port", 9000)
        self.assertEqual(config.get("port"), 9000)

    def test_missing_key(self):
        config = Config()
        self.assertIsNone(config.get("nonexistent"))
        self.assertEqual(config.get("nonexistent", "default"), "default")


class TestValidation(unittest.TestCase):
    def test_valid_email(self):
        self.assertEqual(validate_email("user@example.com"), "user@example.com")

    def test_invalid_email(self):
        with self.assertRaises(ValueError):
            validate_email("not-an-email")


class TestApp(unittest.TestCase):
    def test_app_creation(self):
        app = App(title="Test", version="2.0")
        self.assertEqual(app.title, "Test")
        self.assertEqual(app.version, "2.0")

    def test_full_request_cycle(self):
        app = App()

        @app.get("/ping")
        def ping(req):
            return {"pong": True}

        import asyncio
        req = Request(method="GET", path="/ping", headers={})
        resp = asyncio.run(app.handle(req))
        self.assertEqual(resp.status, 200)
        self.assertEqual(resp.body, {"pong": True})


if __name__ == "__main__":
    unittest.main()
