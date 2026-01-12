"""
Defaults for definitions to use.

Profile-aware implementation compatible with Pydantic v2 and
modern nomenclature / nomenclature-iamc.
"""

from collections.abc import Sequence
import logging
from pathlib import Path
from typing import Optional

import git
import nomenclature

logger = logging.getLogger(__name__)

# -------------------------------------------------------------------
# Paths & constants
# -------------------------------------------------------------------

_DATA_ROOT = Path(__file__).parent / "data"
_DEFINITION_REPOS_ROOT = _DATA_ROOT / "definition_repos"
_MAPPINGS_PATH = _DEFINITION_REPOS_ROOT / "mappings"

dimensions: tuple[str, ...] = (
    "model",
    "scenario",
    "region",
    "variable",
)

# -------------------------------------------------------------------
# Caches (PROFILE-SCOPED)
# -------------------------------------------------------------------

_dsd_cache: dict[str, nomenclature.DataStructureDefinition] = {}
_region_processor_cache: dict[str, nomenclature.RegionProcessor] = {}

# -------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------

def _pull_git_repos(parent: Path) -> None:
    """Pull updates for any git repositories under parent."""
    if not parent.is_dir():
        return

    for child in parent.iterdir():
        if not child.is_dir():
            continue
        if (child / ".git").is_dir():
            try:
                repo = git.Repo(child)
                logger.debug("Pulling updates for nomenclature repo in %s", child)
                repo.remotes.origin.pull()
            except Exception as exc:
                logger.warning(
                    "Failed to pull repo in %s: %s",
                    child,
                    exc,
                )

# -------------------------------------------------------------------
# Core loaders
# -------------------------------------------------------------------

def get_dsd(
    profile_name: str | None = None,
    *,
    force_reload: bool = False,
    dimensions_override: Optional[Sequence[str]] = None,
) -> nomenclature.DataStructureDefinition:
    """
    Return a DataStructureDefinition for the given profile.

    Parameters
    ----------
    profile_name
        Name of the folder under `data/definition_repos`.
    force_reload
        Reload definitions even if cached.
    dimensions_override
        Optional override for dimensions.
    """
    if profile_name is None:
        try:
            import streamlit as st
            from common_keys import SSKey
            profile_name = st.session_state.get(
                SSKey.VALIDATION_PROFILE,
                "iamcompact-default",
            )
        except Exception:
            profile_name = "iamcompact-default"

    if force_reload:
        _dsd_cache.pop(profile_name, None)
        _region_processor_cache.pop(profile_name, None)

    if profile_name not in _dsd_cache:
        profile_path = _DEFINITION_REPOS_ROOT / profile_name
        if not profile_path.is_dir():
            raise FileNotFoundError(
                f"Definition profile not found: {profile_path}"
            )

        # Pull git repos (if any)
        _pull_git_repos(profile_path.parent)

        logger.info(
            "Loading DataStructureDefinition from profile: %s",
            profile_path,
        )

        _dsd_cache[profile_name] = nomenclature.DataStructureDefinition(
            path=profile_path,
            dimensions=dimensions_override or dimensions,
        )

    return _dsd_cache[profile_name]


def get_region_processor(
    profile_name: str | None = None,
    *,
    force_reload: bool = False,
) -> nomenclature.RegionProcessor:
    """
    Return a RegionProcessor.

    If profile_name is None, fall back to the profile stored in session state
    or the default profile.
    """
    if profile_name is None:
        try:
            # Lazy import to avoid Streamlit dependency at import time
            import streamlit as st
            from common_keys import SSKey

            profile_name = st.session_state.get(
                SSKey.VALIDATION_PROFILE,
                "iamcompact-default",
            )
        except Exception:
            # Absolute fallback (e.g. CLI usage)
            profile_name = "iamcompact-default"

    if force_reload:
        _region_processor_cache.pop(profile_name, None)

    if profile_name not in _region_processor_cache:
        logger.info(
            "Loading RegionProcessor for profile '%s' from mappings path: %s",
            profile_name,
            _MAPPINGS_PATH,
        )

        dsd = get_dsd(profile_name)

        _region_processor_cache[profile_name] = (
            nomenclature.RegionProcessor.from_directory(
                path=_MAPPINGS_PATH,
                dsd=dsd,
            )
        )

    return _region_processor_cache[profile_name]


# -------------------------------------------------------------------
# Utilities
# -------------------------------------------------------------------

def list_profiles() -> list[str]:
    """List available definition profiles."""
    if not _DEFINITION_REPOS_ROOT.is_dir():
        return []

    return sorted(
        p.name
        for p in _DEFINITION_REPOS_ROOT.iterdir()
        if p.is_dir() and p.name != "mappings"
    )
