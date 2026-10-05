"""Tests for orchestrator.report.__init__ — the pinned public surface."""

from __future__ import annotations

import orchestrator.report as report_pkg


def test_pinned_surface_importable() -> None:
    """The backend imports exactly these names; they must never disappear."""
    from orchestrator.report import (  # noqa: F401
        build_report,
        export_pdf,
        render_markdown,
    )

    assert callable(build_report)
    assert callable(render_markdown)
    assert callable(export_pdf)


def test_models_module_exposed() -> None:
    assert hasattr(report_pkg, "models")
    assert hasattr(report_pkg.models, "Report")
    assert hasattr(report_pkg.models, "ChartSpec")


def test_styles_module_exposed() -> None:
    assert hasattr(report_pkg, "styles")
    assert hasattr(report_pkg.styles, "get_style")


def test_all_names_resolve() -> None:
    for name in report_pkg.__all__:
        assert getattr(report_pkg, name, None) is not None, f"__all__ entry missing: {name}"


def test_signature_is_pinned() -> None:
    """build_report(run_result: dict, style: str = 'default') -> dict."""
    import inspect

    signature = inspect.signature(report_pkg.build_report)
    params = list(signature.parameters.values())
    assert [p.name for p in params] == ["run_result", "style"]
    assert params[1].default == "default"


def test_export_pdf_signature_is_pinned() -> None:
    import inspect

    signature = inspect.signature(report_pkg.export_pdf)
    params = list(signature.parameters.values())
    assert [p.name for p in params] == ["source", "out_path"]
