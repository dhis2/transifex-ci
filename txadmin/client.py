# Client for the Transifex REST API v3, scoped to one organisation.
# Handles authentication, JSON:API pagination, rate limiting and error reporting.

import time
from dataclasses import dataclass
from datetime import datetime

import requests

API_BASE = "https://rest.api.transifex.com"
MAX_RATE_LIMIT_RETRIES = 5
# Changing some project settings, such as translation memory fillup, takes Transifex up to a minute.
REQUEST_TIMEOUT_SECONDS = 120
API_DATETIME_FORMAT = "%Y-%m-%dT%H:%M:%S%z"
# Transifex fails with a server error, rather than a validation error, beyond these lengths.
# It stores a project's tags as one comma-joined string.
MAX_JOINED_TAGS_LENGTH = 255
MAX_HOMEPAGE_URL_LENGTH = 200
MAX_REPOSITORY_URL_LENGTH = 255


class ValueTooLongError(ValueError):
    """Raised before sending a value that Transifex cannot store."""

    def __init__(self, what: str, length: int, limit: int):
        super().__init__(f"{what} would take {length} characters; Transifex allows {limit}.")


class TransifexError(Exception):
    """Raised when the Transifex API returns an error response."""

    def __init__(self, status: int, detail: str):
        super().__init__(f"Transifex API error {status}: {detail}")
        self.status = status
        self.detail = detail


@dataclass(frozen=True)
class Project:
    id: str
    name: str
    slug: str
    private: bool
    archived: bool
    source_language: str
    homepage_url: str
    tags: tuple[str, ...]
    translation_memory_fillup: bool
    modified: datetime

    @classmethod
    def from_api(cls, data: dict) -> "Project":
        attributes = data["attributes"]
        return cls(
            id=data["id"],
            name=attributes["name"],
            slug=attributes["slug"],
            private=attributes["private"],
            archived=attributes["archived"],
            source_language=data["relationships"]["source_language"]["data"]["id"].removeprefix("l:"),
            homepage_url=attributes["homepage_url"],
            tags=clean_tags(attributes["tags"]),
            translation_memory_fillup=attributes["translation_memory_fillup"],
            modified=datetime.strptime(attributes["datetime_modified"], API_DATETIME_FORMAT),
        )


@dataclass(frozen=True)
class Team:
    id: str
    name: str

    @classmethod
    def from_api(cls, data: dict) -> "Team":
        return cls(id=data["id"], name=data["attributes"]["name"])


class TransifexClient:
    def __init__(self, token: str, organisation: str, timeout: float = REQUEST_TIMEOUT_SECONDS):
        self.organisation_id = f"o:{organisation}"
        self.timeout = timeout
        self._session = requests.Session()
        self._session.headers.update(
            {
                "Accept": "application/vnd.api+json",
                "Authorization": f"Bearer {token}",
            }
        )

    def projects(self) -> list[Project]:
        return [
            Project.from_api(item)
            for item in self._get_all("/projects", {"filter[organization]": self.organisation_id})
        ]

    def teams(self) -> list[Team]:
        return [Team.from_api(item) for item in self._get_all("/teams", {"filter[organization]": self.organisation_id})]

    def create_project(self, **fields) -> Project:
        """Creates a project in the organisation from new_project_payload's fields and returns it."""
        payload = new_project_payload(self.organisation_id, **fields)
        return Project.from_api(self._request("POST", f"{API_BASE}/projects", json=payload)["data"])

    def resource_slugs(self, project_id: str) -> list[str]:
        return [item["attributes"]["slug"] for item in self._get_all("/resources", {"filter[project]": project_id})]

    def project(self, project_id: str) -> Project:
        return Project.from_api(self._request("GET", f"{API_BASE}/projects/{project_id}")["data"])

    def set_project_tags(self, project_id: str, tags: tuple[str, ...]) -> Project:
        """Replaces the project's tags and returns the updated project."""
        length = len(",".join(tags))
        if length > MAX_JOINED_TAGS_LENGTH:
            raise ValueTooLongError("Tags", length, MAX_JOINED_TAGS_LENGTH)
        return self._update_project(project_id, {"tags": list(tags)})

    def set_homepage_url(self, project_id: str, url: str) -> Project:
        """Replaces the project's homepage URL (empty to clear it) and returns the updated project."""
        _check_homepage_url(url)
        return self._update_project(project_id, {"homepage_url": url})

    def set_translation_memory_fillup(self, project_id: str, enabled: bool) -> Project:
        """Turns filling up translations from translation memory on or off and returns the updated project."""
        return self._update_project(project_id, {"translation_memory_fillup": enabled})

    def _update_project(self, project_id: str, attributes: dict) -> Project:
        payload = {"data": {"type": "projects", "id": project_id, "attributes": attributes}}
        return Project.from_api(self._request("PATCH", f"{API_BASE}/projects/{project_id}", json=payload)["data"])

    def _get_all(self, path: str, params: dict) -> list[dict]:
        """Fetches every page of a JSON:API collection."""
        body = self._request("GET", API_BASE + path, params=params)
        items = list(body["data"])
        while body["links"].get("next"):
            body = self._request("GET", body["links"]["next"])
            items.extend(body["data"])
        return items

    def _request(self, method: str, url: str, params: dict | None = None, json: dict | None = None) -> dict:
        headers = {"Content-Type": "application/vnd.api+json"} if json is not None else None
        for _ in range(MAX_RATE_LIMIT_RETRIES):
            response = self._session.request(method, url, params=params, json=json, headers=headers, timeout=self.timeout)
            if response.status_code != 429:
                break
            time.sleep(int(response.headers.get("Retry-After", 1)))
        if not response.ok:
            raise TransifexError(response.status_code, _error_detail(response))
        return response.json()


def new_project_payload(
    organisation_id: str,
    *,
    name: str,
    slug: str,
    private: bool,
    license: str,
    source_language: str,
    homepage_url: str,
    repository_url: str,
    team_id: str,
) -> dict:
    """Builds the JSON:API body for creating a project, rejecting values Transifex cannot store."""
    _check_homepage_url(homepage_url)
    if len(repository_url) > MAX_REPOSITORY_URL_LENGTH:
        raise ValueTooLongError("Repository URL", len(repository_url), MAX_REPOSITORY_URL_LENGTH)
    return {
        "data": {
            "type": "projects",
            "attributes": {
                "name": name,
                "slug": slug,
                "private": private,
                "license": license,
                "homepage_url": homepage_url,
                "repository_url": repository_url,
            },
            "relationships": {
                "organization": {"data": {"type": "organizations", "id": organisation_id}},
                "source_language": {"data": {"type": "languages", "id": f"l:{source_language}"}},
                "team": {"data": {"type": "teams", "id": team_id}},
            },
        }
    }


def _check_homepage_url(url: str) -> None:
    if len(url) > MAX_HOMEPAGE_URL_LENGTH:
        raise ValueTooLongError("Homepage URL", len(url), MAX_HOMEPAGE_URL_LENGTH)


def clean_tags(tags: list[str]) -> tuple[str, ...]:
    """Strips surrounding whitespace, which Transifex keeps when tags are entered as a comma-separated list."""
    return tuple(dict.fromkeys(tag.strip() for tag in tags if tag.strip()))


def _error_detail(response: requests.Response) -> str:
    try:
        errors = response.json()["errors"]
        return "; ".join(e.get("detail") or e.get("title", "") for e in errors)
    except (ValueError, KeyError, TypeError):
        return response.text or response.reason
