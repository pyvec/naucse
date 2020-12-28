import datetime

try:
    import zoneinfo
except ImportError:
    from backports import zoneinfo

import pytest

from naucse.datetimes import fix_session_time


PRAGUE_TZ = zoneinfo.ZoneInfo('Europe/Prague')
EASTER_TZ = zoneinfo.ZoneInfo('Pacific/Easter')
CHRISTMAS_TZ = zoneinfo.ZoneInfo('Indian/Christmas')

CHRISTMAS = datetime.datetime(2020, 12, 24, 17, tzinfo=CHRISTMAS_TZ)
TEST_DT = datetime.datetime(2020, 12, 28, 18, tzinfo=PRAGUE_TZ)
EASTER = datetime.datetime(2021, 4, 1, 19, tzinfo=CHRISTMAS_TZ)

DATES = (
    None,
    {'start': CHRISTMAS},
    {'start': CHRISTMAS, 'end': EASTER},
)

TIMES = (
    None,
    {'start': datetime.time(18, 0)},
    {'start': datetime.time(18, 0), 'end': datetime.time(18, 10)},
)


@pytest.mark.parametrize('session_date', DATES)
@pytest.mark.parametrize('default_time', TIMES)
@pytest.mark.parametrize('default_timezone', (CHRISTMAS_TZ, EASTER_TZ))
def test_complete_info(session_date, default_time, default_timezone):
    """With complete session_times, other info is ignored"""
    session_times = {
        'start': datetime.datetime(2020, 12, 24, 18, tzinfo=CHRISTMAS_TZ),
        'end': datetime.datetime(2020, 12, 28, 18, tzinfo=PRAGUE_TZ),
    }
    result = fix_session_time(dict(session_times), None, None, None, 'test')
    assert result == session_times


def test_all_none():
    result = fix_session_time(None, None, None, None, 'test')
    assert result == None


def test_add_date():
    result = fix_session_time(
        {'start': datetime.time(18, 0), 'end': datetime.time(19, 10)},
        datetime.date(2020, 12, 28),
        None,
        PRAGUE_TZ,
        'test',
    )
    assert result == {
        'start':  datetime.datetime(2020, 12, 28, 18, tzinfo=PRAGUE_TZ),
        'end': datetime.datetime(2020, 12, 28, 19, 10, tzinfo=PRAGUE_TZ),
    }


@pytest.mark.parametrize('default_time', TIMES)
def test_add_date(default_time):
    result = fix_session_time(
        {
            'start': datetime.time(18, tzinfo=EASTER_TZ),
            'end': datetime.time(19, 10, tzinfo=CHRISTMAS_TZ),
        },
        datetime.date(2020, 12, 28),
        default_time,  # ignored
        PRAGUE_TZ,
        'test',
    )
    assert result == {
        'start':  datetime.datetime(2020, 12, 28, 18, tzinfo=EASTER_TZ),
        'end': datetime.datetime(2020, 12, 28, 19, 10, tzinfo=CHRISTMAS_TZ),
    }


@pytest.mark.parametrize('default_time', TIMES)
def test_add_date_and_tz(default_time):
    result = fix_session_time(
        {'start': datetime.time(18, 0), 'end': datetime.time(19, 10)},
        datetime.date(2020, 12, 28),
        default_time,  # ignored
        PRAGUE_TZ,
        'test',
    )
    assert result == {
        'start':  datetime.datetime(2020, 12, 28, 18, tzinfo=PRAGUE_TZ),
        'end': datetime.datetime(2020, 12, 28, 19, 10, tzinfo=PRAGUE_TZ),
    }


def test_add_date_and_time():
    result = fix_session_time(
        None,
        datetime.date(2020, 12, 28),
        {
            'start': datetime.time(18, 0),
            'end': datetime.time(19, 10, tzinfo=CHRISTMAS_TZ),
        },
        PRAGUE_TZ,
        'test',
    )
    assert result == {
        'start':  datetime.datetime(2020, 12, 28, 18, tzinfo=PRAGUE_TZ),
        'end': datetime.datetime(2020, 12, 28, 19, 10, tzinfo=CHRISTMAS_TZ),
    }


def test_error_missing_timezone():
    with pytest.raises(ValueError) as err:
        result = fix_session_time(
            None,
            datetime.date(2020, 12, 28),
            {
                'start': datetime.time(18, 0),
                'end': datetime.time(19, 10, tzinfo=CHRISTMAS_TZ),
            },
            None,
            '_test_session_name_',
        )
    assert '_test_session_name_' in str(err)
