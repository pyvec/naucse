from pathlib import Path
import subprocess
import shutil

import pytest
import yaml
from jsonschema.exceptions import ValidationError

from naucse import models
from naucse.edit_info import get_local_repo_info
from naucse.converters import DuplicateKeyError
from naucse.local_renderer import LocalRenderer
from naucse import compiled_renderer

from test_naucse.conftest import add_test_course, fixture_path
from test_naucse.conftest import DummyRenderer, DummyLessonNotFound
from test_naucse.conftest import api_versions_since


@pytest.fixture
def empty_course(model):
    add_test_course(model, 'courses/minimal', {
        'title': 'A minimal course',
        'sessions': [],
    })
    return model.courses['courses/minimal']


def check_empty_course_attrs(empty_course, *, source_file=None):
    assert empty_course.slug == 'courses/minimal'
    assert empty_course.parent == empty_course.root
    assert empty_course.title == 'A minimal course'
    assert empty_course.subtitle == None
    assert empty_course.description == None
    assert empty_course.long_description == ''
    assert empty_course.vars == {}
    assert empty_course.place == None
    assert empty_course.time_description == None
    assert empty_course.default_time == None
    assert empty_course.sessions == {}
    assert empty_course.source_file == source_file
    assert empty_course.start_date == None
    assert empty_course.end_date == None
    assert empty_course.derives == None
    assert empty_course.base_course == None
    assert empty_course.get_recent_derived_runs() == []


def test_empty_course_attrs(model, empty_course):
    assert empty_course.root == model
    check_empty_course_attrs(empty_course)


def test_get_lesson_url(empty_course):
    """Generating lessons URLs doesn't need the lesson to be available"""
    assert empty_course.get_lesson_url('any/lesson') == (
        'http://dummy.test/model/web/Page/'
        + '?course_slug=courses/minimal'
        + '&lesson_slug=any/lesson'
        + '&page_slug=index'
    )


def test_freeze_empty_course(empty_course):
    empty_course.freeze()
    check_empty_course_attrs(empty_course)


def test_get_lesson_url_freeze_error(empty_course):
    """Requested lessons are loaded on freeze(), failing if not available"""
    empty_course.get_lesson_url('any/lesson')
    empty_course.renderer = DummyRenderer(slug='dummy')
    with pytest.raises(DummyLessonNotFound):
        empty_course.freeze()


def test_empty_course_from_renderer(model, assert_model_dump):
    """Valid trvial json that could come from a fork is loaded correctly"""
    source = 'courses/minimal/info.yml'
    renderer = DummyRenderer(
        slug='courses/minimal',
        course={
            'api_version': [0, 0],
            'course': {
                'title': 'A minimal course',
                'sessions': [],
                'source_file': source,
            }
        }
    )
    course = models.Course.from_renderer(
        parent=model,
        renderer=renderer,
    )
    check_empty_course_attrs(course, source_file=Path(source))
    assert_model_dump(course, 'minimal-course')


def load_course_from_fixture(model, filename):
    """Load course from a file with info as it would come from a fork.

    Contents of the file are passed as kwargs to DummyRenderer.
    """

    with (fixture_path / filename).open() as f:
        renderer = DummyRenderer(
            slug='courses/complex',
            **yaml.safe_load(f),
        )
    course = models.Course.from_renderer(
        parent=model,
        renderer=renderer,
    )
    model.add_course(course)
    return course


def test_complex_course(model, assert_model_dump):
    """Valid complex json that could come from a fork is loaded correctly"""
    course = load_course_from_fixture(model, 'course-data/complex-course.yml')

    assert_model_dump(course, 'complex-course')

    # Make sure HTML is sanitized
    assert course.long_description == 'A <em>fun course!</em>'
    assert course.sessions['full'].description == 'A <em>full session!</em>'


@pytest.mark.parametrize('version', api_versions_since((0, 1)))
def test_api_version(model, assert_model_dump, version):
    """Valid json with API changes from the given version is loaded correctly"""
    version = '{}.{}'.format(*version)
    name = f'course-v{version}'
    course = load_course_from_fixture(model, f'course-data/{name}.yml')

    assert_model_dump(course, name)


def test_derives(model):
    """Test that derives and base_course is set correctly"""
    add_test_course(model, 'courses/base', {
        'title': 'A base course',
        'sessions': [],
    })
    add_test_course(model, 'courses/derived', {
        'title': 'A derived course',
        'sessions': [],
        'derives': 'base'
    })

    base = model.courses['courses/base']
    derived = model.courses['courses/derived']

    assert derived.derives == 'base'
    assert derived.base_course is base


def test_nonexisting_derives(model):
    """Test that nonexisting derives fails quietly"""
    add_test_course(model, 'courses/bad-derives', {
        'title': 'A course derived from nothing',
        'sessions': [],
        'derives': 'nonexisting'
    })

    course = model.courses['courses/bad-derives']

    assert course.derives == 'nonexisting'
    assert course.base_course is None


def test_invalid_course(model):
    """Invalid complex json that could come from a fork is not loaded"""
    with pytest.raises(ValidationError):
        load_course_from_fixture(model, 'course-data/invalid-course.yml')


def test_invalid_duplicate_session(model):
    """Json with duplicate sessions that could come from a fork is not loaded"""
    with pytest.raises(DuplicateKeyError):
        load_course_from_fixture(model, 'course-data/invalid-duplicate-session.yml')


def setup_compiled_renderer(model, tmp_path, fixture_name, branch='main'):
    repo_path = tmp_path / 'repo'
    shutil.copytree(fixture_path / fixture_name, repo_path)
    subprocess.run(['git', 'init', '-b', branch], cwd=repo_path, check=True)
    subprocess.run(['git', 'add', '.'], cwd=repo_path, check=True)
    subprocess.run(['git', 'config', 'user.name', 'Test'], cwd=repo_path, check=True)
    subprocess.run(['git', 'config', 'user.email', 'test@test'], cwd=repo_path, check=True)
    subprocess.run(['git', 'commit', '-m', 'course'], cwd=repo_path, check=True)

    fetcher = compiled_renderer.Fetcher(repo_path=tmp_path / 'fetch_repo')
    renderer = compiled_renderer.CompiledRenderer(
        slug='test',
        info={'url': str(repo_path), 'branch': branch},
        fetcher=fetcher,
    )
    return renderer


def test_load_compiled_course(model, tmp_path):
    """Test that a compiled course can be loaded"""
    renderer = setup_compiled_renderer(model, tmp_path, 'compiled-course')
    course = models.Course.from_renderer(parent=model, renderer=renderer)
    assert str(course.lessons['lesson1'].pages['index'].content) == 'Content 1'
    assert str(course.lessons['lesson2'].pages['index'].content) == 'Content 2\n'


def test_load_compiled_course_from_branch_with_slash(model, tmp_path):
    """Test that a compiled course can be loaded"""
    renderer = setup_compiled_renderer(model, tmp_path, 'compiled-course',
                                       branch='compiled/test')
    course = models.Course.from_renderer(parent=model, renderer=renderer)
    assert str(course.lessons['lesson1'].pages['index'].content) == 'Content 1'
    assert str(course.lessons['lesson2'].pages['index'].content) == 'Content 2\n'


def test_load_compiled_course_missing_page(model, tmp_path):
    """Test that accessing missing lesson contents fails"""
    renderer = setup_compiled_renderer(model, tmp_path, 'compiled-missing-page')
    course = models.Course.from_renderer(parent=model, renderer=renderer)
    with pytest.raises(FileNotFoundError):
        print(course.lessons['lesson1'].pages['index'].content)


def test_load_compiled_course_missing_page_freeze(model, tmp_path):
    """Test that freeze() fails fast when lesson contents are missing"""
    renderer = setup_compiled_renderer(model, tmp_path, 'compiled-missing-page')
    course = models.Course.from_renderer(parent=model, renderer=renderer)
    with pytest.raises(FileNotFoundError):
        course.freeze()


def test_load_compiled_course_missing_static(model, tmp_path):
    """Test that accessing a missing static file fails"""
    renderer = setup_compiled_renderer(model, tmp_path, 'compiled-missing-static')
    course = models.Course.from_renderer(parent=model, renderer=renderer)
    with pytest.raises(FileNotFoundError):
        static_file = course.lessons['lesson1'].static_files['helpful-diagram.png']
        print(static_file.get_path_or_file())


def test_load_compiled_course_missing_static_freeze(model, tmp_path):
    """Test that freeze() fails fast when a static file is missing"""
    renderer = setup_compiled_renderer(model, tmp_path, 'compiled-missing-static')
    course = models.Course.from_renderer(parent=model, renderer=renderer)
    with pytest.raises(FileNotFoundError):
        course.freeze()
