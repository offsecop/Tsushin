"""
Tests for stored XSS prevention via input sanitization.

Validates that HTML/script tags are stripped from user-supplied text fields
by the sanitizer functions, preventing stored XSS payloads from reaching
the database.

The sanitizer unit tests verify strip_html_tags and sanitize_text_field
directly.  The validator pattern tests use standalone Pydantic models that
replicate the exact same @field_validator pattern used in
api/v1/routes_agents.py (AgentCreateRequest and AgentUpdateRequest),
proving the validator logic is correct without requiring the full
application import chain (which needs docker, etc.).
"""

import pytest
from typing import Optional
from pydantic import BaseModel, Field, ValidationError, field_validator

from api.sanitizers import strip_html_tags, sanitize_text_field


# ---------------------------------------------------------------------------
# Unit tests for the sanitizers module
# ---------------------------------------------------------------------------

class TestStripHtmlTags:
    """Tests for api.sanitizers.strip_html_tags."""

    def test_strips_script_tags(self):
        assert strip_html_tags('<script>alert(1)</script>') == 'alert(1)'

    def test_strips_nested_script(self):
        result = strip_html_tags('<script>alert("<script>nested</script>")</script>')
        assert '<script>' not in result
        assert '</script>' not in result

    def test_strips_img_onerror(self):
        assert strip_html_tags('<img src=x onerror=alert(1)>') == ''

    def test_strips_bold_tags(self):
        assert strip_html_tags('Hello <b>world</b>') == 'Hello world'

    def test_preserves_plain_text(self):
        assert strip_html_tags('plain text') == 'plain text'

    def test_strips_anchor_tags(self):
        assert strip_html_tags('<a href="javascript:alert(1)">click</a>') == 'click'

    def test_strips_div_with_style(self):
        assert strip_html_tags('<div style="background:url(javascript:alert(1))">text</div>') == 'text'

    def test_handles_empty_string(self):
        assert strip_html_tags('') == ''

    def test_strips_svg_onload(self):
        assert strip_html_tags('<svg onload=alert(1)>') == ''

    def test_strips_iframe(self):
        assert strip_html_tags('<iframe src="evil.com"></iframe>') == ''

    def test_preserves_angle_brackets_in_non_tags(self):
        # "5 > 3" does not form a valid HTML tag
        assert strip_html_tags('5 > 3') == '5 > 3'

    def test_strips_multiline_script(self):
        payload = '<script>\nalert(document.cookie)\n</script>'
        result = strip_html_tags(payload)
        assert '<script>' not in result
        assert '</script>' not in result

    def test_preserves_ampersand_entities(self):
        assert strip_html_tags('Tom &amp; Jerry') == 'Tom &amp; Jerry'

    def test_strips_event_handler_attributes(self):
        assert strip_html_tags('<body onload="alert(1)">') == ''

    def test_strips_multiple_tags(self):
        assert strip_html_tags('<b>one</b> <i>two</i> <u>three</u>') == 'one two three'


class TestSanitizeTextField:
    """Tests for api.sanitizers.sanitize_text_field."""

    def test_returns_none_for_none(self):
        assert sanitize_text_field(None) is None

    def test_strips_and_trims(self):
        assert sanitize_text_field('  <b>hello</b>  ') == 'hello'

    def test_strips_tags_preserves_text(self):
        assert sanitize_text_field('<script>alert(1)</script>') == 'alert(1)'


# ---------------------------------------------------------------------------
# Validator pattern tests — standalone Pydantic models that replicate
# the exact @field_validator pattern from api/v1/routes_agents.py
# ---------------------------------------------------------------------------

class _MockCreateRequest(BaseModel):
    """Mirrors AgentCreateRequest's name/description validator pattern."""
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=500)
    system_prompt: str = Field(..., min_length=1)

    @field_validator("name")
    @classmethod
    def sanitize_name(cls, v: str) -> str:
        cleaned = strip_html_tags(v)
        if not cleaned or not cleaned.strip():
            raise ValueError("Name must not be empty after removing HTML tags")
        return cleaned.strip()

    @field_validator("description")
    @classmethod
    def sanitize_description(cls, v: str | None) -> str | None:
        if v is None:
            return v
        return strip_html_tags(v).strip() or None


class _MockUpdateRequest(BaseModel):
    """Mirrors AgentUpdateRequest's name/description validator pattern."""
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=500)
    system_prompt: Optional[str] = None

    @field_validator("name")
    @classmethod
    def sanitize_name(cls, v: str | None) -> str | None:
        if v is None:
            return v
        cleaned = strip_html_tags(v)
        if not cleaned or not cleaned.strip():
            raise ValueError("Name must not be empty after removing HTML tags")
        return cleaned.strip()

    @field_validator("description")
    @classmethod
    def sanitize_description(cls, v: str | None) -> str | None:
        if v is None:
            return v
        return strip_html_tags(v).strip() or None


class TestAgentCreateValidatorPattern:
    """Proves the @field_validator pattern used in AgentCreateRequest works."""

    def _make(self, **kw):
        defaults = {"name": "Test Agent", "system_prompt": "You are a test."}
        defaults.update(kw)
        return _MockCreateRequest(**defaults)

    def test_plain_name_passes(self):
        req = self._make(name="My Agent")
        assert req.name == "My Agent"

    def test_script_tag_stripped_from_name(self):
        req = self._make(name='<script>alert(1)</script>Safe Name')
        assert '<script>' not in req.name
        assert 'Safe Name' in req.name

    def test_html_tags_stripped_from_name(self):
        req = self._make(name='<b>Bold</b> Agent')
        assert req.name == 'Bold Agent'

    def test_img_onerror_stripped(self):
        req = self._make(name='<img src=x onerror=alert(1)>Agent')
        assert req.name == 'Agent'
        assert '<img' not in req.name

    def test_name_script_tag_leaves_text_content(self):
        """<script>alert(1)</script> strips to 'alert(1)' which is valid text."""
        req = self._make(name='<script>alert(1)</script>')
        assert req.name == 'alert(1)'
        assert '<script>' not in req.name

    def test_name_only_self_closing_tag_raises(self):
        """A name that is only a self-closing tag becomes empty -> error."""
        with pytest.raises(ValidationError) as exc_info:
            _MockCreateRequest(
                name='<img src=x onerror=alert(1)>',
                system_prompt="test",
            )
        assert "Name must not be empty" in str(exc_info.value)

    def test_name_whitespace_after_strip_raises(self):
        with pytest.raises(ValidationError) as exc_info:
            _MockCreateRequest(name='<b> </b>', system_prompt="test")
        assert "Name must not be empty" in str(exc_info.value)

    def test_system_prompt_not_sanitized(self):
        """system_prompt may contain angle brackets for AI instructions."""
        req = self._make(
            system_prompt="Use <emphasis>strong</emphasis> language."
        )
        assert '<emphasis>' in req.system_prompt

    def test_description_sanitized(self):
        req = self._make(description='<script>xss</script>Safe desc')
        assert '<script>' not in (req.description or '')
        assert 'Safe desc' in (req.description or '')

    def test_description_all_tags_becomes_none(self):
        req = self._make(description='<img src=x onerror=alert(1)>')
        assert req.description is None


class TestAgentUpdateValidatorPattern:
    """Proves the @field_validator pattern used in AgentUpdateRequest works."""

    def _make(self, **kw):
        return _MockUpdateRequest(**kw)

    def test_none_name_passes(self):
        req = self._make()
        assert req.name is None

    def test_plain_name_passes(self):
        req = self._make(name="Updated Agent")
        assert req.name == "Updated Agent"

    def test_script_tag_stripped(self):
        req = self._make(name='<script>alert(1)</script>Updated')
        assert '<script>' not in req.name
        assert 'Updated' in req.name

    def test_name_only_tags_raises(self):
        with pytest.raises(ValidationError) as exc_info:
            _MockUpdateRequest(name='<img src=x onerror=alert(1)>')
        assert "Name must not be empty" in str(exc_info.value)

    def test_description_sanitized(self):
        req = self._make(description='<script>xss</script>Safe desc')
        assert '<script>' not in (req.description or '')
        assert 'Safe desc' in (req.description or '')
