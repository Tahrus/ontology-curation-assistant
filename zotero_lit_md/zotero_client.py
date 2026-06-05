from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Any, Iterable


@dataclass(frozen=True)
class ZoteroItem:
    key: str
    data: dict[str, Any]
    raw: dict[str, Any]


class ZoteroLocalClient:
    """Small client for the Zotero Desktop local API."""

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:23119/api/",
        *,
        timeout: float = 20.0,
        zotero_data_dir: Path | None = None,
        storage_path: Path | None = None,
    ):
        import requests

        self.base_url = base_url.rstrip("/") + "/"
        self.timeout = timeout
        self.session = requests.Session()
        self.zotero_data_dir = zotero_data_dir or detect_zotero_data_dir()
        self.storage_path = storage_path.expanduser() if storage_path is not None else _storage_root(self.zotero_data_dir)

    def test_connection(self) -> bool:
        response = self.session.get(
            self.base_url + "users/0/items",
            params={"limit": 1, "format": "json"},
            timeout=self.timeout,
        )
        response.raise_for_status()
        return True

    def items(self) -> list[ZoteroItem]:
        return [self._item(item) for item in self._get_json("users/0/items", params={"format": "json"})]

    def limited_items(self, *, limit: int = 1) -> list[ZoteroItem]:
        return [
            self._item(item)
            for item in self._get_json("users/0/items", params={"limit": limit, "format": "json"})
        ]

    def item(self, item_key: str) -> ZoteroItem:
        return self._item(self._get_json(f"users/0/items/{item_key}", params={"format": "json"})[0])

    def collections(self) -> list[dict[str, Any]]:
        return self._get_json("users/0/collections")

    def saved_searches(self) -> list[dict[str, Any]]:
        try:
            return self._get_json("users/0/searches")
        except Exception:
            return []

    def saved_search_items(self, saved_search: str) -> list[ZoteroItem]:
        search_key = self._saved_search_key(saved_search)
        return [self._item(item) for item in self._get_json(f"users/0/searches/{search_key}/items")]

    def collection_items(self, collection: str) -> list[ZoteroItem]:
        collection_key = self._collection_key(collection)
        return [self._item(item) for item in self._get_json(f"users/0/collections/{collection_key}/items")]

    def child_attachments(self, item_key: str) -> list[dict[str, Any]]:
        return self._get_json(f"users/0/items/{item_key}/children", params={"format": "json"})

    def pdf_attachments(self, item_key: str, *, first_pdf_only: bool = False) -> list[dict[str, Any]]:
        attachments = sorted(
            [attachment for attachment in self.child_attachments(item_key) if is_pdf_attachment(attachment)],
            key=lambda attachment: 0 if is_stored_attachment(attachment) else 1,
        )
        return attachments[:1] if first_pdf_only else attachments

    def all_items_with_pdfs(self, *, max_papers: int | None = None) -> Iterable[ZoteroItem]:
        count = 0
        for item in self.items():
            attachments = [attachment for attachment in self.child_attachments(item.key) if is_attachment(attachment)]
            if any(self.resolve_pdf_paths(attachment) for attachment in attachments):
                yield item
                count += 1
                if max_papers is not None and count >= max_papers:
                    return

    def items_by_keys(self, keys: list[str]) -> list[ZoteroItem]:
        key_set = {key.casefold() for key in keys}
        return [item for item in self.items() if item.key.casefold() in key_set]

    def resolve_pdf_path(self, attachment: dict[str, Any]) -> Path | None:
        paths = find_pdfs_for_attachment_key(self.storage_path, _attachment_key(attachment), attachment)
        return paths[0] if paths else None

    def resolve_pdf_paths(self, attachment: dict[str, Any]) -> list[Path]:
        return find_pdfs_for_attachment_key(self.storage_path, _attachment_key(attachment), attachment)

    def _collection_key(self, collection: str) -> str:
        for record in self.collections():
            data = record.get("data") or {}
            if record.get("key") == collection or data.get("key") == collection:
                return str(record.get("key") or data.get("key"))
            if str(data.get("name") or "").casefold() == collection.casefold():
                return str(record.get("key") or data.get("key"))
        return collection

    def _saved_search_key(self, saved_search: str) -> str:
        for record in self.saved_searches():
            data = record.get("data") or {}
            if record.get("key") == saved_search or data.get("key") == saved_search:
                return str(record.get("key") or data.get("key"))
            if str(data.get("name") or "").casefold() == saved_search.casefold():
                return str(record.get("key") or data.get("key"))
        return saved_search

    def _get_json(self, path: str, *, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        response = self.session.get(
            self.base_url + path.lstrip("/"),
            params=params,
            timeout=self.timeout,
        )
        response.raise_for_status()
        payload = response.json()
        return payload if isinstance(payload, list) else [payload]

    @staticmethod
    def _item(raw: dict[str, Any]) -> ZoteroItem:
        return ZoteroItem(key=str(raw.get("key") or (raw.get("data") or {}).get("key") or ""), data=raw.get("data") or {}, raw=raw)


def is_pdf_attachment(item: dict[str, Any]) -> bool:
    data = item.get("data") or {}
    item_type = str(data.get("itemType") or item.get("itemType") or "").casefold()
    content_type = str(data.get("contentType") or data.get("mimeType") or "").casefold()
    filename = str(data.get("filename") or data.get("title") or item.get("filename") or "").casefold()
    title = str(data.get("title") or item.get("title") or "").casefold()
    return item_type == "attachment" and (
        content_type == "application/pdf" or filename.endswith(".pdf") or "pdf" in title
    )


def is_attachment(item: dict[str, Any]) -> bool:
    data = item.get("data") or {}
    return str(data.get("itemType") or item.get("itemType") or "").casefold() == "attachment"


def is_stored_attachment(item: dict[str, Any]) -> bool:
    path = str((item.get("data") or {}).get("path") or "")
    return path.casefold().startswith("storage:")


def detect_zotero_data_dir() -> Path | None:
    env_path = os.environ.get("ZOTERO_DATA_DIR")
    if env_path:
        return Path(env_path).expanduser()
    candidates = []
    userprofile = os.environ.get("USERPROFILE")
    if userprofile:
        candidates.append(Path(userprofile) / "Zotero")
    candidates.append(Path.home() / "Zotero")
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0] if candidates else None


def resolve_zotero_data_dir(cli_path: Path | None) -> Path | None:
    return cli_path.expanduser() if cli_path is not None else detect_zotero_data_dir()


def resolve_attachment_pdf_path(
    attachment_item: dict[str, Any],
    zotero_data_dir: Path | None,
) -> Path | None:
    paths = find_pdf_for_attachment_key(zotero_data_dir, _attachment_key(attachment_item), attachment_item)
    return paths[0] if paths else None


def find_pdfs_for_attachment_key(
    storage_path: Path | None,
    attachment_key: str,
    attachment_metadata: dict[str, Any] | None = None,
) -> list[Path]:
    """Find real PDFs for a Zotero attachment by inspecting its storage folder."""
    metadata = attachment_metadata or {}
    data = metadata.get("data") or {}
    attachment_key = str(attachment_key or metadata.get("key") or data.get("key") or "").strip()
    raw_path = data.get("path") or data.get("localPath") or metadata.get("path")
    linked_pdf = _linked_pdf_path(raw_path)
    if linked_pdf is not None:
        return [linked_pdf]

    if storage_path is None or not attachment_key:
        return []
    attachment_dir = Path(storage_path).expanduser() / attachment_key
    if not attachment_dir.exists() or not attachment_dir.is_dir():
        return []

    pdfs = sorted(
        {
            path.resolve()
            for pattern in ("*.pdf", "*.PDF")
            for path in attachment_dir.rglob(pattern)
            if path.is_file()
        }
    )
    return sorted(pdfs, key=lambda path: _pdf_relevance_key(path, data))


def find_pdf_for_attachment_key(
    zotero_data_dir: Path | None,
    attachment_key: str,
    attachment_metadata: dict[str, Any] | None = None,
) -> list[Path]:
    """Backward-compatible data-directory wrapper for stored Zotero PDFs."""
    return find_pdfs_for_attachment_key(_storage_root(zotero_data_dir), attachment_key, attachment_metadata)


def _linked_pdf_path(raw_path: Any) -> Path | None:
    if not raw_path:
        return None
    text = str(raw_path).strip()
    if not text or text.casefold().startswith("storage:"):
        return None
    candidate = Path(text).expanduser()
    if candidate.is_absolute() and candidate.exists() and candidate.is_file() and candidate.suffix.casefold() == ".pdf":
        return candidate
    return None


def _pdf_relevance_key(path: Path, data: dict[str, Any]) -> tuple[int, int, str]:
    filename = str(data.get("filename") or "").strip()
    raw_path = str(data.get("path") or data.get("localPath") or "").strip()
    storage_hint = raw_path.split(":", 1)[1].strip() if raw_path.casefold().startswith("storage:") else ""
    title = str(data.get("title") or "").strip()
    path_name = path.name.casefold()
    if filename and path_name == filename.casefold():
        return (0, 0, path_name)
    if storage_hint and path_name == Path(storage_hint).name.casefold():
        return (1, 0, path_name)
    title_words = {
        word
        for word in _normalize_name(title).split("-")
        if len(word) > 2
    }
    path_words = set(_normalize_name(path.stem).split("-"))
    shared_words = len(title_words & path_words)
    if shared_words:
        return (2, -shared_words, path_name)
    return (3, 0, path_name)


def _storage_candidate(zotero_data_dir: Path | None, attachment_key: str, filename: str) -> Path | None:
    storage_dir = _storage_dir(zotero_data_dir, attachment_key)
    if storage_dir is None or not filename:
        return None
    return storage_dir / filename


def _storage_dir(zotero_data_dir: Path | None, attachment_key: str) -> Path | None:
    if zotero_data_dir is None or not attachment_key:
        return None
    return Path(zotero_data_dir).expanduser() / "storage" / attachment_key


def _storage_root(zotero_data_dir: Path | None) -> Path | None:
    if zotero_data_dir is None:
        return None
    return Path(zotero_data_dir).expanduser() / "storage"


def _acceptable_pdf(path: Path | None, content_type: str) -> bool:
    if path is None or not path.exists() or not path.is_file():
        return False
    if path.suffix.casefold() == ".pdf":
        return True
    return content_type == "application/pdf" and can_open_pdf(path)


def can_open_pdf(path: Path) -> bool:
    try:
        import fitz

        with fitz.open(path) as document:
            return document.page_count >= 0
    except Exception:
        return False


def _best_pdf_match(paths: list[Path], hint: str) -> Path:
    normalized_hint = _normalize_name(hint)
    if normalized_hint:
        ranked = sorted(paths, key=lambda path: _match_distance(_normalize_name(path.name), normalized_hint))
        return ranked[0]
    return paths[0]


def _match_distance(candidate: str, hint: str) -> tuple[int, str]:
    if not hint:
        return (1, candidate)
    if candidate == hint:
        return (0, candidate)
    if hint in candidate or candidate in hint:
        return (0, candidate)
    shared = len(set(candidate.split("-")) & set(hint.split("-")))
    return (-shared, candidate)


def _normalize_name(value: str) -> str:
    import re

    return re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")


def _attachment_key(attachment: dict[str, Any]) -> str:
    data = attachment.get("data") or {}
    return str(attachment.get("key") or data.get("key") or "")
