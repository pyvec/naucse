from pathlib import Path

from werkzeug.security import safe_join

import naucse_render

class LocalRenderer:
    """Renders a local course using the `naucse_render` module."""
    def __init__(self, *, path, slug, repo_info):
        self.path = Path(path).resolve()
        self.version = 1
        self.slug = slug
        self.repo_info = repo_info

    def get_course(self):
        """Return information about a course"""
        return naucse_render.get_course(
            self.slug,
            version=self.version,
            path=self.path,
        )

    def get_lessons(self, lesson_slugs, *, vars):
        """Return information about the given lessons"""
        return naucse_render.get_lessons(lesson_slugs, vars=vars, path=self.path)

    def get_path_or_file(self, path):
        """Return a path/file for a static file (e.g. an image).

        Renderers can either return a filename, or an opened file-like object.
        (A filename will likely be better for performance.)
        """
        return safe_join(self.path, path)

    def get_repo_info(self):
        return self.repo_info
