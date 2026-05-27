from dataclasses import dataclass
from urllib.parse import urljoin

import httpx


class ZoteroApiError(RuntimeError):
    pass


class ZoteroConfigError(ZoteroApiError):
    pass


class ZoteroAuthenticationError(ZoteroApiError):
    pass


class ZoteroNotFoundError(ZoteroApiError):
    pass


class ZoteroNetworkError(ZoteroApiError):
    pass


class ZoteroInvalidResponseError(ZoteroApiError):
    pass


@dataclass(frozen=True)
class ZoteroApiConfig:
    library_type: str | None
    library_id: str | None
    api_key: str | None = None
    collection_key: str | None = None
    base_url: str = "https://api.zotero.org"

    def validate(self) -> None:
        if self.library_type not in {"user", "group"}:
            raise ZoteroConfigError("Zotero library type must be 'user' or 'group'.")
        if not self.library_id:
            raise ZoteroConfigError("Zotero library id is required for API sync.")


class ZoteroApiClient:
    def __init__(
        self,
        config: ZoteroApiConfig,
        *,
        http_client: httpx.Client | None = None,
    ) -> None:
        config.validate()
        self.config = config
        self.http_client = http_client or httpx.Client(timeout=30.0)

    def build_items_url(self, collection_key: str | None = None) -> str:
        library_segment = "users" if self.config.library_type == "user" else "groups"
        path = f"{library_segment}/{self.config.library_id}/"
        key = collection_key or self.config.collection_key
        if key:
            path += f"collections/{key}/items"
        else:
            path += "items"
        return urljoin(self.config.base_url.rstrip("/") + "/", path)

    def build_headers(self) -> dict[str, str]:
        headers = {"Zotero-API-Version": "3"}
        if self.config.api_key:
            headers["Zotero-API-Key"] = self.config.api_key
        return headers

    def fetch_items(
        self,
        *,
        collection_key: str | None = None,
        limit: int | None = None,
    ) -> list[dict]:
        url = self.build_items_url(collection_key)
        items: list[dict] = []
        params: dict[str, int] | None = {"limit": min(limit, 100)} if limit else None

        while url:
            response = self._get(url, params=params)
            page = self._decode_page(response)
            items.extend(page)
            if limit is not None and len(items) >= limit:
                return items[:limit]
            url = _next_link(response.headers.get("Link"))
            params = None

        return items

    def _get(self, url: str, *, params: dict[str, int] | None) -> httpx.Response:
        try:
            response = self.http_client.get(url, headers=self.build_headers(), params=params)
        except httpx.RequestError as exc:
            raise ZoteroNetworkError("Could not reach Zotero API.") from exc

        if response.status_code in {401, 403}:
            raise ZoteroAuthenticationError("Zotero authentication failed or access is forbidden.")
        if response.status_code == 404:
            raise ZoteroNotFoundError("Zotero library or collection was not found.")
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise ZoteroApiError(f"Zotero API request failed with HTTP {response.status_code}.") from exc
        return response

    @staticmethod
    def _decode_page(response: httpx.Response) -> list[dict]:
        try:
            payload = response.json()
        except ValueError as exc:
            raise ZoteroInvalidResponseError("Zotero API returned invalid JSON.") from exc

        if not isinstance(payload, list):
            raise ZoteroInvalidResponseError("Zotero API response must be a JSON list.")

        return [item for item in payload if isinstance(item, dict)]


def _next_link(header: str | None) -> str | None:
    if not header:
        return None
    for part in header.split(","):
        section = part.strip()
        if 'rel="next"' not in section:
            continue
        start = section.find("<")
        end = section.find(">")
        if start != -1 and end != -1 and end > start:
            return section[start + 1:end]
    return None
