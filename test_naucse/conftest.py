from pathlib import Path
import shutil
import subprocess

import pytest
import yaml
import os

from naucse import models
from naucse.edit_info import get_local_repo_info
from naucse.local_renderer import LocalRenderer


API_VERSIONS = ((0, 0), (0, 1), (0, 2), (0, 3), (0, 4))

def api_versions_since(minimum):
    return tuple(version for version in API_VERSIONS if version >= minimum)


fixture_path = Path(__file__).parent / 'fixtures'


def dummy_schema_url_factory(cls, **kwargs):
    return f'http://dummy.test/schema/{cls.__name__}'


class DummyURLFactories:
    def __init__(self, url_type):
        self.url_type = url_type

    def __getitem__(self, cls):
        def dummy_url_factory(_external=True, **kwargs):
            args = '&'.join(f'{k}={v}' for k, v in sorted(kwargs.items()))
            base = 'http://dummy.test/model'
            return f'{base}/{self.url_type}/{cls.__name__}/?{args}'
        return dummy_url_factory


class DummyRenderer:
    """Renderer that returns courses/lessons from the given data

    Mocks the get_lessons method of a renderer.

    As `course`, DummyRenderer expects a full API response, complete with
    api_version.
    The `lessons` argument should be a mapping of lesson slugs to full API
    responses.

    As of now, get_lessons only allows a single lesson slug.
    """

    def __init__(self, slug, course=None, lessons=None):
        self.slug = slug
        self.course = course
        self._lessons = lessons or {}

    def get_course(self):
        return self.course

    def get_lessons(self, lessons, *, vars):
        [slug] = lessons
        try:
            return self._lessons[slug]
        except KeyError as e:
            raise DummyLessonNotFound(slug) from e

    def get_repo_info(self):
        return get_local_repo_info('/dummy')

class DummyLessonNotFound(LookupError):
    """Raised by DummyRenderer when a lesson is not found"""


def make_model(**extra_kwargs):
    """Return a set-up testing model, possibly with additional init kwargs"""
    model = models.Root(
        schema_url_factory=dummy_schema_url_factory,
        url_factories={
            'api': DummyURLFactories('api'),
            'web': DummyURLFactories('web'),
        },
        **extra_kwargs,
    )
    model.load_licenses(fixture_path / 'licenses')
    return model


@pytest.fixture
def model():
    """Model for testing courses"""
    return make_model()


def assert_yaml_dump(data, filename):
    """Assert that JSON-compatible "data" matches a given YAML dump

    With TEST_NAUCSE_DUMP_YAML=1, will dump the data to the expected location.
    """

    # I find that textually comparing structured dumped to YAML is easier
    # than a "deep diff" algorithm (like the one in pytest).
    # Another advantage is that output changes can be verified with
    # `git diff`, and reviewed along with code changes.
    # The downside is that we need to dump *everything*, so if a new item
    # is added to the output, all expected data needs to be changed.
    # TEST_NAUCSE_DUMP_YAML=1 makes dealing with that easier.

    yaml_path = fixture_path / 'expected-dumps' / filename
    try:
        expected_yaml = yaml_path.read_text()
    except FileNotFoundError:
        expected_yaml = ''
        expected = None
    else:
        expected = yaml.safe_load(expected_yaml)
    if data != expected or expected is None:
        data_dump = yaml.safe_dump(data, default_flow_style=False, indent=4)
        if os.environ.get('TEST_NAUCSE_DUMP_YAML') == '1':
            yaml_path.write_text(data_dump)
        else:
            print(
                'Note: Run with TEST_NAUCSE_DUMP_YAML=1 to dump the '
                'expected YAML'
            )
            assert data_dump == expected_yaml
            assert data == expected


@pytest.fixture(params=API_VERSIONS)
def assert_model_dump(request):
    version = request.param
    def _assert(model, filename):
        filename += '.v{}.{}.yaml'.format(*version)
        assert_yaml_dump(models.dump(model, version=version), filename)
    return _assert


def add_test_course(model, slug, data, version=(0, 0)):
    renderer = DummyRenderer(
        course={
            'api_version': list(version),
            'course': data,
        },
        slug=slug,
    )
    model.add_course(models.Course.from_renderer(
        renderer=renderer,
        parent=model,
    ))


def setup_repo(content_source_path, repo_path, branch='main'):
    shutil.copytree(content_source_path, repo_path)
    subprocess.run(['git', 'init', '-b', branch], cwd=repo_path, check=True)
    subprocess.run(['git', 'add', '.'], cwd=repo_path, check=True)
    subprocess.run(['git', 'config', 'user.name', 'Test'], cwd=repo_path, check=True)
    subprocess.run(['git', 'config', 'user.email', 'test@test'], cwd=repo_path, check=True)
    subprocess.run(['git', 'commit', '-m', 'course'], cwd=repo_path, check=True)
