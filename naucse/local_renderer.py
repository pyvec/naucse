from pathlib import Path

from werkzeug.security import safe_join

import naucse_render

class LocalRenderer:
    def __init__(self, path):
        self.path = Path(path).resolve()
        self.version = 1

    def get_course(self, slug):
        return naucse_render.get_course(slug, version=self.version, path=self.path)

    def get_lessons(self, lesson_slugs, *, vars):
        return naucse_render.get_lessons(lesson_slugs, vars=vars, path=self.path)

    def get_path_or_file(self, path):
        return safe_join(self.path, path)
