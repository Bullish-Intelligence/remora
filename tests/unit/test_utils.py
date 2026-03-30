from __future__ import annotations

from remora.core.utils import mask_secret


def test_mask_secret_handles_empty_values() -> None:
    assert mask_secret(None) == "EMPTY"
    assert mask_secret("") == "EMPTY"


def test_mask_secret_masks_short_values() -> None:
    assert mask_secret("abc") == "****"


def test_mask_secret_keeps_prefix_for_long_values() -> None:
    assert mask_secret("abcdefghij") == "abcd****"
