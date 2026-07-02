# -*- coding: utf-8 -*-
"""Optional template rendering helpers for small report fragments.

This module is intentionally fragment-scoped: callers should expose explicit
helpers with literal fallbacks rather than treating it as a full report renderer.
"""

import logging
from pathlib import Path
from typing import Any, Mapping, Optional

logger = logging.getLogger(__name__)

DEFAULT_TEMPLATE_DIR = Path(__file__).resolve().parents[2] / "templates"
EMAIL_REPORT_FOOTER_TEMPLATE = "email_report_footer.md.j2"


def _create_jinja_environment(template_dir: Path) -> Any:
    from jinja2 import Environment, FileSystemLoader, StrictUndefined

    return Environment(
        loader=FileSystemLoader(str(template_dir)),
        autoescape=False,
        undefined=StrictUndefined,
        keep_trailing_newline=True,
    )


def _render_template(
    template_name: str,
    context: Optional[Mapping[str, Any]] = None,
    *,
    template_dir: Optional[Path] = None,
) -> Optional[str]:
    """Render a report fragment when optional Jinja support is available."""
    template_root = template_dir or DEFAULT_TEMPLATE_DIR
    try:
        environment = _create_jinja_environment(template_root)
    except ImportError as exc:
        logger.debug("Jinja2 unavailable; skipping report template %s: %s", template_name, exc)
        return None
    except Exception:
        logger.warning("Report template environment failed for %s; using literal fallback", template_name, exc_info=True)
        return None

    try:
        rendered = environment.get_template(template_name).render(**dict(context or {})).rstrip("\n")
    except Exception:
        logger.warning("Report template rendering failed for %s; using literal fallback", template_name, exc_info=True)
        return None

    if not rendered.strip():
        logger.warning("Report template %s rendered empty; using literal fallback", template_name)
        return None
    return rendered


def render_email_report_footer(*, template_dir: Optional[Path] = None) -> Optional[str]:
    """Render the email archive footer, or return None for the literal fallback."""
    rendered = _render_template(EMAIL_REPORT_FOOTER_TEMPLATE, {}, template_dir=template_dir)
    if rendered is None:
        return None
    return "\n\n" + rendered.lstrip("\n")
