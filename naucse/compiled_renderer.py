from pathlib import Path, PurePosixPath
import subprocess
import functools
import sys
import re
import datetime
import threading
from io import BytesIO
import json

from gitpathlib import GitPath

from .edit_info import get_repo_info

CACHE_INTERVAL = datetime.timedelta(minutes=10)
main_lock = threading.Lock()


class CompiledRenderer:
    def __init__(self, slug, info, fetcher):
        self.slug = slug
        self.fetcher = fetcher
        self.url = info['url']
        self.branch = info['branch']
        self.path = PurePosixPath(info.get('path', '.'))
        self.ref = self.fetcher.get_ref(self.url, self.branch)
        fetcher.register_branch(self.url, self.branch)
        self.gitpath = None

    def get_path(self, path):
        if self.gitpath is None:
            self.gitpath = self.fetcher.fetch(self.url, self.branch) / self.path
        return self.gitpath / path

    @functools.lru_cache
    def get_course(self):
        with self.get_path('course.json').open() as f:
            return json.load(f)

    def get_lessons(self, slugs, *, vars=None):
        info = self.get_course()
        course = info['course']
        return {
            'api_version': info['api_version'],
            'data': course['lessons'],
        }

    @functools.lru_cache
    def get_repo_info(self):
        try:
            edit_info = self.get_course()['course']['edit_info']
        except KeyError:
            raise ValueError('edit info should be included in the course')
        return get_repo_info(edit_info['url'], edit_info['branch'])

    def get_path_or_file(self, path):
        return self.get_path(path).open('rb')


def run(*args, check=True, encoding='utf-8', **kwargs):
    print('$', *(_quote(word) for word in args), file=sys.stderr)
    return subprocess.run(args, check=check, encoding=encoding, **kwargs)

def _quote(word):
    word = str(word)
    if re.match('^[-_a-zA-Z0-9.:]+$', word):
        return word
    word = word.replace("'", r"'\''")
    return f"'{word}'"

class Fetcher:
    """Manages a Git repository to which content is pulled.

    When multiple branches from a singe remote repository are used,
    it's good to fetch them all at once.
    To do this:
    - first register all branches to fetch using `register_branch`,
    - then fetch branches as needed using `fetch`.

    Each fetched branch is available under a ref given by `get_ref`.
    """
    git_cmd = 'git'

    def __init__(self, repo_path='.cache/naucse/repo'):
        self.repo_path = Path(repo_path).resolve()
        if not self.repo_path.exists():
            self.repo_path.mkdir(parents=True)
            self.run_git('init', '--bare', '-b', 'main', '.')
        else:
            if not (self.repo_path / 'HEAD').exists():
                raise ValueError(
                    f"Cache directory `{self.repo_path}` is not a bare "
                    "Git repo. Remove it to continue."
                )
        self.registered_branches = {}
        self.fetched_branches = {}

    def run_git(self, *args, **kwargs):
        """Run a `git` sub command in the repo, ignoring the user's settings.
        """
        env = {
            'GIT_DIR': self.repo_path,
            'GIT_CONFIG_NOSYSTEM': '1',
            'GIT_TERMINAL_PROMPT': '0',
            'HOME': self.repo_path,
            **kwargs.pop('env', {})
        }
        kwargs['env'] = env
        kwargs.setdefault('cwd', self.repo_path)
        return run(self.git_cmd, *args, **kwargs)

    def register_branch(self, url, branch):
        """Advertise that `branch` should be fetched from remoe given by `url`
        """
        self.registered_branches.setdefault(url, set()).add(branch)

    def get_ref(self, url, branch):
        """Get the ref corresponding to the given repo `url` and `branch`
        """
        return f'refs/remotes/{git_identifer(url)}/{branch}'

    def fetch(self, url, branch, depth=5):
        """Fetch the given branch from the given URL

        Returns a GitPath to the newly fetched branch.
        """
        with main_lock:
            self.register_branch(url, branch)
            to_fetch = self.registered_branches.pop(url)
            now = datetime.datetime.now()
            to_fetch = self.filter_branches_to_fetch(url, to_fetch, now=now)
            if branch not in to_fetch:
                self.fetched_branches.setdefault(url, set()).add(branch)
                return GitPath(self.repo_path, self.get_ref(url, branch))
            branches = sorted(to_fetch)
            ident = git_identifer(url)
            self.run_git(
                'remote', 'add', '--', ident, url,
                check=False, stderr=subprocess.DEVNULL,
            )
            self.run_git(
                'fetch', '--depth', str(depth), '--', ident,
                *(f'+{branch}:{self.get_ref(url, branch)}' for branch in branches)
            )
            self.fetched_branches.setdefault(url, set()).update(to_fetch)
            self.update_fetched_branches(url, to_fetch, now=now)
        return GitPath(self.repo_path, self.get_ref(url, branch))

    def get_last_fetch_config_variable(self, url, branch):
        return f'naucse.last_fetch.{git_identifer(url)}.{branch}'

    def filter_branches_to_fetch(self, url, branches, *, now):
        result = []
        branches = set(branches) - self.fetched_branches.get(url, set())
        for branch in branches:
            var = self.get_last_fetch_config_variable(url, branch)
            proc = self.run_git(
                'config', '--', var,
                check=False,
                stdout=subprocess.PIPE
            )
            last_fetch_str = proc.stdout.strip()
            if not last_fetch_str:
                result.append(branch)
            else:
                last_fetch = datetime.datetime.fromisoformat(last_fetch_str)
                if last_fetch + CACHE_INTERVAL < now:
                    result.append(branch)
                else:
                    print(
                        f'{url}: {branch} aready fetched',
                        file=sys.stderr
                    )
        return result

    def update_fetched_branches(self, url, branches, *, now):
        for branch in branches:
            var = self.get_last_fetch_config_variable(url, branch)
            proc = self.run_git('config', var, now.isoformat())


def git_identifer(string):
    """Convert "string" to a Git config variable name.

    According to `man git config`: variable names are case-insensitive,
    allow only alphanumeric characters and -, and must start with an alphabetic
    character.
    """
    def replacement(match):
        char = match[0]
        if result := {
            ':': '-m', '.': '-p', '/': '-s', '-': '-d', '_': '-r',
        }.get(char):
            return result
        num = ord(char)
        if num < 2**8:
            return '-c{num:02x}'
        if num < 2**16:
            return '-u{num:04x}'
        if num < 2**32:
            return '-v{num:016x}'
        raise ValueError('char to big')
    result = re.sub('[^a-z0-9]', replacement, string)
    if re.match('^[a-z]', result):
        return result
    else:
        return 'x' + result
