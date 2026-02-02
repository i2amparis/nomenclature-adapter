"""Defaults for definitions to use."""
from collections.abc import Sequence
import logging
from pathlib import Path
from typing import Final, Optional

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


def _get_mappings_path(profile_name: str) -> Path:
    return _get_profile_root(profile_name) / "mappings"


def _load_definitions(
    profile_name: str,
    dimensions: Optional[Sequence[str]] = None,
):
    definitions_paths = _get_definitions_paths(profile_name)

    # Pull repos (unchanged logic)
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


def _load_region_processor(profile_name: str):
    mappings_path = _get_mappings_path(profile_name)
    if not mappings_path.is_dir():
        logger.info("No mappings directory for profile '%s'", profile_name)
        return None

    return nomenclature.RegionProcessor.from_directory(
        path=mappings_path,
        dsd=get_dsd(profile_name),
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
