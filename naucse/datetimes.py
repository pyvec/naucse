"""Converters and helper functions for session dates and times

Time handling is unfortunately a bit complicated for several reasons:
- Dates/times in the input API can come in several text formats, e.g. with
  seconds or timezones either included or left off.
- A session's time is an interval with start and end times.
- A session's start and end times can be fully specified in the session,
  specified without date and/or timezone, or left out.
  The missing information is filled in from:
    - the session's date (single default date for both start and end times)
    - the course's default time
    - the course's timezone
"""
import datetime

try:
    import zoneinfo
except ImportError:
    from backports import zoneinfo

from naucse.converters import BaseConverter

# Before API 0.3, a fixed timezone was assumed
_OLD_DEFAULT_TIMEZONE = zoneinfo.ZoneInfo('Europe/Prague')


def _strptime_with_optional_z(data, dateformat):
    """Like datetime.strptime, but with possibly empty timezone for %z

    If there is no timezone offset, the "%z" is ignored and a naive datetime
    object is returned.
    """
    if not ('+' in data or '-' in data):
        dateformat = dateformat.replace('%z', '')
    return datetime.datetime.strptime(data, dateformat)


def time_from_string(time_string):
    """Get datetime.time object from a 'HH:MM' or 'HH:MM+ZZZZ' string"""
    return _strptime_with_optional_z(time_string, '%H:%M').timetz()


class SessionTimeConverter(BaseConverter):
    """Convert a single session time, represented in JSON as string

    May be loaded as a complete datetime, or as just date or None.
    May contain a timezone offset on input.

    The `fix_session_time` function needs to be called on the session time
    to fill in any missing information.

    Converted to the full datetime on output.
    """
    def load(self, data, context):
        if data.count(':') == 2:
            time_format = '%H:%M:%S'
        else:
            time_format = '%H:%M'
        try:
            return _strptime_with_optional_z(data, f'%Y-%m-%d {time_format}%z')
        except ValueError:
            return _strptime_with_optional_z(data, f'{time_format}%z').timetz()

    def dump(self, value, context):
        if context.version < (0, 3):
            value = value.astimezone(_OLD_DEFAULT_TIMEZONE)
            return value.strftime('%Y-%m-%d %H:%M:%S')
        else:
            return value.strftime('%Y-%m-%d %H:%M:%S%z')

    @classmethod
    def get_schema(cls, context):
        _date_re = '[0-9]{4}-[0-9]{2}-[0-9]{2}'
        if context.version < (0, 3):
            _tz_re = ''
            _optional_tz_re = ''
        else:
            _tz_re = '[+-][0-9]{4}'
            _optional_tz_re = f'({_tz_re})?'
        if context.is_input:
            _time_re = '[0-9]{1,2}:[0-9]{2}(:[0-9]{2})?'
            pattern = f'^({_date_re} )?{_time_re}{_optional_tz_re}$'
        else:
            _time_re = '[0-9]{2}:[0-9]{2}:[0-9]{2}'
            pattern = f'^{_date_re} {_time_re}{_tz_re}$'
        return {
            'type': 'string',
            'pattern': pattern,
        }


class DateConverter(BaseConverter):
    """Converter for datetime.date values (as 'YYYY-MM-DD' strings in JSON)"""
    def load(self, data, context):
        return datetime.datetime.strptime(data, "%Y-%m-%d").date()

    def dump(self, value, context):
        return str(value)

    def get_schema(self, context):
        return {
            'type': 'string',
            'pattern': r'^[0-9]{4}-[0-9]{2}-[0-9]{2}$',
            'format': 'date',
        }


class ZoneInfoConverter(BaseConverter):
    """Converter for ZoneInfo values (in JSON as keys, e.g. 'Europe/Prague')"""
    def load(self, data, context):
        return zoneinfo.ZoneInfo(data)

    def dump(self, value, context):
        return value.key

    @classmethod
    def get_schema(cls, context):
        return {
            'type': 'string',
            'pattern': '[A-Za-z0-9/+_-]+'
        }


class TimeIntervalConverter(BaseConverter):
    """Converter for a time interval, as a dict with 'start' and 'end'"""
    def load(self, data, context):
        return {
            'start': time_from_string(data['start']),
            'end': time_from_string(data['end']),
        }

    def dump(self, value, context):
        time_format = '%H:%M'
        return {
            'start': value['start'].strftime(time_format),
            'end': value['end'].strftime(time_format),
        }

    @classmethod
    def get_schema(cls, context):
        return {
            'type': 'object',
            'properties': {
                'start': {'type': 'string', 'pattern': '[0-9]{1,2}:[0-9]{2}'},
                'end': {'type': 'string', 'pattern': '[0-9]{1,2}:[0-9]{2}'},
            },
            'required': ['start', 'end'],
            'additionalProperties': False,
        }


def fix_session_time(
    session_time, session_date, default_time, default_timezone, session_name,
):
    """Combine a session time from all the available information.

    The session time is represented as a dict with `start` and `end` keys.

    session_time:
        start and end datetime (dict) given for the session.
        May be complete (datetime with timezone), or incomplete (time only,
        no timezone, or None).
        Overrides all other information.
    session_date:
        start and end date (dict) given for the session.
        Used if session_time doesn't specify a date.
    default_time:
        Per-course default time (with or without a timezone).
        Used if session_time doesn't specify a time.
    default_timezone:
        Per-course default time (with or without a timezone).
        Used if session_time doesn't specify a time.
    session_name:
        Used for error messages.
    """
    if session_time is None:
        session_time = {}
    else:
        if set(session_time) != {'start', 'end'}:
            raise ValueError('Session time may must have start and end')
    result = {}
    for kind in 'start', 'end':
        time = session_time.get(kind, None)
        if isinstance(time, datetime.datetime):
            pass
        elif isinstance(time, datetime.time):
            if session_date:
                time = datetime.datetime.combine(session_date, time)
            else:
                return None
        elif time is None:
            if session_date and default_time:
                time = datetime.datetime.combine(
                    session_date, default_time[kind],
                )
            else:
                return None
        else:
            raise TypeError(time)
        if time.tzinfo is None:
            if default_timezone is None:
                raise ValueError(
                    f'{kind} time of session {session_name} is missing '
                    + 'timezone information. Provide an offset or set '
                    + 'a timezone for the whole course.')
            time = time.replace(tzinfo=default_timezone)
        result[kind] = time
    return result
