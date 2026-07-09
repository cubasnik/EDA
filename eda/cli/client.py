"""Thin HTTP client used by the eda-cli. Talks to the EDA REST API only -
the CLI has no access to the store/engine directly, exactly like a real
operator workstation talking to a network element's northbound API."""
from __future__ import annotations

from typing import Any, Dict, Optional

import requests


class ApiError(Exception):
    def __init__(self, status_code: Optional[int], detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


class ApiClient:
    def __init__(self, base_url: str, api_key: str = "", timeout: float = 10.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._headers = {"X-API-Key": api_key} if api_key else {}

    def _url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    def _handle(self, resp: requests.Response) -> Any:
        if resp.status_code >= 400:
            try:
                detail = resp.json().get("detail", resp.text)
            except ValueError:
                detail = resp.text
            raise ApiError(resp.status_code, detail)
        if resp.status_code == 204 or not resp.content:
            return None
        return resp.json()

    def get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        try:
            resp = requests.get(
                self._url(path), params=params, headers=self._headers, timeout=self.timeout
            )
        except requests.RequestException as exc:
            raise ApiError(None, f"Cannot reach EDA API at {self.base_url}: {exc}") from exc
        return self._handle(resp)

    def post(self, path: str, json_body: Optional[Dict[str, Any]] = None) -> Any:
        try:
            resp = requests.post(
                self._url(path), json=json_body or {}, headers=self._headers, timeout=self.timeout
            )
        except requests.RequestException as exc:
            raise ApiError(None, f"Cannot reach EDA API at {self.base_url}: {exc}") from exc
        return self._handle(resp)

    def delete(self, path: str) -> Any:
        try:
            resp = requests.delete(self._url(path), headers=self._headers, timeout=self.timeout)
        except requests.RequestException as exc:
            raise ApiError(None, f"Cannot reach EDA API at {self.base_url}: {exc}") from exc
        return self._handle(resp)
