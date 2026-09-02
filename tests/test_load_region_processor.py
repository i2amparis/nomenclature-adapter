"""Tests for `_load_region_processor`'s handling of profiles that don't
declare a region-mapping file.

Some newer projects (e.g. ENTICE) don't have any model-native-region
mappings defined yet. `DataStructureDefinition` loading still works fine for
such profiles (region/variable/model/scenario definitions are independent of
region mappings), but `RegionProcessor` construction previously always
raised `FileNotFoundError` regardless of whether a `mappings:` section was
declared in the profile manifest at all, or was declared but pointed at a
missing file. These tests lock in the fix: only the latter (a real
misconfiguration) still raises; the former now returns `None`, and that
`None` propagates safely through `get_invalid_model_regions`/`map_regions`.
"""
from pathlib import Path

import pytest
import yaml

from nomenclature_adapter import default_definitions as dd


@pytest.fixture
def fake_profile_root(tmp_path, monkeypatch):
    def _fake_get_profile_root(profile_name, force_reload=False):
        return tmp_path
    monkeypatch.setattr(dd, "_get_profile_root", _fake_get_profile_root)
    return tmp_path
###END fixture fake_profile_root


class TestMappingsPathAndRegionProcessorTolerance:

    def test_no_mappings_section_returns_none_path(self, fake_profile_root):
        (fake_profile_root / "nomenclature.yaml").write_text(
            yaml.safe_dump({"repositories": {}, "dimensions": ["region"]})
        )
        assert dd._get_mappings_path("fake-profile") is None
    ###END def test_no_mappings_section_returns_none_path

    def test_no_nomenclature_yaml_returns_none_path(self, fake_profile_root):
        # profile_root exists but nomenclature.yaml hasn't been written yet
        assert dd._get_mappings_path("fake-profile") is None
    ###END def test_no_nomenclature_yaml_returns_none_path

    def test_configured_mappings_section_returns_target_path(
            self, fake_profile_root,
    ):
        (fake_profile_root / "nomenclature.yaml").write_text(
            yaml.safe_dump({
                "mappings": {"repository": "my-defs", "file": "mappings/m.yaml"},
            })
        )
        result = dd._get_mappings_path("fake-profile")
        assert result == fake_profile_root / "my-defs" / "mappings" / "m.yaml"
    ###END def test_configured_mappings_section_returns_target_path

    def test_load_region_processor_returns_none_without_mappings_section(
            self, fake_profile_root,
    ):
        (fake_profile_root / "nomenclature.yaml").write_text(
            yaml.safe_dump({"repositories": {}})
        )
        assert dd._load_region_processor("fake-profile") is None
    ###END def test_load_region_processor_returns_none_without_mappings_section

    def test_load_region_processor_raises_for_missing_configured_file(
            self, fake_profile_root,
    ):
        (fake_profile_root / "nomenclature.yaml").write_text(
            yaml.safe_dump({
                "mappings": {"repository": "my-defs", "file": "mappings/m.yaml"},
            })
        )
        with pytest.raises(FileNotFoundError):
            dd._load_region_processor("fake-profile")
    ###END def test_load_region_processor_raises_for_missing_configured_file

###END class TestMappingsPathAndRegionProcessorTolerance
