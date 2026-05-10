"""Defaults for definitions to use."""
from collections.abc import Sequence
import logging
from pathlib import Path
from typing import Final, Optional

from nomenclature.processor.region import RegionAggregationMapping
import yaml
import git
import nomenclature
import streamlit as st
from common_keys import SSKey

from .multi_load import (
    MergedDataStructureDefinition,
    read_multi_definitions,
    read_multi_region_processors,
)

logger: logging.Logger = logging.getLogger(__name__)

_data_root: Final[Path] = Path(__file__).parent / "data"

dimensions: Final[tuple[str, ...]] = (
    "model",
    "scenario",
    "region",
    "variable",
)

# Per-profile caches
_dsds: dict[str, nomenclature.DataStructureDefinition] = {}
_individual_dsds: dict[str, list[nomenclature.DataStructureDefinition]] = {}
_region_processors: dict[str, nomenclature.RegionProcessor | None] = {}


def _get_profile_name() -> str:
    return st.session_state.get(
        SSKey.VALIDATION_PROFILE,
        "iamcompact-default",
    )


def _get_profile_root(profile_name: str) -> Path:
    root = _data_root / "definition_repos" / profile_name
    if not root.is_dir():
        raise FileNotFoundError(f"Unknown profile '{profile_name}'")
    return root


def _get_definitions_paths(profile_name: str) -> list[Path]:
    return [
        _get_profile_root(profile_name) / "definitions",
    ]


#def _get_mappings_path(profile_name: str) -> Path:
#    return _get_profile_root(profile_name) / "mappings"

def _get_mappings_path(profile_name: str) -> Path:
    profile_root = _get_profile_root(profile_name)
    config_file = profile_root / "nomenclature.yaml"
    
    if config_file.exists():
        with open(config_file, "r") as f:
            config = yaml.safe_load(f)
            mapping_config = config.get("mappings", {})
            repo_name = mapping_config.get("repository")
            file_name = mapping_config.get("file")       
            
            if repo_name and file_name:
                specific_file = profile_root / repo_name / file_name
                if specific_file.exists():
                    return specific_file

    # Fallback to the local mappings folder if config fails
    return profile_root / "mappings"


def _load_definitions(
    profile_name: str,
    dimensions: Optional[Sequence[str]] = None,
):
    definitions_paths = _get_definitions_paths(profile_name)

    # Pull repos
    for parent in (_p.parent for _p in definitions_paths):
        if not parent.is_dir():
            continue
        for child in parent.iterdir():
            if (child / ".git").is_dir():
                repo = git.Repo(child)
                logger.debug("Pulling updates for %s", child)
                repo.remotes.origin.pull()

    if len(definitions_paths) > 1:
        return read_multi_definitions(
            definitions_paths,
            dimensions=dimensions,
            return_individual_dsds=True,
        )
    else:
        dsd = nomenclature.DataStructureDefinition(
            path=definitions_paths[0],
            dimensions=dimensions,
        )
        return dsd, [dsd]


#def _load_region_processor(profile_name: str):
#    mappings_path = _get_mappings_path(profile_name)
#    if not mappings_path.is_dir():
#        logger.info("No mappings directory for profile '%s'", profile_name)
#        return None
#
#    return nomenclature.RegionProcessor.from_directory(
#        path=mappings_path,
#        dsd=get_dsd(profile_name),
#    )

def _load_region_processor(profile_name: str):
    target_file = _get_mappings_path(profile_name)
    
    if not target_file.is_file():
        raise FileNotFoundError(f"Mapping file not found: {target_file}")

    dsd = get_dsd(profile_name)

    # Load specific mappings file
    mapping = RegionAggregationMapping.from_file(target_file)

    model_mapping = {}
    if isinstance(mapping.model, list):
        for model_name in mapping.model:
            model_mapping[model_name] = mapping
    else:
        model_mapping[mapping.model] = mapping

    return nomenclature.RegionProcessor(
        mappings=model_mapping,
        region_codelist=dsd.region,
        variable_codelist=dsd.variable
    )

def get_dsd(
    profile_name: Optional[str] = None,
    force_reload: bool = False,
    dimensions: Optional[Sequence[str]] = None,
) -> nomenclature.DataStructureDefinition:
    if profile_name is None:
        profile_name = _get_profile_name()

    if force_reload or profile_name not in _dsds:
        logger.info("Loading definitions for profile '%s'", profile_name)
        dsd, individuals = _load_definitions(
            profile_name,
            dimensions=dimensions,
        )
        _dsds[profile_name] = dsd
        _individual_dsds[profile_name] = individuals
        _region_processors.pop(profile_name, None)

    return _dsds[profile_name]


def get_region_processor(
    profile_name: Optional[str] = None,
    force_reload: bool = False,
):
    if profile_name is None:
        profile_name = _get_profile_name()

    if force_reload or profile_name not in _region_processors:
        _region_processors[profile_name] = _load_region_processor(profile_name)

    return _region_processors[profile_name]