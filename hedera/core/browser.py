"""
Hedera 浏览器自动化工具
基于 Playwright + Edge，支持语义化操作（不需要 CSS 选择器）
"""

import os
import json
import time
import threading

_browser = None
_page = None
_context = None
_pw = None
_lock = threading.Lock()
_browser_thread_id = None


def _get_browser():
    global _browser, _context, _page, _pw, _browser_thread_id
    current_thread = threading.get_ident()
    # 如果线程变了，需要重新创建浏览器
    if _browser_thread_id is not None and _browser_thread_id != current_thread:
        _cleanup_browser()
    if _browser is None or not _browser.is_connected():
        from playwright.sync_api import sync_playwright
        _pw = sync_playwright().start()
        _browser = _pw.chromium.launch(headless=True, channel='msedge')
        _context = _browser.new_context(
            viewport={'width': 1280, 'height': 720},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        )
        _page = _context.new_page()
        _browser_thread_id = current_thread
    return _page


def _ensure_page():
    global _page
    if _page is None or _page.is_closed():
        _page = _get_browser()
    return _page


def _cleanup_browser():
    global _browser, _context, _page, _pw, _browser_thread_id
    try:
        if _page and not _page.is_closed():
            _page.close()
    except: pass
    try:
        if _context:
            _context.close()
    except: pass
    try:
        if _browser:
            _browser.close()
    except: pass
    try:
        if _pw:
            _pw.stop()
    except: pass
    _browser = _context = _page = _pw = None
    _browser_thread_id = None


def _save_screenshot(page, full_page=False):
    upload_dir = os.path.join(os.getcwd(), "uploads", "_common")
    os.makedirs(upload_dir, exist_ok=True)
    filename = f"screenshot_{int(time.time())}.png"
    filepath = os.path.join(upload_dir, filename)
    page.screenshot(path=filepath, full_page=full_page)
    return f"/download/_common/{filename}"


def _get_page_summary(page):
    """获取页面摘要：可交互元素列表 + 文本预览"""
    info = page.evaluate("""() => {
        const result = {title: document.title, url: location.href, elements: [], text: ''};

        // 收集可交互元素（用无障碍语义）
        const interactables = document.querySelectorAll(
            'a[href], button, input, textarea, select, [role=button], [role=link], [role=tab], [onclick], [tabindex]'
        );
        const seen = new Set();
        for (const el of interactables) {
            if (el.offsetParent === null && el.tagName !== 'INPUT') continue; // 跳过隐藏元素
            const tag = el.tagName.toLowerCase();
            const type = el.type || '';
            const text = (el.textContent || el.value || el.placeholder || el.title || el.alt || '').trim().substring(0, 60);
            const role = el.getAttribute('role') || '';
            const name = el.name || el.id || '';
            const href = el.href || '';

            if (!text && !name && tag !== 'input') continue;
            const key = `${tag}|${name}|${text}`;
            if (seen.has(key)) continue;
            seen.add(key);

            const item = {tag};
            if (text) item.text = text;
            if (role) item.role = role;
            if (name) item.name = name;
            if (type) item.type = type;
            if (href && tag === 'a') item.href = href.substring(0, 200);
            if (tag === 'select') {
                item.options = Array.from(el.options).map(o => ({value: o.value, text: o.textContent.trim()})).slice(0, 10);
            }
            result.elements.push(item);
        }

        // 收集页面主要文本（前 2000 字）
        const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, {
            acceptNode: n => (n.parentElement.tagName === 'SCRIPT' || n.parentElement.tagName === 'STYLE') ?
                NodeFilter.FILTER_REJECT : (n.textContent.trim().length > 0 ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_SKIP)
        });
        const texts = [];
        while (walker.nextNode() && texts.join('').length < 2000) {
            texts.push(walker.currentNode.textContent.trim());
        }
        result.text = texts.join('\\n').substring(0, 2000);

        return result;
    }""")
    return info


def browser_run(steps: list) -> dict:
    """
    批量执行浏览器操作。

    支持的操作：
    - navigate: {"action":"navigate", "url":"https://..."}
    - see: {"action":"see"}  → 截图 + 返回页面摘要（可交互元素 + 文本）
    - type: {"action":"type", "selector":"...", "text":"...", "enter":false}
      selector 可以是 CSS 选择器，也可以是 placeholder/name/id 文本
    - click: {"action":"click", "selector":"..."}
    - wait: {"action":"wait", "ms":1000}
    - screenshot: {"action":"screenshot"}
    - content: {"action":"content", "max_length":5000}
    - scroll: {"action":"scroll", "direction":"down", "amount":500}
    - select: {"action":"select", "selector":"...", "value":"..."}
    - eval: {"action":"eval", "code":"..."}
    """
    with _lock:
        page = _ensure_page()
        results = []

        for i, step in enumerate(steps):
            action = step.get("action", "")
            try:
                if action == "navigate":
                    url = step.get("url", "")
                    page.goto(url, wait_until='domcontentloaded', timeout=30000)
                    results.append({"step": i, "action": action, "ok": True,
                                   "title": page.title(), "url": page.url})

                elif action == "see":
                    screenshot_url = _save_screenshot(page)
                    summary = _get_page_summary(page)
                    results.append({"step": i, "action": action, "ok": True,
                                   "screenshot": screenshot_url, "summary": summary})

                elif action == "type":
                    selector = _resolve_selector(page, step.get("selector", ""))
                    text = step.get("text", "")
                    enter = step.get("enter", False)
                    clear = step.get("clear", True)
                    if clear:
                        page.fill(selector, "")
                    page.fill(selector, text)
                    if enter:
                        page.press(selector, 'Enter')
                        time.sleep(0.5)
                    results.append({"step": i, "action": action, "ok": True})

                elif action == "click":
                    selector = _resolve_selector(page, step.get("selector", ""))
                    page.click(selector, timeout=5000)
                    time.sleep(0.3)
                    results.append({"step": i, "action": action, "ok": True})

                elif action == "wait":
                    time.sleep(step.get("ms", 1000) / 1000)
                    results.append({"step": i, "action": action, "ok": True})

                elif action == "screenshot":
                    url = _save_screenshot(page, step.get("full_page", False))
                    results.append({"step": i, "action": action, "ok": True, "url": url})

                elif action == "content":
                    max_len = step.get("max_length", 5000)
                    text = page.evaluate("() => document.body.innerText").substring(0, max_len)
                    results.append({"step": i, "action": action, "ok": True, "text": text})

                elif action == "scroll":
                    direction = step.get("direction", "down")
                    amount = step.get("amount", 500)
                    if direction == "down":
                        page.evaluate(f"window.scrollBy(0, {amount})")
                    elif direction == "up":
                        page.evaluate(f"window.scrollBy(0, -{amount})")
                    elif direction == "top":
                        page.evaluate("window.scrollTo(0, 0)")
                    elif direction == "bottom":
                        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    time.sleep(0.2)
                    results.append({"step": i, "action": action, "ok": True})

                elif action == "select":
                    selector = _resolve_selector(page, step.get("selector", ""))
                    page.select_option(selector, step.get("value", ""))
                    results.append({"step": i, "action": action, "ok": True})

                elif action == "eval":
                    result = page.evaluate(step.get("code", ""))
                    results.append({"step": i, "action": action, "ok": True, "result": str(result)[:500]})

                elif action == "script":
                    result = browser_script(step.get("code", ""))
                    results.append({"step": i, "action": action, **result})

                elif action == "cdp":
                    result = browser_cdp(step.get("method", ""), step.get("params"))
                    results.append({"step": i, "action": action, **result})

                elif action == "back":
                    page.go_back()
                    results.append({"step": i, "action": action, "ok": True, "title": page.title()})

                elif action == "forward":
                    page.go_forward()
                    results.append({"step": i, "action": action, "ok": True, "title": page.title()})

                elif action == "reload":
                    page.reload()
                    results.append({"step": i, "action": action, "ok": True, "title": page.title()})

                else:
                    results.append({"step": i, "action": action, "ok": False, "error": f"未知操作: {action}"})

            except Exception as e:
                results.append({"step": i, "action": action, "ok": False, "error": str(e)[:200]})
                if not step.get("continue_on_error", False):
                    break

        success = all(r.get("ok", False) for r in results)
        return {
            "success": success,
            "ok": success,
            "steps": len(results),
            "results": results,
            "page_title": page.title() if page and not page.is_closed() else "",
            "page_url": page.url if page and not page.is_closed() else "",
        }


def _resolve_selector(page, selector: str) -> str:
    """
    智能解析选择器：
    - 如果是标准 CSS 选择器（以 # . [ 开头），直接用
    - 否则尝试按 placeholder、name、aria-label、文本内容匹配
    """
    if not selector:
        return selector

    # 标准 CSS 选择器
    if selector.startswith(('#', '.', '[', 'input', 'button', 'a', 'select', 'textarea')):
        return selector

    # 尝试语义匹配
    lower = selector.lower()
    # 按 placeholder
    found = page.query_selector(f'[placeholder*="{selector}" i]')
    if found:
        return f'[placeholder*="{selector}" i]'

    # 按 name
    found = page.query_selector(f'[name="{selector}"]')
    if found:
        return f'[name="{selector}"]'

    # 按 aria-label
    found = page.query_selector(f'[aria-label*="{selector}" i]')
    if found:
        return f'[aria-label*="{selector}" i]'

    # 按文本内容（button、a、label）
    found = page.query_selector(f'button:has-text("{selector}")')
    if found:
        return f'button:has-text("{selector}")'
    found = page.query_selector(f'a:has-text("{selector}")')
    if found:
        return f'a:has-text("{selector}")'

    # 兜底：原样返回
    return selector


def browser_script(code: str) -> dict:
    """
    在浏览器中执行 JavaScript 代码，直接操作 DOM。
    可用变量：page（Playwright Page 对象）
    返回值自动序列化为 JSON。
    """
    page = _ensure_page()
    try:
        # 包装代码，捕获返回值
        wrapped = f"""
        (async () => {{
            const page = arguments[0];
            {code}
        }})(window.__playwright_page)
        """
        # 通过 CDP 直接执行
        result = page.evaluate(code)
        return {"success": True, "result": str(result)[:5000] if result else None}
    except Exception as e:
        return {"success": False, "error": str(e)[:300]}


def browser_cdp(method: str, params: dict = None) -> dict:
    """
    直接调用 CDP（Chrome DevTools Protocol）命令。
    例：browser_cdp("Network.enable")
        browser_cdp("Runtime.evaluate", {"expression": "document.title"})
    """
    page = _ensure_page()
    try:
        result = page.evaluate(f"""
            async () => {{
                const client = await window.__cdpSession;
                return await client.send('{method}', {json.dumps(params or {})});
            }}
        """)
        return {"success": True, "result": result}
    except Exception as e:
        # fallback: 用 Playwright 的 CDP session
        try:
            cdp = page.context.new_cdp_session(page)
            result = cdp.send(method, params or {})
            return {"success": True, "result": result}
        except Exception as e2:
            return {"success": False, "error": str(e2)[:300]}


def browser_close() -> dict:
    global _browser, _context, _page, _pw
    try:
        if _page and not _page.is_closed():
            _page.close()
        if _context:
            _context.close()
        if _browser:
            _browser.close()
        if _pw:
            _pw.stop()
        _browser = _context = _page = _pw = None
        return {"success": True, "message": "浏览器已关闭"}
    except Exception as e:
        return {"success": False, "error": str(e)}
