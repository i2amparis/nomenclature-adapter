"""Tests for `_checkout_repository`'s tolerance of transient fetch failures.

A production incident showed that a `git fetch` failing (auth/network/rate
limit hiccup against the real GitHub remote) on a repository that had
*already* been cloned successfully earlier in the process's lifetime took
down the whole page with an uncaught `GitCommandError`, even though the
existing, previously-working local clone was still perfectly usable. These
tests lock in the fix: such a failure is now logged and swallowed, falling
back to the existing clone, exactly like the (pre-existing) tolerance
already applied to the `git pull` call for a pinned ref.
"""
import shutil
import tempfile
from pathlib import Path

import git
import pytest

from nomenclature_adapter.default_definitions import _checkout_repository


@pytest.fixture
def tmp_dirs():
    tmp = Path(tempfile.mkdtemp())
    try:
        yield tmp
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
###END fixture tmp_dirs


def _make_upstream(tmp: Path) -> Path:
    upstream = tmp / 'upstream'
    upstream.mkdir()
    repo = git.Repo.init(upstream, initial_branch='main')
    (upstream / 'file.txt').write_text('v1')
    repo.index.add(['file.txt'])
    repo.index.commit('initial commit')
    return upstream
###END def _make_upstream


class TestCheckoutRepositoryFetchTolerance:

    def test_initial_clone_succeeds(self, tmp_dirs):
        upstream = _make_upstream(tmp_dirs)
        profile_root = tmp_dirs / 'profile_root'
        profile_root.mkdir()
        _checkout_repository(
            profile_root, 'myrepo', {'url': str(upstream), 'release': 'main'},
        )
        assert (profile_root / 'myrepo' / 'file.txt').read_text() == 'v1'
    ###END def test_initial_clone_succeeds

    def test_failed_fetch_on_existing_clone_does_not_raise(self, tmp_dirs):
        upstream = _make_upstream(tmp_dirs)
        profile_root = tmp_dirs / 'profile_root'
        profile_root.mkdir()
        repo_config = {'url': str(upstream), 'release': 'main'}
        _checkout_repository(profile_root, 'myrepo', repo_config)
        repo_path = profile_root / 'myrepo'

        # Simulate the remote becoming unreachable (auth failure, network
        # blip, rate limit, or -- as in the production incident -- a
        # malformed response from something on the network path) after a
        # successful initial clone.
        existing_repo = git.Repo(repo_path)
        existing_repo.remotes.origin.set_url(
            'https://github.com/this-org-does-not-exist-xyz/'
            'this-repo-does-not-exist-xyz.git'
        )

        # Must not raise: falls back to the existing, already-cloned data.
        _checkout_repository(profile_root, 'myrepo', repo_config)
        assert (repo_path / 'file.txt').read_text() == 'v1'
    ###END def test_failed_fetch_on_existing_clone_does_not_raise

    def test_successful_fetch_still_picks_up_new_commits(self, tmp_dirs):
        """Sanity check that the tolerance doesn't mask a real, reachable
        update -- i.e. this isn't just always skipping the fetch."""
        upstream = _make_upstream(tmp_dirs)
        profile_root = tmp_dirs / 'profile_root'
        profile_root.mkdir()
        repo_config = {'url': str(upstream), 'release': 'main'}
        _checkout_repository(profile_root, 'myrepo', repo_config)

        up_repo = git.Repo(upstream)
        (upstream / 'file.txt').write_text('v2')
        up_repo.index.add(['file.txt'])
        up_repo.index.commit('second commit')

        _checkout_repository(profile_root, 'myrepo', repo_config)
        assert (profile_root / 'myrepo' / 'file.txt').read_text() == 'v2'
    ###END def test_successful_fetch_still_picks_up_new_commits

###END class TestCheckoutRepositoryFetchTolerance
