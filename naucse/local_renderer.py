from pathlib import Path

from werkzeug.security import safe_join

import naucse_render

class LocalRenderer:
    def __init__(self, *, path, slug):
        self.path = Path(path).resolve()
        self.version = 1
        self.slug = slug

    def get_course(self):
        return naucse_render.get_course(
            self.slug,
            version=self.version,
            path=self.path,
        )

    def get_lessons(self, lesson_slugs, *, vars):
        return naucse_render.get_lessons(lesson_slugs, vars=vars, path=self.path)

    def get_path_or_file(self, path):
        return safe_join(self.path, path)
