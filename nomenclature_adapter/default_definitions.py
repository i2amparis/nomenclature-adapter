"""Defaults for definitions to use."""
from collections.abc import Sequence
import logging
import os
from pathlib import Path
import re
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

_profiles_dir_name: Final[str] = "profiles"
_profile_cache_env_var: Final[str] = "NOMENCLATURE_PROFILE_CACHE"
_profile_cache_app_name: Final[str] = "nomenclature-adapter"
DEFAULT_PROFILE: Final[str] = "iamcompact"

dimensions: Final[tuple[str, ...]] = (
    "model",
    "scenario",
    "region",
    "variable",
)
_default_profile_dimensions: Final[tuple[str, ...]] = dimensions
"""Alias for the module-level `dimensions` tuple, for use as a fallback
default inside functions that have their own `dimensions` parameter (which
would otherwise shadow the module-level name).
"""

# Per-profile caches
_dsds: dict[str, nomenclature.DataStructureDefinition] = {}
_individual_dsds: dict[str, list[nomenclature.DataStructureDefinition]] = {}
_region_processors: dict[str, nomenclature.RegionProcessor | None] = {}
_materialized_profiles: set[str] = set()
"""Names of profiles whose repositories have already been cloned/fetched in
this process. Deliberately separate from `_dsds`/`_region_processors`, so
that repository materialization is not tied to whether a DataStructureDefinition
or RegionProcessor has successfully been built for the profile.
"""


def _find_profiles_root() -> Path:
    for parent in (Path(__file__).resolve(), *Path(__file__).resolve().parents):
        profiles_root = parent / _profiles_dir_name
        if profiles_root.is_dir():
            return profiles_root

    raise FileNotFoundError(
        f"Could not find bundled validation profiles directory "
        f"'{_profiles_dir_name}'"
    )


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


def _profile_label(profile_file: Path) -> str:
    return profile_file.stem


def get_validation_profiles() -> dict[str, str]:
    """Return available validation profiles as display label -> profile name."""
    profiles_root = _find_profiles_root()
    profiles = {
        _profile_label(profile_file): profile_file.stem
        for profile_file in sorted(profiles_root.glob("*.yaml"))
    }

    default_profile_file = profiles_root / f"{DEFAULT_PROFILE}.yaml"
    default_profile_label = _profile_label(default_profile_file) \
        if default_profile_file.is_file() else DEFAULT_PROFILE
    if default_profile_label in profiles:
        return {
            default_profile_label: profiles.pop(default_profile_label),
            **profiles,
        }

    return profiles or {default_profile_label: DEFAULT_PROFILE}


def _get_profile_manifest(profile_name: str) -> Path | None:
    profile_filename = Path(profile_name).name
    if not profile_filename.endswith((".yaml", ".yml")):
        profile_filename = f"{profile_filename}.yaml"

    manifest = _find_profiles_root() / profile_filename
    if manifest.is_file():
        return manifest

    return None


def _sync_profile_manifest(manifest: Path, profile_root: Path) -> None:
    target = profile_root / "nomenclature.yaml"
    with manifest.open("r", encoding="utf-8") as stream:
        config = yaml.safe_load(stream) or {}
    # The "definitions" section of our own profile manifests is a
    # (currently unused) per-dimension file selector for readers of this
    # package's profile YAMLs; it is not part of nomenclature-iamc's own
    # NomenclatureConfig schema, which rejects the "file" sub-key with a
    # validation error. This package's own code never reads this section
    # either (definitions are always loaded from the whole "definitions/"
    # directory tree, see _get_definitions_paths), so strip it before
    # writing out the nomenclature.yaml that
    # nomenclature.DataStructureDefinition will parse directly.
    config.pop("definitions", None)
    new_content = yaml.safe_dump(config, sort_keys=False)
    if not target.is_file() \
            or target.read_text(encoding="utf-8") != new_content:
        target.write_text(new_content, encoding="utf-8")


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
        # `git clone --branch` only accepts a branch or tag name, not an
        # arbitrary commit SHA (the git server won't resolve it as a ref).
        # For a SHA-like `release`, clone the default branch (full history,
        # so the target commit's objects are fetched too) and let the
        # `repo.git.checkout(repo_ref)` call below check it out.
        is_commit_sha = bool(re.fullmatch(r"[0-9a-fA-F]{7,40}", repo_ref or ""))
        clone_kwargs = {"branch": repo_ref} \
            if repo_ref and not is_commit_sha else {}
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


def _materialize_profile(
    profile_name: str,
    force_reload: bool = False,
) -> Path | None:
    manifest = _get_profile_manifest(profile_name)
    if manifest is None:
        return None

    profile_root = _get_profile_cache_root() / "definition_repos" / manifest.stem
    profile_root.mkdir(parents=True, exist_ok=True)
    (profile_root / "definitions").mkdir(exist_ok=True)
    (profile_root / "mappings").mkdir(exist_ok=True)
    _sync_profile_manifest(manifest, profile_root)
    # Only actually clone/fetch the profile's repositories once per process
    # (per profile), unless force_reload is requested. This is deliberately
    # independent of `_dsds` (get_dsd's own cache) below: resolving a
    # profile's repository paths (e.g. for get_profile_repo_path) should not
    # require that the profile's DataStructureDefinition successfully
    # parses, and vice versa.
    if force_reload or profile_name not in _materialized_profiles:
        _materialize_profile_repositories(manifest, profile_root)
        _materialized_profiles.add(profile_name)
    return profile_root


def _get_profile_name() -> str:
    try:
        import streamlit as st
        from common_keys import SSKey
    except ImportError:
        return DEFAULT_PROFILE

    return st.session_state.get(SSKey.VALIDATION_PROFILE, DEFAULT_PROFILE)


def _get_profile_root(
    profile_name: str,
    force_reload: bool = False,
) -> Path:
    root = _materialize_profile(profile_name, force_reload=force_reload)
    if root is not None:
        return root

    root = _get_profile_cache_root() / "definition_repos" / profile_name
    if not root.is_dir():
        raise FileNotFoundError(f"Unknown profile '{profile_name}'")
    return root


def _get_definitions_paths(
    profile_name: str,
    dimensions: Optional[Sequence[str]] = None,
    force_reload: bool = False,
) -> tuple[list[Path], list[list[str]]]:
    """Return per-repository definitions paths and their dimensions.

    Each repository listed under `repositories:` in the profile manifest is
    expected to contribute its own `definitions/` subdirectory. Repositories
    with no such subdirectory are skipped. Repositories are returned in the
    order they are declared in the manifest, which is significant: when
    merged (see `multi_load.read_multi_definitions`), earlier repositories
    take precedence over later ones for overlapping codes. By convention (see
    e.g. the `iamcompact-nomenclature-definitions` and
    `transience-nomenclature-definitions` READMEs), a profile's
    project-specific definitions repository should therefore be listed
    *before* any shared/upstream repository (such as a `common-definitions`
    fork) it overrides or adds to.

    Since not every repository necessarily has definitions for every
    dimension (e.g. a `common-definitions` fork may have no `model` or
    `scenario` definitions of its own), and not every repository has its own
    `nomenclature.yaml` to declare which dimensions it covers, the set of
    dimensions actually present in each repository is determined by which of
    the requested dimensions have a matching subdirectory on disk.

    Parameters
    ----------
    profile_name : str
        Name of the validation profile.
    dimensions : sequence of str, optional
        Dimensions to look for in each repository. Optional, by default uses
        the profile manifest's own `dimensions:` list, falling back to this
        package's default dimensions if the manifest does not declare one.

    Returns
    -------
    (paths, per_path_dimensions) : tuple[list[Path], list[list[str]]]
        `paths` are the definitions directories to load (one per repository
        that has any matching dimension), and `per_path_dimensions` are the
        dimensions actually found in each of those directories, in the same
        order.
    """
    profile_root = _get_profile_root(profile_name, force_reload=force_reload)
    manifest_config = get_profile_manifest(profile_name)
    repositories = manifest_config.get("repositories", {})
    wanted_dimensions: list[str] = list(dimensions) if dimensions is not None \
        else list(manifest_config.get("dimensions") or _default_profile_dimensions)

    paths: list[Path] = []
    per_path_dimensions: list[list[str]] = []
    for repo_name in repositories:
        repo_definitions_path = profile_root / repo_name / "definitions"
        if not repo_definitions_path.is_dir():
            continue
        repo_dimensions: list[str] = [
            _dim for _dim in wanted_dimensions
            if (repo_definitions_path / _dim).is_dir()
        ]
        if not repo_dimensions:
            continue
        paths.append(repo_definitions_path)
        per_path_dimensions.append(repo_dimensions)
    return paths, per_path_dimensions


#def _get_mappings_path(profile_name: str) -> Path:
#    return _get_profile_root(profile_name) / "mappings"

def _get_mappings_path(
    profile_name: str,
    force_reload: bool = False,
) -> Path:
    profile_root = _get_profile_root(profile_name, force_reload=force_reload)
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
    force_reload: bool = False,
):
    definitions_paths, per_path_dimensions = _get_definitions_paths(
        profile_name, dimensions=dimensions, force_reload=force_reload,
    )
    if not definitions_paths:
        raise FileNotFoundError(
            f"No repository with a 'definitions' subdirectory found for "
            f"profile '{profile_name}'"
        )

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
            dimensions=per_path_dimensions,
            return_individual_dsds=True,
        )
    else:
        dsd = nomenclature.DataStructureDefinition(
            path=definitions_paths[0],
            dimensions=per_path_dimensions[0],
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

def _load_region_processor(profile_name: str, force_reload: bool = False):
    target_file = _get_mappings_path(profile_name, force_reload=force_reload)

    if not target_file.is_file():
        raise FileNotFoundError(f"Mapping file not found: {target_file}")

    dsd = get_dsd(profile_name, force_reload=force_reload)

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
            force_reload=force_reload,
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
        _region_processors[profile_name] = _load_region_processor(
            profile_name, force_reload=force_reload,
        )

    return _region_processors[profile_name]


def get_profile_manifest(profile_name: Optional[str] = None) -> dict:
    """Return the parsed YAML manifest for a validation profile.

    This gives other packages (e.g. a vetting-checks adapter) access to
    top-level keys in a profile manifest that this package itself does not
    interpret, without having to duplicate profile lookup and YAML parsing.

    Parameters
    ----------
    profile_name : str, optional
        Name of the validation profile. Optional, defaults to the currently
        selected profile (see `_get_profile_name`).

    Returns
    -------
    dict
        The parsed contents of the profile's manifest YAML file.

    Raises
    ------
    FileNotFoundError
        If no manifest is found for `profile_name`.
    """
    if profile_name is None:
        profile_name = _get_profile_name()
    manifest = _get_profile_manifest(profile_name)
    if manifest is None:
        raise FileNotFoundError(f"Unknown profile '{profile_name}'")
    with manifest.open("r", encoding="utf-8") as stream:
        return yaml.safe_load(stream) or {}


def get_profile_repo_path(
    repo_name: str,
    profile_name: Optional[str] = None,
    force_reload: bool = False,
) -> Path:
    """Return the local path of one of a profile's cloned definition repos.

    Materializes (clones/updates) the profile's repositories if needed. Like
    `get_dsd` and `get_region_processor`, repeated calls for the same profile
    reuse a per-process cache (independent of theirs) rather than re-fetching
    every repository on every call -- notably, this does *not* require that
    the profile's DataStructureDefinition itself successfully loads, so it
    remains usable even for profiles whose codelists currently fail to
    parse.

    Parameters
    ----------
    repo_name : str
        Name of the repository, as given as a key under `repositories:` in
        the profile manifest.
    profile_name : str, optional
        Name of the validation profile. Optional, defaults to the currently
        selected profile (see `_get_profile_name`).
    force_reload : bool, optional
        Whether to force re-fetching the profile's repositories even if
        already materialized in this process. Optional, by default False.

    Returns
    -------
    pathlib.Path
        Local path of the cloned repository.

    Raises
    ------
    FileNotFoundError
        If `profile_name` is unknown, or if it has no repository named
        `repo_name`.
    """
    if profile_name is None:
        profile_name = _get_profile_name()
    profile_root = _materialize_profile(profile_name, force_reload=force_reload)
    if profile_root is None:
        raise FileNotFoundError(f"Unknown profile '{profile_name}'")
    repo_path = profile_root / repo_name
    if not repo_path.is_dir():
        raise FileNotFoundError(
            f"Repository '{repo_name}' not found for profile '{profile_name}'"
        )
    return repo_path
