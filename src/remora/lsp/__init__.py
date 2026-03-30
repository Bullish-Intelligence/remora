"""LSP adapter package."""

_LSP_INSTALL_MESSAGE = (
    "LSP support requires pygls. Install with: uv sync --extra lsp\n"
    "See docs/HOW_TO_USE_REMORA.md#lsp-setup for full setup instructions."
)


def create_lsp_server(*args, **kwargs):
    """Create the LSP server, raising a clear error if pygls is missing."""
    try:
        from remora.lsp.server import create_lsp_server as _create
    except ImportError as exc:
        raise ImportError(_LSP_INSTALL_MESSAGE) from exc
    return _create(*args, **kwargs)


def create_lsp_server_standalone(*args, **kwargs):
    """Create standalone LSP server, raising a clear error if pygls is missing."""
    try:
        from remora.lsp.server import create_lsp_server_standalone as _create
    except ImportError as exc:
        raise ImportError(_LSP_INSTALL_MESSAGE) from exc
    return _create(*args, **kwargs)


__all__ = ["create_lsp_server", "create_lsp_server_standalone"]
