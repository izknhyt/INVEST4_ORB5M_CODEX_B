"""Compatibility wrapper exposing :class:`MeanReversionStrategy`.

The original placeholder lived in this module.  The full implementation now
resides in :mod:`strategies.mean_reversion` but we keep this shim so that
existing manifests and tests referencing ``strategies.reversion_stub`` continue
working without modification.
"""
from __future__ import annotations

from strategies.mean_reversion import MeanReversionStrategy

__all__ = ["MeanReversionStrategy"]
