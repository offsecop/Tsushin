"""
Input sanitization utilities for API routes.

Provides functions to strip HTML/script tags from user-supplied text fields
to prevent stored XSS attacks.

NOTE: This currently covers agent name/description fields.
TODO: Apply similar sanitization to other entities:
  - Contacts (friendly_name) in routes_contacts.py
  - Personas (name, description) in routes_personas.py
  - Tone Presets (name, description) in routes_agents.py
  - Projects (name, description) in routes_projects.py
  - Flows (name, description) in routes_flows.py
  - API Clients (name) in routes_api_clients.py
  - Knowledge Base entries in routes_knowledge_base.py
"""

import re


# Pattern matches HTML tags including self-closing, comments, and script blocks
_HTML_TAG_RE = re.compile(r"<[^>]+>", re.DOTALL)


def strip_html_tags(value: str) -> str:
    """
    Remove all HTML tags from a string.

    This is a defense-in-depth measure against stored XSS.  The frontend
    should also sanitize on render, but stripping tags on input ensures
    malicious payloads are never persisted.

    Examples:
        >>> strip_html_tags('<script>alert(1)</script>')
        'alert(1)'
        >>> strip_html_tags('Hello <b>world</b>')
        'Hello world'
        >>> strip_html_tags('plain text')
        'plain text'
        >>> strip_html_tags('<img src=x onerror=alert(1)>')
        ''
    """
    if not value:
        return value
    return _HTML_TAG_RE.sub("", value)


def sanitize_text_field(value: str | None) -> str | None:
    """
    Sanitize an optional text field: strip HTML tags and trim whitespace.

    Returns None unchanged if the input is None.
    """
    if value is None:
        return None
    cleaned = strip_html_tags(value)
    return cleaned.strip() if cleaned else cleaned
