import os
import shutil
import tempfile
import functools
from pathlib import Path
from nomenclature import DataStructureDefinition
from nomenclature.processor import RegionProcessor

_definitions_root: Path = (Path(__file__).parent.parent /'iamcompact_nomenclature'/ 'data' / 'definition_repos').resolve()

# Global paths, dynamically set by _set_profile_paths.
_dsd_paths: list[Path] = []
_mappings_path: Path = _definitions_root / 'mappings' 

# Global cache for the RegionProcessor
_region_processor: RegionProcessor | None = None

dimensions = (
    'model',
    'scenario',
    'region',
    'variable',
)
"""Defines which dimensions are provided by the data structure definition object
that is returned by `get_dsd`.

At the moment, this attribute is not used by the `iamcompact-nomenclature`
package itself (the dimensions are now specified in the nomenclature.yaml files
in the directories under `data`), but is kept since it may be used by external
code, and may be useful for internal use again in the future.
"""

def get_dsd_path() -> list[Path]:
    """Returns the currently active DSD paths."""
    return _dsd_paths

def get_mappings_path() -> Path:
    """Returns the currently active mappings path."""
    return _mappings_path

# CORE LOGIC TO SWITCH PROFILES

def _set_profile_paths(profile_name: str) -> None:
    """
    INTERNAL: Sets the global DSD path based on the profile name.
    It targets the directory containing the profile-specific nomenclature.yaml.
    """
    global _dsd_paths
    
    # 1. Determine the correct profile directory based on the input name
    #if profile_name == 'iamcompact-default':
    #   profile_directory = _definitions_root / 'definitions'
    #elif profile_name == 'new-project-defs':
    #   profile_directory = _definitions_root / profile_name 
    #else:
    #  raise ValueError(f"Unknown nomenclature profile: {profile_name}")
    
    if profile_name == 'iamcompact-default':
        profile_directory = _definitions_root / 'definitions'
    else:
        profile_directory = _definitions_root / profile_name

    # --- DIAGNOSTIC PRINTING ---
    print(f"DIAGNOSTIC: __file__ is: {Path(__file__).resolve()}")
    print(f"DIAGNOSTIC: Calculated _definitions_root is: {_definitions_root}")
    print(f"DIAGNOSTIC: Checking for profile directory: {profile_directory}")
    print(f"DIAGNOSTIC: Does the directory exist? {profile_directory.is_dir()}")
    # --- END DIAGNOSTIC PRINTING ---
    
    # 2. Validation Check
    if not profile_directory.is_dir():
        raise FileNotFoundError(
            f"Profile definitions directory for '{profile_name}' not found at {profile_directory}"
        )
        
    # 3. Set the global DSD path
    _dsd_paths = [profile_directory]


# FUNCTIONS TO GET DSD AND PROCESSOR

@functools.lru_cache()
def get_dsd(
    name: str = "iamcompact-default",
    repo: str = None,
    revision: str = None,
    profile_name: str = 'iamcompact-default', # New argument
    force_reload: bool = False
) -> DataStructureDefinition:
    """
    Returns the DataStructureDefinition object, first setting the profile paths.
    Caches the result based on all input arguments.
    """
    # 1. Switch the global path state based on the profile
    _set_profile_paths(profile_name) 

    # 2. Initialize the DSD using the newly set global path
    dsd = DataStructureDefinition(
        get_dsd_path()[0],
        dimensions=dimensions,
        use_local_definitions=False
        #name=name,
        #repo=repo,
        #revision=revision,
    )
    return dsd

# Helper function for loading the RegionProcessor
def _load_region_processor() -> RegionProcessor:
    """Helper function to instantiate the RegionProcessor."""
    return RegionProcessor()


def get_region_processor(force_reload: bool = False) -> RegionProcessor:
    """
    Returns the RegionProcessor object, implementing caching and allowing force reloading.
    """
    global _region_processor
    
    if _region_processor is None or force_reload:
        _region_processor = _load_region_processor()
        
    return _region_processor