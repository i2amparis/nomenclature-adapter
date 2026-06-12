"""Defaults for definitions to use."""
from collections.abc import Sequence
import logging
import os
from pathlib import Path
import shutil
import sys
from typing import Final, Optional

from nomenclature.processor.region import RegionAggregationMapping
import yaml
import git
import nomenclature

from .multi_load import (
    MergedDataStructureDefinition,
    read_multi_definitions,
    read_multi_region_processors,
)

logger: logging.Logger = logging.getLogger(__name__)

_data_root: Final[Path] = Path(__file__).parent / "data"
_profiles_root: Final[Path] = _data_root / "profiles"
_profile_cache_env_var: Final[str] = "NOMENCLATURE_PROFILE_CACHE"
_profile_cache_app_name: Final[str] = "nomenclature-template"

_profile_labels: Final[dict[str, str]] = {
    "iamcompact-default": "IAM COMPACT Default",
    "transience": "TRANSIENCE",
}

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


def _default_cache_root() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / _profile_cache_app_name
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        if base:
            return Path(base) / _profile_cache_app_name

    return Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) \
        / _profile_cache_app_name


def _get_profile_cache_root() -> Path:
    configured_cache_root = os.environ.get(_profile_cache_env_var)
    if configured_cache_root:
        return Path(configured_cache_root).expanduser()
    return _default_cache_root()


def _profile_label(profile_name: str) -> str:
    if profile_name in _profile_labels:
        return _profile_labels[profile_name]
    return profile_name.replace("-", " ").replace("_", " ").title()


def get_validation_profiles() -> dict[str, str]:
    """Return available validation profiles as display label -> profile name."""
    profiles = {
        _profile_label(profile_file.stem): profile_file.stem
        for profile_file in sorted(_profiles_root.glob("*.yaml"))
    }

    if "IAM COMPACT Default" in profiles:
        return {
            "IAM COMPACT Default": profiles.pop("IAM COMPACT Default"),
            **profiles,
        }

    return profiles or {"IAM COMPACT Default": "iamcompact-default"}


def _get_profile_manifest(profile_name: str) -> Path | None:
    profile_filename = Path(profile_name).name
    if not profile_filename.endswith((".yaml", ".yml")):
        profile_filename = f"{profile_filename}.yaml"

    manifest = _profiles_root / profile_filename
    if manifest.is_file():
        return manifest

    return None


def _sync_profile_manifest(manifest: Path, profile_root: Path) -> None:
    target = profile_root / "nomenclature.yaml"
    if not target.is_file() or target.read_bytes() != manifest.read_bytes():
        shutil.copy2(manifest, target)


def _checkout_repository(
    profile_root: Path,
    repo_name: str,
    repo_config: dict,
) -> None:
    repo_url = repo_config.get("url")
    repo_ref = repo_config.get("release")
    repo_path = profile_root / repo_name

    if not repo_url:
        raise ValueError(f"Repository '{repo_name}' has no URL")

    if (repo_path / ".git").is_dir():
        repo = git.Repo(repo_path)
        logger.debug("Fetching updates for %s", repo_path)
        repo.remotes.origin.fetch()
    elif repo_path.exists():
        logger.warning(
            "Repository path %s already exists but is not a git repository",
            repo_path,
        )
        return
    else:
        logger.info("Cloning %s into %s", repo_url, repo_path)
        clone_kwargs = {"branch": repo_ref} if repo_ref else {}
        repo = git.Repo.clone_from(repo_url, repo_path, **clone_kwargs)

    if repo_ref:
        repo.git.checkout(repo_ref)
        try:
            repo.git.pull("origin", repo_ref)
        except git.GitCommandError:
            logger.debug("Could not pull ref '%s' for %s", repo_ref, repo_path)
    else:
        repo.remotes.origin.pull()


def _materialize_profile_repositories(manifest: Path, profile_root: Path) -> None:
    with manifest.open("r", encoding="utf-8") as stream:
        config = yaml.safe_load(stream) or {}
    if not isinstance(config, dict):
        raise ValueError(f"Profile manifest '{manifest}' must contain a mapping")

    repositories = config.get("repositories", {})
    if not isinstance(repositories, dict):
        raise ValueError(
            f"Profile manifest '{manifest}' has invalid repositories section"
        )

    for repo_name, repo_config in repositories.items():
        if not isinstance(repo_config, dict):
            raise ValueError(
                f"Repository '{repo_name}' in '{manifest}' must be a mapping"
            )
        _checkout_repository(profile_root, repo_name, repo_config)


def _materialize_profile(profile_name: str) -> Path | None:
    manifest = _get_profile_manifest(profile_name)
    if manifest is None:
        return None

    profile_root = _get_profile_cache_root() / "definition_repos" / manifest.stem
    profile_root.mkdir(parents=True, exist_ok=True)
    (profile_root / "definitions").mkdir(exist_ok=True)
    (profile_root / "mappings").mkdir(exist_ok=True)
    _sync_profile_manifest(manifest, profile_root)
    _materialize_profile_repositories(manifest, profile_root)
    return profile_root


def _get_profile_name() -> str:
    try:
        import streamlit as st
        from common_keys import SSKey
    except ImportError:
        return "iamcompact-default"

    return st.session_state.get(SSKey.VALIDATION_PROFILE, "iamcompact-default")


def _get_profile_root(profile_name: str) -> Path:
    root = _materialize_profile(profile_name)
    if root is not None:
        return root

    root = _get_profile_cache_root() / "definition_repos" / profile_name
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
