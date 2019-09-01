import datetime

import pytest
import dateutil.tz
import jsonschema

from naucse import models
from test_naucse.conftest import fixture_path, add_test_course


TZINFO = dateutil.tz.gettz('Europe/Prague')


SESSIONS = [
    {
        'title': 'A normal session',
        'slug': 'normal-session',
        'date': '2000-01-01',
    },
    {
        'title': 'Afterparty (with overridden time)',
        'slug': 'afterparty',
        'date': '2000-01-01',
        'time': {'start': '22:00', 'end': '23:00'},
    },
    {
        'title': 'Self-study (no date)',
        'slug': 'self-study',
    },
    {
        'title': 'Umm... no date, but a time',
        'slug': 'morning-meditation',
        'time': {'start': '7:00', 'end': '8:00'},
    },
]


def test_run_with_default_times(model, assert_model_dump):
    add_test_course(model, 'courses/with-default-times', {
        'title': 'Test course with default times',
        'default_time': {'start': '19:00', 'end': '21:00'},
        'sessions': SESSIONS,
    })

    course = model.courses['courses/with-default-times']
    assert course.default_time == {
        'start': datetime.time(19, 00, tzinfo=TZINFO),
        'end': datetime.time(21, 00, tzinfo=TZINFO),
    }

    session = course.sessions['normal-session']
    assert session.date == datetime.date(2000, 1, 1)
    assert session.time == {
        'start': datetime.datetime(2000, 1, 1, 19, tzinfo=TZINFO),
        'end': datetime.datetime(2000, 1, 1, 21, tzinfo=TZINFO),
    }

    session = course.sessions['afterparty']
    assert session.date == datetime.date(2000, 1, 1)
    assert session.time == {
        'start': datetime.datetime(2000, 1, 1, 22, tzinfo=TZINFO),
        'end': datetime.datetime(2000, 1, 1, 23, tzinfo=TZINFO),
    }

    session = course.sessions['self-study']
    assert session.date == None
    assert session.time == None

    session = course.sessions['morning-meditation']
    assert session.date == None
    assert session.time == None

    assert_model_dump(course, 'session-times/with-default-times')


def test_course_with_no_default_time(model, assert_model_dump):
    add_test_course(model, 'courses/without-default-time', {
        'title': 'Test course without scheduled times',
        'sessions': SESSIONS,
    })

    course = model.courses['courses/without-default-time']
    assert course.default_time is None

    session = course.sessions['normal-session']
    assert session.date == datetime.date(2000, 1, 1)
    assert session.time is None

    session = course.sessions['afterparty']
    assert session.date == datetime.date(2000, 1, 1)
    assert session.time == {
        'start': datetime.datetime(2000, 1, 1, 22, tzinfo=TZINFO),
        'end': datetime.datetime(2000, 1, 1, 23, tzinfo=TZINFO),
    }

    session = course.sessions['self-study']
    assert session.date == None
    assert session.time == None

    session = course.sessions['morning-meditation']
    assert session.date == None
    assert session.time == None

    assert_model_dump(course, 'session-times/without-default-time')


def test_course_without_dates(model, assert_model_dump):
    add_test_course(model, 'courses/without-dates', {
        'title': 'A plain vanilla course',
        'sessions': [
            {
                'title': 'A normal session',
                'slug': 'normal-session',
            },
        ],
    })

    course = model.courses['courses/without-dates']
    assert course.default_time is None

    session = course.sessions['normal-session']
    assert session.date is None
    assert session.time is None

    assert_model_dump(course, 'session-times/without-dates')


BAD_TIMES = {
    'empty': {},
    'start_only': {'start': '19:00'},
    'start_hour_only': {'start': '19', 'end': '21'},
    'end_hour_only': {'start': '19:00', 'end': '21'},
    'not_a_time': {'start': '00:00', 'end': '55:00'},
    'extra': {'start': '19:00', 'end': '21:00', 'break': '00:30'},
}

@pytest.mark.parametrize('key', BAD_TIMES)
def test_invalid_default_time(model, key):
    with pytest.raises((jsonschema.ValidationError, ValueError)):
        add_test_course(model, 'courses/invalid', {
            'title': 'Bad course',
            'default_time': BAD_TIMES[key],
            'sessions': [],
        })

@pytest.mark.parametrize('key', BAD_TIMES)
def test_invalid_session_time(model, key):
    with pytest.raises((jsonschema.ValidationError, ValueError)):
        add_test_course(model, 'courses/invalid', {
            'title': 'Bad course',
            'sessions': [
                {
                    'title': 'A session',
                    'slug': 'session',
                    'time': BAD_TIMES[key],
                },
            ],
        })


def test_course_api02_fails_without_timezone(model):
    """Time without a timezone is not allowed in API 0.3+"""
    with pytest.raises(ValueError):
        add_test_course(
            model,
            'courses/test',
            {
                'title': 'Test course',
                'default_time': {'start': '18:00', 'end': '20:00'},
                'sessions': [
                    {
                        'title': 'A session with a date',
                        'slug': 'dated-session',
                        'date': '2019-01-01',
                    },
                ],
            },
            version=(0, 3),
        )


def test_course_api02_ok_without_timezone(model):
    """No timezone is OK in API 0.3+ if there's not time info"""
    add_test_course(
        model,
        'courses/test',
        {
            'title': 'Test course',
            'default_time': {'start': '18:00:00', 'end': '20:00'},
            'sessions': [
                {
                    'title': 'A self-study session',
                    'slug': 'undated-session',
                },
            ],
        },
        version=(0, 3),
    )
    course = model.courses['courses/test']
    assert course.timezone is None
    assert course.sessions['undated-session'].date is None
    assert course.sessions['undated-session'].time is None


def test_course_api02_ok_without_timezone(model):
    """No timezone is OK in API 0.3+ if explicit TZ offset is always given"""
    add_test_course(
        model,
        'courses/test',
        {
            'title': 'Test course',
            'default_time': {'start': '18:00', 'end': '20:00'},
            'sessions': [
                {
                    'title': 'A precisely specified session',
                    'slug': 'specified-session',
                    'time': {
                        'start': '2019-01-01 18:00:00+0100',
                        'end': '2019-01-01 20:00+0100',
                    }
                },
            ],
        },
        version=(0, 3),
    )
    course = model.courses['courses/test']
    assert course.timezone is None
    assert course.sessions['specified-session'].date is None
    tzinfo = dateutil.tz.tzoffset('+0100', 3600)
    assert course.sessions['specified-session'].time == {
        'start': datetime.datetime(2019, 1, 1, 18, 0, tzinfo=tzinfo),
        'end': datetime.datetime(2019, 1, 1, 20, 0, tzinfo=tzinfo),
    }
