"""
MIDI 播放器插件
支持上传 MIDI 和 SF2 文件，在浏览器中播放。
路由由插件自行注册，不再依赖 http.py 硬编码。
"""

import os
import json
import re
import shutil
import io
from pathlib import Path
from datetime import datetime

from hedera.plugin.base import PluginBase
from plugins.midi.midi_renderer import render_midi_to_wav

# 数据目录
DATA_DIR = Path(__file__).parent / "data"
MIDI_DIR = DATA_DIR / "midi"
SF2_DIR = DATA_DIR / "sf2"

# 静态文件目录
STATIC_DIR = Path(__file__).parent / "static"

# 确保目录存在
MIDI_DIR.mkdir(parents=True, exist_ok=True)
SF2_DIR.mkdir(parents=True, exist_ok=True)
STATIC_DIR.mkdir(parents=True, exist_ok=True)


def _list_files(directory: Path, extensions: list[str], url_prefix: str) -> list[dict]:
    """列出目录中的文件"""
    files = []
    for f in sorted(directory.iterdir()):
        if f.is_file() and f.suffix.lower() in extensions:
            stat = f.stat()
            files.append({
                "name": f.name,
                "size": stat.st_size,
                "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                "path": str(f.relative_to(DATA_DIR)),
                "url": f"{url_prefix}/{f.name}",
            })
    return files


def list_midi_files() -> dict:
    """列出所有MIDI文件"""
    return {
        "success": True,
        "files": _list_files(MIDI_DIR, [".mid", ".midi"], "/api/midi/download"),
    }


def list_sf2_files() -> dict:
    """列出所有SF2音色库"""
    return {
        "success": True,
        "files": _list_files(SF2_DIR, [".sf2", ".sf3"], "/api/sf2/download"),
    }


def upload_file(filename: str, file_data: bytes, file_type: str = "midi") -> dict:
    """上传文件"""
    try:
        if file_type == "midi":
            target_dir = MIDI_DIR
            allowed = [".mid", ".midi"]
        elif file_type == "sf2":
            target_dir = SF2_DIR
            allowed = [".sf2", ".sf3"]
        else:
            return {"success": False, "error": f"不支持的文件类型: {file_type}"}

        ext = Path(filename).suffix.lower()
        if ext not in allowed:
            return {"success": False, "error": f"不支持的扩展名: {ext}，允许: {allowed}"}

        # 安全文件名
        safe_name = "".join(c for c in filename if c.isalnum() or c in "._- ")
        target_path = target_dir / safe_name

        with open(target_path, "wb") as f:
            f.write(file_data)

        return {
            "success": True,
            "filename": safe_name,
            "path": str(target_path.relative_to(DATA_DIR)),
            "size": len(file_data),
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def delete_file(filename: str, file_type: str = "midi") -> dict:
    """删除文件"""
    try:
        if file_type == "midi":
            target_dir = MIDI_DIR
        elif file_type == "sf2":
            target_dir = SF2_DIR
        else:
            return {"success": False, "error": f"不支持的文件类型: {file_type}"}

        target_path = target_dir / filename
        if not target_path.exists():
            return {"success": False, "error": "文件不存在"}

        target_path.unlink()
        return {"success": True, "message": f"已删除: {filename}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def get_file_path(filename: str, file_type: str = "midi") -> str | None:
    """获取文件完整路径"""
    if file_type == "midi":
        target_dir = MIDI_DIR
    elif file_type == "sf2":
        target_dir = SF2_DIR
    else:
        return None

    target_path = target_dir / filename
    if target_path.exists():
        return str(target_path)
    return None


def _parse_multipart(content_type: str, body: bytes):
    """简单的 multipart/form-data 解析"""
    import email.parser
    import email.policy

    # 提取 boundary
    match = re.search(r'boundary=(.+)', content_type)
    if not match:
        return None, None
    boundary = match.group(1).strip()

    # 构造完整的 multipart 消息
    msg_bytes = (
        f"Content-Type: multipart/form-data; boundary={boundary}\r\n"
        f"\r\n"
    ).encode() + body

    msg = email.parser.BytesParser(policy=email.policy.default).parsebytes(msg_bytes)

    for part in msg.walk():
        content_disposition = part.get("Content-Disposition", "")
        if "filename=" in content_disposition:
            # 文件字段
            filename_match = re.search(r'filename="([^"]+)"', content_disposition)
            filename = filename_match.group(1) if filename_match else "upload"
            file_data = part.get_payload(decode=True) or b""
            return filename, file_data

    return None, None


# ─── HTTP 路由处理器 ───

def handle_midi_upload(context: dict):
    """POST /api/midi/upload — 上传 MIDI 文件"""
    file_data = context.get("file_data")
    file_name = context.get("file_name")
    if not file_data or not file_name:
        return {"success": False, "error": "未提供文件"}, 400
    # 裁掉尾部垃圾数据（防止 midi-player-js 解析器死循环）
    file_data = _trim_midi(file_data)
    result = upload_file(file_name, file_data, "midi")
    return result, 200 if result.get("success") else 400


def _trim_midi(data: bytes) -> bytes:
    """裁掉 MIDI 文件末尾非 MTrk 块的垃圾数据"""
    import struct
    if len(data) < 14 or data[:4] != b'MThd':
        return data
    offset = 14
    while offset < len(data) - 8:
        tag = data[offset:offset+4]
        if tag != b'MTrk':
            break
        size = struct.unpack_from('>I', data, offset+4)[0]
        offset += 8 + size
    if offset < len(data):
        return data[:offset]
    return data


def handle_sf2_upload(context: dict):
    """POST /api/sf2/upload — 上传 SF2 音色库"""
    file_data = context.get("file_data")
    file_name = context.get("file_name")
    if not file_data or not file_name:
        return {"success": False, "error": "未提供文件"}, 400
    result = upload_file(file_name, file_data, "sf2")
    return result, 200 if result.get("success") else 400


def handle_midi_list(context: dict):
    """GET /api/midi/list — 列出 MIDI 文件"""
    return list_midi_files(), 200


def handle_sf2_list(context: dict):
    """GET /api/sf2/list — 列出 SF2 文件"""
    return list_sf2_files(), 200


def handle_midi_delete(context: dict):
    """DELETE /api/midi/delete/{filename} — 删除 MIDI 文件"""
    filename = context["params"]["filename"]
    return delete_file(filename, "midi"), 200


def handle_sf2_delete(context: dict):
    """DELETE /api/sf2/delete/{filename} — 删除 SF2 文件"""
    filename = context["params"]["filename"]
    return delete_file(filename, "sf2"), 200


def handle_midi_download(context: dict):
    """GET /api/midi/download/{filename} — 下载 MIDI 文件"""
    filename = context["params"]["filename"]
    file_path = get_file_path(filename, "midi")
    if not file_path:
        return {"error": "文件不存在"}, 404
    with open(file_path, "rb") as f:
        data = f.read()
    return (data, 200, "audio/midi")


def handle_sf2_download(context: dict):
    """GET /api/sf2/download/{filename} — 下载 SF2 音色库"""
    filename = context["params"]["filename"]
    file_path = get_file_path(filename, "sf2")
    if not file_path:
        return {"error": "文件不存在"}, 404
    with open(file_path, "rb") as f:
        data = f.read()
    return (data, 200, "application/octet-stream")





def handle_midi_render(context: dict):
    """GET /api/midi/render/{filename} — 渲染 MIDI 为 WAV"""
    from urllib.parse import unquote
    from plugins.midi.midi_renderer import render_midi_to_wav, get_render_progress, set_render_progress
    filename = unquote(context["params"]["filename"])
    file_path = get_file_path(filename, "midi")
    if not file_path:
        return {"error": "文件不存在"}, 404

    sf2_files = list(SF2_DIR.glob('*.sf2')) + list(SF2_DIR.glob('*.sf3'))
    if not sf2_files:
        return {"error": "没有 SF2 音色库"}, 400
    sf2_path = str(sf2_files[0])

    wav_name = Path(filename).stem + '.wav'
    wav_path = str(MIDI_DIR / wav_name)

    if Path(wav_path).exists():
        if Path(wav_path).stat().st_mtime > Path(file_path).stat().st_mtime:
            return {"success": True, "url": f"/api/midi/download/{wav_name}"}, 200

    render_id = f"render_{filename}"
    try:
        set_render_progress(render_id, "starting", 0)
        # 异步渲染，不阻塞请求
        import threading
        def _do_render():
            try:
                render_midi_to_wav(file_path, sf2_path, wav_path, render_id=render_id)
            except Exception as e:
                set_render_progress(render_id, "error", 0, str(e))
        threading.Thread(target=_do_render, daemon=True).start()
        return {"success": True, "status": "rendering", "render_id": render_id}, 202
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"success": False, "error": str(e)}, 500


def handle_render_progress(context: dict):
    """GET /api/midi/progress/{render_id} — 渲染进度"""
    from urllib.parse import unquote
    from plugins.midi.midi_renderer import get_render_progress
    render_id = unquote(context["params"]["render_id"])
    prog = get_render_progress(render_id)
    # 完成时附带 WAV URL
    if prog.get("pct", 0) >= 100:
        # 从 render_id 提取文件名
        fname = render_id.replace("render_", "", 1)
        wav_name = Path(fname).stem + ".wav"
        prog["url"] = f"/api/midi/download/{wav_name}"
    return prog, 200


def handle_player_page(context: dict):
    """GET /player — MIDI 播放器页面"""
    index_path = STATIC_DIR / "midi.html"
    if not index_path.exists():
        return {"error": "播放器页面不存在"}, 404
    with open(index_path, "rb") as f:
        data = f.read()
    return (data, 200, "text/html")


# ─── 插件类 ───


class MIDIPlugin(PluginBase):
    name = "midi"
    description = "播放MIDI文件，支持自定义SF2音色库"
    keywords = ["midi", "音乐", "播放器", "sf2", "soundfont", "音色"]
    commands = ["/midi"]

    def process(self, message: str, context: dict = None) -> str | None:
        msg = message.strip()

        if msg.startswith("/midi"):
            return "🎵 MIDI播放器已就绪\n使用前端界面上传和播放MIDI文件。\n支持格式: .mid, .midi\n音色库: .sf2, .sf3"

        # 关键词匹配
        has_midi_kw = any(kw in msg for kw in ["midi", "播放音乐", "音乐播放"])
        if has_midi_kw and len(msg) > 5:
            return None  # 让 LLM 处理

        return None

    def get_tools(self) -> list[dict]:
        return [
            {
                "name": "midi_list_files",
                "description": "列出已上传的MIDI文件和SF2音色库",
                "fn": lambda: {"midi": list_midi_files(), "sf2": list_sf2_files()},
                "parameters": {"type": "object", "properties": {}},
            },
            {
                "name": "midi_get_path",
                "description": "获取MIDI或SF2文件的路径",
                "fn": get_file_path,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "filename": {"type": "string", "description": "文件名"},
                        "file_type": {
                            "type": "string",
                            "enum": ["midi", "sf2"],
                            "description": "文件类型",
                            "default": "midi",
                        },
                    },
                    "required": ["filename"],
                },
            },
        ]

    def get_routes(self) -> list[tuple]:
        """注册 HTTP 路由"""
        return [
            # 页面
            ("GET", "/player", handle_player_page),
            # MIDI API
            ("GET", "/api/midi/list", handle_midi_list),
            ("POST", "/api/midi/upload", handle_midi_upload),
            ("DELETE", "/api/midi/delete/{filename}", handle_midi_delete),
            ("GET", "/api/midi/download/{filename}", handle_midi_download),
            ("GET", "/api/midi/render/{filename}", handle_midi_render),

            ("GET", "/api/midi/progress/{render_id}", handle_render_progress),
            # SF2 API
            ("GET", "/api/sf2/list", handle_sf2_list),
            ("POST", "/api/sf2/upload", handle_sf2_upload),
            ("DELETE", "/api/sf2/delete/{filename}", handle_sf2_delete),
            ("GET", "/api/sf2/download/{filename}", handle_sf2_download),
        ]

    def get_static_dir(self) -> str | None:
        """返回静态文件目录"""
        return str(STATIC_DIR)

    def get_system_prompt_modifier(self) -> str:
        return (
            "【MIDI播放器】用户可通过前端界面上传和播放MIDI文件，支持SF2音色库。\n"
            "  用户说「播放midi」「打开播放器」时，引导用户访问前端MIDI播放器页面。\n"
        )
