from pathlib import Path
import contextlib
import shutil
import re
from fnmatch import fnmatch

from arca import Task
from werkzeug.security import safe_join

from naucse.exceptions import UntrustedRepo


NAUCSE_URL_RE = re.compile(
    r'^https://github.com/[^/]+/naucse\.python\.cz(\.git)?$'
)


class RemoteRepoError(Exception):
    """Raised when an Arca call fails and provides info about remote repo"""


class Renderer:
    """Render courses from a remote repository using Arca

    Renderer objects have the same API as the `naucse_render` module.

    This renderer additionally populates the course 'etag', if the
    remote task doesn't return it.
    """
    def __init__(self, arca, url, branch, *, trusted_repo_patterns):
        self.arca = arca
        self.url = url
        self.branch = branch

        checked_url = f'{url}#{branch}'
        if not any(fnmatch(checked_url, l) for l in trusted_repo_patterns):
            raise UntrustedRepo(checked_url)

        readme_path = arca.static_filename(url, branch, 'README.md')
        self.worktree_path = Path(readme_path).parent

    @contextlib.contextmanager
    def wrap_errors(self, method, arg):
        """In case of error, provide extra information about method and repo
        """
        try:
            yield
        except Exception as e:
            raise RemoteRepoError(
                f'Error in {method}({arg!r}), '
                + f'repo {self.url!r}, branch {self.branch!r}'
            ) from e

    def get_course(self, slug, *, version):
        task = Task(
            entry_point="naucse_render:get_course",
            args=[slug],
            kwargs={'version': version, 'path': '.'},
        )
        with self.wrap_errors('get_course', slug):
            info = self.arca.run(self.url, self.branch, task).output
            repo = self.arca.get_repo(self.url, self.branch)
            etag = self.arca.current_git_hash(self.url, self.branch, repo)

        if 'course' in info:
            info['course'].setdefault('etag', etag)

        return info

    def get_lessons(self, lesson_slugs, *, vars):
        # Default timeout is 5s; multiply this by the no. of requested lessons
        timeout = 5 * len(lesson_slugs)
        task = Task(
            entry_point="naucse_render:get_lessons",
            args=[sorted(lesson_slugs)],
            kwargs={'vars': vars, 'path': '.'},
            timeout=timeout,
        )
        with self.wrap_errors('get_lessons', lesson_slugs):
            info = self.arca.run(self.url, self.branch, task).output

        return info


    def get_path_or_file(self, path):
        return safe_join(self.worktree_path, path)
