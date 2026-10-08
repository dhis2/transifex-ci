# Parses and validates project values typed into the maintenance tool's dialogs.
# Each parser returns the cleaned value or raises ValueError with a message for the user.

import re
from urllib.parse import urlparse


def parse_homepage_url(text: str) -> str:
    """Parses a homepage URL as typed by the user; empty text clears the homepage."""
    url = text.strip()
    parsed = urlparse(url)
    if url and (parsed.scheme not in ("http", "https") or not parsed.netloc):
        raise ValueError("Homepage must be an http:// or https:// URL, or empty.")
    return url


MAX_NAME_LENGTH = 255
SLUG_PATTERN = re.compile(r"[a-zA-Z0-9_-]+")


def suggest_slug(name: str) -> str:
    """Derives a slug from a project name, e.g. "APP: Dashboard" becomes "app-dashboard"."""
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:MAX_NAME_LENGTH]


def parse_project_name(text: str) -> str:
    name = text.strip()
    if not name:
        raise ValueError("Name is required.")
    if len(name) > MAX_NAME_LENGTH:
        raise ValueError(f"Name must be at most {MAX_NAME_LENGTH} characters.")
    return name


def parse_slug(text: str) -> str:
    slug = text.strip()
    if not slug:
        raise ValueError("Slug is required.")
    if len(slug) > MAX_NAME_LENGTH or not SLUG_PATTERN.fullmatch(slug):
        raise ValueError(f"Slug may only contain letters, digits, '-' and '_' (at most {MAX_NAME_LENGTH} characters).")
    return slug
