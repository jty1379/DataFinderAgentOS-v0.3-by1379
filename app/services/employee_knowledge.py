"""数字员工 Markdown Prompt 资料的隔离存储与读取。"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

from config.settings import BASE_DIR

KNOWLEDGE_ROOT = BASE_DIR / "data" / "dgUser"
MAX_FILE_BYTES = 512 * 1024
MAX_FILES = 8
MAX_CONTEXT_CHARS = 30000


class EmployeeKnowledgeError(ValueError):
    pass


def _directory(employee_id: int) -> Path:
    if int(employee_id) <= 0:
        raise EmployeeKnowledgeError("数字员工编号无效")
    return KNOWLEDGE_ROOT / str(int(employee_id))


def list_files(employee_id: int) -> list[dict]:
    directory = _directory(employee_id)
    if not directory.exists():
        return []
    return [
        {"name": item.name, "size": item.stat().st_size}
        for item in sorted(directory.glob("*.md"), key=lambda path: path.name.lower())
        if item.is_file()
    ]


def save_uploads(employee_id: int, uploads: list, *, clear: bool = False) -> list[dict]:
    directory = _directory(employee_id)
    uploads = list(uploads or [])
    if not uploads:
        if clear and directory.exists():
            shutil.rmtree(directory)
        return list_files(employee_id)
    existing_count = 0 if clear else len(list_files(employee_id))
    if existing_count + len(uploads) > MAX_FILES:
        raise EmployeeKnowledgeError(f"每个数字员工最多保存 {MAX_FILES} 个 Markdown 文件")
    prepared: list[tuple[str, bytes]] = []
    for upload in uploads:
        original = Path(str(upload.get("filename") or "")).name
        if not original.lower().endswith(".md"):
            raise EmployeeKnowledgeError("Prompt 资料只允许上传 .md 文件")
        body = upload.get("body") or b""
        if not isinstance(body, bytes) or not 1 <= len(body) <= MAX_FILE_BYTES:
            raise EmployeeKnowledgeError("单个 Markdown 文件需为 1B—512KB")
        try:
            body.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise EmployeeKnowledgeError("Markdown 文件必须使用 UTF-8 编码") from exc
        stem = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff._-]+", "-", original[:-3]).strip(".-")
        prepared.append(((stem[:80] or "prompt") + ".md", body))
    if clear and directory.exists():
        shutil.rmtree(directory)
    directory.mkdir(parents=True, exist_ok=True)
    for name, body in prepared:
        (directory / name).write_bytes(body)
    return list_files(employee_id)


def prompt_context(employee_id: int) -> str:
    parts: list[str] = []
    used = 0
    for item in list_files(employee_id):
        text = (_directory(employee_id) / item["name"]).read_text(
            encoding="utf-8-sig", errors="strict"
        ).strip()
        remaining = MAX_CONTEXT_CHARS - used
        if not text or remaining <= 0:
            continue
        excerpt = text[:remaining]
        parts.append(f"### 管理员资料：{item['name']}\n{excerpt}")
        used += len(excerpt)
    return "\n\n".join(parts)


def remove_employee_directory(employee_id: int) -> None:
    directory = _directory(employee_id)
    if directory.exists():
        shutil.rmtree(directory)
