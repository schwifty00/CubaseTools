"""Extractor mixins for CprParser.

Each mixin groups related extraction methods by domain.
They access shared state (self.data, self.project, self._track_positions)
from the CprParser instance via self.
"""

from cubasetools.core.extractors.media import MediaExtractor
from cubasetools.core.extractors.metadata import MetadataExtractor
from cubasetools.core.extractors.mixer import MixerExtractor
from cubasetools.core.extractors.plugins import PluginExtractor
from cubasetools.core.extractors.tracks import TrackExtractor

__all__ = [
    "MediaExtractor",
    "MetadataExtractor",
    "MixerExtractor",
    "PluginExtractor",
    "TrackExtractor",
]
