# nomenclature-adapter

`nomenclature-adapter` is a Python package that loads validationnomenclature profiles for Integrated Assessment Model (IAM) result checking.
It builds on [`nomenclature-iamc`](https://github.com/IAMconsortium/nomenclature)
and adds a project-profile layer so one validation UI can switch between
different sets of models, regions, variables, scenarios, and region mappings.

The package is primarily used by
[`i2amparis/validation-ui`](https://github.com/i2amparis/validation-ui), but it
can also be imported directly by scripts or notebooks that need the same
validation definitions.

This package started as [CICERO&#39;s `iamcompact-nomenclature`](https://github.com/ciceroOslo/iamcompact-nomenclature),
built specifically for the HORIZON EUROPE project IAM COMPACT, and has since
been generalized into a project-agnostic profile loader usable by any project
(IAM COMPACT and TRANSIENCE are both bundled profiles today, see `profiles/`).

## What This Repository Contains

- `nomenclature_adapter/`: the Python package used to load profiles, build
  `nomenclature.DataStructureDefinition` objects, create region processors, and
  run helper validation checks.
- `profiles/`: YAML profile manifests. Each profile points to one or more
  external definition repositories and selects the definition and mapping files
  used for validation.
- `scripts/`: maintenance utilities for working with definition files.

The repository does not vendor the full model, region, variable, or scenario
definitions. Those live in separate definition repositories and are cloned on
demand when a profile is loaded.

## Profiles

Each file in `profiles/` is a validation profile. The filename, without the
`.yaml` extension, is the profile name exposed to consuming applications.

Current bundled profiles include:

- `iamcompact`: IAM COMPACT validation profile.
- `transience`: TRANSIENCE validation profile.

A profile manifest defines:

- external Git repositories containing nomenclature definitions;
- the Git branch, tag, or ref to use for each repository;
- the definition files for each IAMC dimension;
- the mapping file used by the region processor.

Example structure:

```yaml
repositories:
  project-definitions:
    url: https://github.com/example/project-definitions.git
    release: main
dimensions:
  - variable
  - region
  - model
  - scenario
definitions:
  variable:
    repository: project-definitions
    file: definitions/variable/common.yaml
mappings:
  repository: project-definitions
  file: mappings/GCAM_7.1.yaml
```

## Installation

Install directly from GitHub with `pip`:

```bash
pip install git+https://github.com/i2amparis/nomenclature-adapter.git
```

Install a specific branch or tag:

```bash
pip install git+https://github.com/i2amparis/nomenclature-adapter.git@main
```

With `uv`, add the package to another project as a Git dependency:

```bash
uv add "nomenclature-adapter @ git+https://github.com/i2amparis/nomenclature-adapter.git@main"
```

## Usage

List the available profiles:

```python
import nomenclature_adapter as adapter

profiles = adapter.get_validation_profiles()
print(profiles)
```

Load a profile and get the objects used by `nomenclature-iamc`:

```python
import nomenclature_adapter as adapter

dsd = adapter.get_dsd(profile_name="transience")
processor = adapter.get_region_processor(profile_name="transience")
```

Run aggregate checks using the helper functions:

```python
import nomenclature_adapter as adapter

variable_errors = adapter.check_var_aggregates(data, profile_name="iamcompact")
region_errors = adapter.check_region_aggregates(data, profile_name="iamcompact")
```

When a profile is loaded, its external definition repositories are cloned into
a local cache and updated on subsequent loads. The default cache location is
platform-specific, for example:

- macOS: `~/Library/Caches/nomenclature-adapter`
- Linux: `~/.cache/nomenclature-adapter`
- Windows: `%LOCALAPPDATA%\nomenclature-adapter` or
  `%APPDATA%\nomenclature-adapter`

Set `NOMENCLATURE_PROFILE_CACHE` to use a different cache directory:

```bash
export NOMENCLATURE_PROFILE_CACHE=/path/to/profile-cache
```

## Adding A Profile

To add a new validation profile:

1. Create a new YAML file in `profiles/`, for example `my-project.yaml`.
2. Add the external definition repositories under `repositories`.
3. Select the definition files for `variable`, `region`, `model`, and
   `scenario`.
4. Select the mapping file under `mappings`.
5. Use the new profile name from Python or from the validation UI.

The profile name is the filename stem, so `profiles/my-project.yaml` becomes
`my-project`.

## Development

Install the package in editable mode from this repository:

```bash
uv sync
```

Run tests, if present, with:

```bash
uv run pytest
```

The package requires Python 3.13 or newer.
