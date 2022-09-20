from pathlib import Path
import shutil
import os

import pytest
import yaml

from naucse import models
from naucse.edit_info import get_local_repo_info
from naucse.local_renderer import LocalRenderer

from test_naucse.conftest import fixture_path, dummy_schema_url_factory
from test_naucse.conftest import add_test_course, setup_repo


def test_empty_model():
    model = models.Root()
    assert not model.courses
    assert not model.licenses
    assert not model.run_years
    assert model.get_pks() == {}

    with pytest.raises(models.NoURL):
        model.get_url()


def test_licenses():
    model = models.Root()
    model.load_licenses(fixture_path / 'licenses')

    assert sorted(model.licenses) == ['cc-by-sa-40', 'cc0']
    assert model.licenses['cc0'].slug == 'cc0'
    assert model.licenses['cc0'].url.endswith('/publicdomain/zero/1.0/')
    assert model.licenses['cc0'].title.endswith('Public Domain Dedication')

    assert model.licenses['cc-by-sa-40'].slug == 'cc-by-sa-40'
    assert model.licenses['cc-by-sa-40'].url.endswith('/licenses/by-sa/4.0/')
    assert model.licenses['cc-by-sa-40'].title.endswith('4.0 International')


def test_dump_empty_model(assert_model_dump):
    model = models.Root(schema_url_factory=dummy_schema_url_factory)
    assert_model_dump(model, 'empty-root')


def test_load_empty_dir():
    model = models.Root()

    # Collections are available but empty
    assert not model.courses
    assert not model.run_years
    assert not model.licenses


def test_no_courses():
    """Loading directory with no courses succeeds, but gives no course
    """
    model = models.Root()
    model.load_local_courses(fixture_path / 'empty-lessons-dir')

    assert sorted(model.courses) == []


def test_load_courses():
    model = models.Root()
    model.load_local_courses(fixture_path / 'minimal-courses')

    assert sorted(model.courses) == [
        '2019/minimal', '2019/minimal-flat',
        'courses/minimal', 'courses/minimal-flat',
    ]

    assert model.courses['courses/minimal'].title == 'A minimal course'
    assert model.courses['courses/minimal'].slug == 'courses/minimal'
    assert model.courses['2019/minimal'].title == 'A minimal course'
    assert model.courses['2019/minimal'].slug == '2019/minimal'


def test_from_renderer():
    model = models.Root()
    path = fixture_path / 'minimal-courses'
    renderer = LocalRenderer(
        path=path,
        repo_info=get_local_repo_info(path),
        slug='courses/minimal',
    )
    model.add_course(models.Course.from_renderer(
        parent=model,
        renderer=renderer,
    ))

    assert sorted(model.courses) == ['courses/minimal']

    assert model.courses['courses/minimal'].title == 'A minimal course'
    assert model.courses['courses/minimal'].slug == 'courses/minimal'


def test_lessons_slug():
    """Test that an arbitrary course can have the slug 'lessons',
    which used to be special
    """
    model = models.Root()
    path = fixture_path / 'minimal-courses'
    renderer = LocalRenderer(
        path=path,
        repo_info=get_local_repo_info(path),
        slug='lessons',
        api_slug='courses/minimal',
    )
    model.add_course(models.Course.from_renderer(
        parent=model,
        renderer=renderer,
    ))

    assert sorted(model.courses) == ['lessons']

    assert model.courses['lessons'].slug == 'lessons'
    assert model.courses['lessons'].title == 'A minimal course'


def test_dump_local_course(model, assert_model_dump):
    version=(0, 0)
    path = fixture_path / 'minimal-courses'
    renderer=LocalRenderer(
        repo_info=get_local_repo_info(path),
        path=path,
        slug='courses/minimal',
    )
    model.add_course(models.Course.from_renderer(
        parent=model,
        renderer=renderer,
    ))

    assert_model_dump(model, 'minimal-root')
    course = model.courses['courses/minimal']
    assert_model_dump(course, 'minimal-course')


def test_add_course_from_data():
    model = models.Root()

    add_test_course(model, 'courses/minimal', {
        'title': 'A minimal course',
        'sessions': [],
    })

    assert sorted(model.courses) == ['courses/minimal']

    assert model.courses['courses/minimal'].title == 'A minimal course'
    assert model.courses['courses/minimal'].slug == 'courses/minimal'


def test_run_years(model, assert_model_dump):
    assert model.run_years == {}

    # Add a self-study course. It should not appear in run_years.

    add_test_course(model, 'courses/minimal', {
        'title': 'A minimal course',
        'sessions': [],
    })

    assert model.run_years == {}
    assert sorted(model.courses) == ['courses/minimal']
    assert sorted(model.self_study_courses) == ['courses/minimal']
    course_minimal = model.courses['courses/minimal']
    assert course_minimal.start_date == None
    assert course_minimal.end_date == None

    # Add a course with a single session. It should appear in its run_year.

    add_test_course(model, '2019/single-session', {
        'title': 'A course with a single session',
        'sessions': [
            {
                'title': 'One session',
                'slug': 'foo',
                'date': '2019-01-05',
                'materials': [],
            },
        ],
    })

    assert sorted(model.courses) == ['2019/single-session', 'courses/minimal']
    assert sorted(model.self_study_courses) == ['courses/minimal']
    course_2019 = model.courses['2019/single-session']
    assert course_2019.start_date.year == 2019
    assert course_2019.end_date.year == 2019
    assert sorted(model.run_years) == [2019]
    assert model.run_years[2019] == {'2019/single-session': course_2019}

    # Add a course spanning 3 years. Should appear in all run_years it spans.
    # (Even if there are no sessions that year.)

    add_test_course(model, '2017/multi-year', {
        'title': 'A course with sessions in years 2017 and 2019',
        'sessions': [
            {
                'title': 'First session, 2017',
                'slug': 'one',
                'date': '2017-01-05',
                'materials': [],
            },
            {
                'title': 'Last session, 2019',
                'slug': 'two',
                'date': '2019-01-05',
                'materials': [],
            },
        ],
    })

    assert sorted(model.courses) == [
        '2017/multi-year', '2019/single-session', 'courses/minimal',
    ]
    assert sorted(model.self_study_courses) == ['courses/minimal']
    course_2017 = model.courses['2017/multi-year']
    assert course_2017.start_date.year == 2017
    assert course_2017.end_date.year == 2019
    assert sorted(model.run_years) == [2017, 2018, 2019]
    for year in 2017, 2018:
        assert model.run_years[year] == {'2017/multi-year': course_2017}
    assert model.run_years[2019] == {
        '2017/multi-year': course_2017,
        '2019/single-session': course_2019,
    }

    assert_model_dump(model, 'run-years/root')
    for year, run_year in model.run_years.items():
        assert_model_dump(run_year, f'run-years/{year}')


def test_load_courses_yml(model, tmp_path):
    """Test loading compiled courses from courses.yml"""
    fixture_name = 'compiled-course'
    setup_repo(fixture_path / fixture_name, tmp_path / 'repos' / 'basic')
    setup_repo(
        fixture_path / fixture_name,
        tmp_path / 'repos' / 'branch-trunk',
        branch='trunk',
    )

    with (tmp_path / 'courses.yml').open('w') as f:
        yaml.dump({
            'courses/basic': {
                'url': str(tmp_path / 'repos/basic'),
                'branch': 'main',
                'featured': 1,
                'canonical': True,
            },
            'courses/branch': {
                'url': str(tmp_path / 'repos/branch-trunk'),
                'branch': 'trunk',
                'canonical': True,
            },
            'courses/alternate': {
                'url': str(tmp_path / 'repos/basic'),
                'branch': 'main',
                'featured': 2,
            },
            'lessons': {
                'url': str(tmp_path / 'repos/basic'),
                'branch': 'main',
            },
        }, f)

    model.load_local_courses(tmp_path)
    assert sorted(model.courses) == [
        'courses/alternate', 'courses/basic', 'courses/branch', 'lessons',
    ]
    assert [c.slug for c in model.featured_courses] == [
        'courses/basic', 'courses/alternate',
    ]
    assert model.courses['courses/alternate'].canonical == False
    assert model.courses['courses/basic'].canonical == True
    assert model.courses['courses/branch'].canonical == True
    assert model.courses['lessons'].canonical == False
