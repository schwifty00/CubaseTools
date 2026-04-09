"""Plugin extraction mixin: VST3 plugins, PresetChunkXMLTree, presets,
deduplication, track assignment."""

from __future__ import annotations

import logging
import re

from cubasetools.core.constants import (
    PLUGIN_DEDUP_THRESHOLD,
    PRESET_ASSIGN_DISTANCE,
    PRESET_MERGE_DISTANCE,
)
from cubasetools.core.models import PluginInstance, Track, TrackType
from cubasetools.core.plugin_registry import interpret_plugin_parameters
from cubasetools.core.realworld import interpret_realworld, parse_realworld_params

logger = logging.getLogger(__name__)

# VST3 built-in channel components (not user plugins)
_BUILTIN_PLUGINS = frozenset({
    "Standard Panner", "Stereo Combined Panner", "Input Filter", "EQ",
    "Mono Panner", "Surround Panner", "Sampler Track",
})


class PluginExtractor:
    """Mixin for extracting plugins from binary .cpr data."""

    def _extract_plugins(self):
        """Extract plugins using two sources and merge them.

        1. VST3 'Plugin Name' entries - finds ALL plugins
        2. PresetChunkXMLTree blocks - provides parameter values for Waves plugins
        """
        try:
            self._index_preset_chunk_data()
            plugins_with_pos = self._extract_vst3_plugins()
            deduped = self._deduplicate_plugins(plugins_with_pos)
            self._assign_plugins_to_tracks(deduped)
        except Exception:
            logger.warning("Failed to extract plugins", exc_info=True)

    def _index_preset_chunk_data(self):
        """Parse PresetChunkXMLTree blocks and index them by position."""
        pattern = rb'PresetChunkXMLTree[^>]*>'
        for match in re.finditer(pattern, self.data):
            pos = match.start()
            region = self.data[pos : pos + 5000]

            pn_match = re.search(rb'<PluginName>([^<]+)</PluginName>', region)
            if not pn_match:
                continue

            plugin_name = pn_match.group(1).decode("utf-8", errors="ignore")

            preset_name = ""
            preset_match = re.search(rb'<Preset\s+Name="([^"]*)"', region)
            if preset_match:
                preset_name = preset_match.group(1).decode("utf-8", errors="ignore")

            plugin = PluginInstance(name=plugin_name)

            # Extract RealWorld parameters from active Setup A
            rw_match = re.search(
                rb'<PresetData\s+Setup="SETUP_A"[^>]*>\s*<Parameters\s+Type="RealWorld">\s*([^<]+)</Parameters>',
                region,
            )
            if rw_match:
                raw_params = rw_match.group(1).decode("utf-8", errors="ignore").strip()
                values = parse_realworld_params(raw_params)
                interpret_realworld(plugin, plugin_name, values, preset_name)

            # Fallback: XML attribute-based params
            if not plugin.parameters and not plugin.eq_bands and not plugin.compressor:
                for param_match in re.finditer(
                    rb'<(\w+)\s+[^>]*?(?:name|Name)="([^"]+)"[^>]*?(?:value|Value)="([^"]+)"',
                    region,
                ):
                    param_name = param_match.group(2).decode("utf-8", errors="ignore")
                    try:
                        param_val = float(param_match.group(3).decode("utf-8", errors="ignore"))
                        plugin.parameters[param_name] = param_val
                    except ValueError:
                        pass
                if plugin.parameters:
                    interpret_plugin_parameters(plugin)

            self._preset_chunk_data[pos] = plugin

    def _extract_vst3_plugins(self) -> list[tuple[PluginInstance, int]]:
        """Extract all user plugins from VST3 'Plugin Name' entries."""
        results: list[tuple[PluginInstance, int]] = []

        for m in re.finditer(rb'Plugin Name\x00', self.data):
            pos = m.start()
            after = self.data[pos + 12 : pos + 100]
            name_match = re.match(rb'.{0,8}?([\x20-\x7e]{2,50})', after)
            if not name_match:
                continue

            plugin_name = name_match.group(1).decode("utf-8", errors="ignore").strip()

            if plugin_name in _BUILTIN_PLUGINS:
                continue

            before = self.data[max(0, pos - 300) : pos]
            is_insert = b'Slot\x00' in before or b'Bay Program\x00' in before

            plugin = PluginInstance(name=plugin_name)

            merged = self._merge_preset_data(plugin, pos)
            if merged:
                plugin = merged

            results.append((plugin, pos))

        return results

    def _merge_preset_data(
        self, plugin: PluginInstance, vst3_pos: int
    ) -> PluginInstance | None:
        """Try to find matching PresetChunkXMLTree data for a VST3 plugin entry."""
        base_name = plugin.name.replace(" Mono", "").replace(" Stereo", "")
        base_name = base_name.replace(" Mono/Stereo", "")

        for chunk_pos, chunk_plugin in self._preset_chunk_data.items():
            if abs(chunk_pos - vst3_pos) > PRESET_MERGE_DISTANCE:
                continue
            chunk_base = chunk_plugin.name.replace(" Mono", "").replace(" Stereo", "")
            if chunk_base == base_name:
                merged = PluginInstance(name=plugin.name)
                merged.eq_bands = chunk_plugin.eq_bands
                merged.compressor = chunk_plugin.compressor
                merged.parameters = chunk_plugin.parameters
                merged.bypassed = chunk_plugin.bypassed
                return merged

        return None

    def _deduplicate_plugins(
        self, plugins: list[tuple[PluginInstance, int]]
    ) -> list[tuple[PluginInstance, int]]:
        """Remove duplicate plugin entries."""
        if not plugins:
            return []

        plugins.sort(key=lambda x: x[1])

        deduped: list[tuple[PluginInstance, int]] = []
        i = 0
        while i < len(plugins):
            current_plugin, current_pos = plugins[i]
            best = current_plugin
            best_pos = current_pos

            j = i + 1
            while j < len(plugins):
                next_plugin, next_pos = plugins[j]
                if next_pos - current_pos > PLUGIN_DEDUP_THRESHOLD:
                    break
                cur_base = current_plugin.name.replace(" Mono", "").replace(" Stereo", "").replace(" Mono/Stereo", "")
                next_base = next_plugin.name.replace(" Mono", "").replace(" Stereo", "").replace(" Mono/Stereo", "")
                if next_base == cur_base:
                    best_score = len(best.parameters) + len(best.eq_bands) + (1 if best.compressor else 0)
                    next_score = len(next_plugin.parameters) + len(next_plugin.eq_bands) + (1 if next_plugin.compressor else 0)
                    if next_score > best_score:
                        best = next_plugin
                        best_pos = next_pos
                    j += 1
                else:
                    break

            deduped.append((best, best_pos))
            i = j if j > i + 1 else i + 1

        return deduped

    def _assign_plugins_to_tracks(
        self, plugins: list[tuple[PluginInstance, int]]
    ):
        """Assign plugins to tracks based on binary position."""
        if not self._track_positions or not plugins:
            if plugins and not self.project.tracks:
                default_track = Track(name="Master", track_type=TrackType.MASTER, index=0)
                self.project.tracks.append(default_track)
                for plugin, _ in plugins:
                    plugin.slot_index = len(default_track.plugins)
                    default_track.plugins.append(plugin)
            return

        sorted_tracks = sorted(self._track_positions, key=lambda x: x[1])

        for plugin, plugin_pos in plugins:
            assigned_track = sorted_tracks[0][0]
            for track, track_pos in sorted_tracks:
                if track_pos <= plugin_pos:
                    assigned_track = track
                else:
                    break

            plugin.slot_index = len(assigned_track.plugins)
            assigned_track.plugins.append(plugin)

    def _extract_plugin_presets(self):
        """Extract preset names from XML Preset entries and assign to plugins."""
        try:
            presets: list[tuple[int, str]] = []
            for m in re.finditer(rb'<Preset\s+Name="([^"]*)"', self.data):
                name = m.group(1).decode("utf-8", errors="ignore")
                if name:
                    presets.append((m.start(), name))

            if not presets:
                return

            all_plugins: list[tuple[PluginInstance, int]] = []
            sorted_tracks = sorted(self._track_positions, key=lambda x: x[1])
            for track, track_pos in sorted_tracks:
                for plugin in track.plugins:
                    all_plugins.append((plugin, track_pos))

            for preset_pos, preset_name in presets:
                best_plugin = None
                best_dist = float("inf")
                for plugin, plugin_pos in all_plugins:
                    dist = abs(preset_pos - plugin_pos)
                    if dist < best_dist and dist < PRESET_ASSIGN_DISTANCE:
                        best_dist = dist
                        best_plugin = plugin
                if best_plugin and not best_plugin.preset_name:
                    best_plugin.preset_name = preset_name
        except Exception:
            logger.warning("Failed to extract plugin presets", exc_info=True)
