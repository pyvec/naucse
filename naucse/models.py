import datetime
from pathlib import Path
import collections.abc
import re
import os
import shutil
from itertools import chain

import yaml
from arca import Arca

from naucse.edit_info import get_local_repo_info, get_repo_info
from naucse.converters import Field, VersionField, register_model
from naucse.converters import BaseConverter, ListConverter, DictConverter
from naucse.converters import KeyAttrDictConverter, ModelConverter
from naucse.converters import dump, load, get_converter, get_schema
from naucse import sanitize
from naucse.logger import logger
from naucse.datetimes import SessionTimeConverter, DateConverter
from naucse.datetimes import ZoneInfoConverter, TimeIntervalConverter
from naucse.datetimes import fix_session_time, _OLD_DEFAULT_TIMEZONE
from naucse.exceptions import UntrustedRepo
from naucse import arca_renderer, local_renderer, compiled_renderer


API_VERSION = 0, 4


class NoURL(LookupError):
    """An object's URL could not be found"""

class NoURLType(NoURL):
    """The requested URL type is not available"""

class URLConverter(BaseConverter):
    def load(self, data, context):
        return sanitize.convert_link('href', data)

    def dump(self, value, context):
        return value

    @classmethod
    def get_schema(cls, context):
        return {'type': 'string', 'format': 'uri'}


models = {}


class Model:
    """Base class for naucse models

    Class attributes:

    `init_arg_names` are names of keyword arguments for `__init__`.
    These are copied to attributes of the same name.

    `parent_attrs` is a tuple of attribute names of the object's parents.
    The first for the parent itself; the subsequent ones are set from the
    parent.

    `model_slug` is a Python identifier used in URLs and fragments. It is set
    automatically by default, but can be overridden or set to None in each
    class.

    `pk_name` is the name that holds a primary key
    """
    init_arg_names = {'parent'}
    parent_attrs = ()
    pk_name = None

    def __init__(self, **kwargs):
        for a in self.init_arg_names:
            setattr(self, a, kwargs[a])
        for p in self.parent_attrs[:1]:
            setattr(self, p, self.parent)
        for p in self.parent_attrs[1:]:
            setattr(self, p, getattr(self.parent, p))
        self.root = self.parent.root

    def __init_subclass__(cls):
        try:
            slug = cls.model_slug
        except AttributeError:
            slug = re.sub('([A-Z])', r'-\1', cls.__name__).lower().lstrip('-')
        cls.model_slug = slug
        models[slug] = cls
        if not hasattr(cls, '_naucse__converter'):
            converter = ModelConverter(
                cls, load_arg_names=cls.init_arg_names, slug=slug,
                extra_fields=[Field(
                    URLConverter(), name='_url', data_key='url', input=False,
                    optional=True,
                    doc="URL for a user-facing page on naucse",
                )],
            )
            converter.get_schema_url=_get_schema_url
            register_model(cls, converter)

    def get_url(self, url_type='web', *, external=False):
        return self.root._url_for(
            type(self), pks=self.get_pks(),
            url_type=url_type, external=external)

    def get_pks(self):
        pk_name = f'{self.model_slug}_{self.pk_name}'
        return {**self.parent.get_pks(), pk_name: getattr(self, self.pk_name)}

    @property
    def _url(self):
        try:
            return self.get_url(external=True)
        except NoURL:
            return None
    @_url.setter
    def _url(self, value):
        return

    def __repr__(self):
        pks = ' '.join(f'{k}={v}' for k, v in self.get_pks().items())
        return f'<{type(self).__qualname__} {pks}>'


def _get_schema_url(instance, *, is_input):
    return instance.root.schema_url_factory(
        type(instance), is_input=is_input, _external=True
    )


class HTMLFragmentConverter(BaseConverter):
    """Converter for a HTML fragment."""
    load_arg_names = {'parent'}

    def load(self, value, context, *, parent):
        return sanitize.sanitize_html(value)

    def dump(self, value, context):
        return str(value)

    @classmethod
    def get_schema(cls, context):
        return {
            'type': 'string',
            'format': 'html-fragment',
        }

class CourseHTMLFragment:
    def __init__(self, page, value):
        self.page = page
        if isinstance(value, str):
            self._content = self.convert(value)
            self.path = None
        else:
            self._content = None
            self.path = value['path']

    def dump(self):
        if self.path:
            return {'path': self.path}
        else:
            return self.content

    @property
    def content(self):
        return self.freeze()

    def __str__(self):
        return self.content

    def __html__(self):
        return self.content

    def convert(self, content):
        """Sanitize HTML and rewrites URLs for given content."""
        def page_url(*, lesson, page='index', **kw):
            return self.page.course.get_lesson_url(lesson, page=page)

        def solution_url(*, solution, **kw):
            return self.page.solutions[int(solution)].get_url(**kw)

        def static_url(*, filename, **kw):
            return self.page.lesson.static_files[filename].get_url(**kw)

        return sanitize.sanitize_html(
            content,
            naucse_urls={
                'page': page_url,
                'solution': solution_url,
                'static': static_url,
            }
        )

    def freeze(self):
        if self._content is not None:
            return self._content
        renderer = self.page.course.renderer
        path_or_file = renderer.get_path_or_file(self.path)
        if read := getattr(path_or_file, 'read', None):
            with path_or_file:
                value = path_or_file.read()
            if isinstance(value, bytes):
                value = value.decode()
        else:
            value = Path(path_or_file).read_text(encoding='utf-8')
        self._content = self.convert(value)
        return self._content


class CourseHTMLFragmentConverter(BaseConverter):
    load_arg_names = {'parent'}

    def load(self, value, context, *, parent):
        return CourseHTMLFragment(parent, value)

    def dump(self, value, context):
        return value.content

    @classmethod
    def get_schema(cls, context):
        return {
            "anyOf": [
                {
                    'type': 'string',
                    'format': 'html-fragment',
                },
                {
                    'type': 'object',
                    'description':
                        'HTML fragment loaded from a file external '
                        + 'to the JSON data',
                    'properties': {
                        'path': {
                            'type': 'string',
                            'pattern': '^[-_./a-z0-9]+$'
                        }
                    },
                    'required': ['path'],
                },
            ]
        }


class Solution(Model):
    """Solution to a problem on a Page
    """
    init_arg_names = {'parent', 'index'}
    pk_name = 'index'
    parent_attrs = 'page', 'lesson', 'course'

    content = Field(
        CourseHTMLFragmentConverter(),
        output=False,
        doc="The right solution, as HTML")


class RelativePathConverter(BaseConverter):
    """Converter for a relative path, as string"""
    def load(self, data, context):
        return Path(data)

    def dump(self, value, context):
        return str(value)

    def get_schema(self, context):
        return {
            'type': 'string',
            'pattern': '^[^./][^/]*(/[^./][^/]*)*$'
        }


source_file_field = Field(
    RelativePathConverter(),
    name='source_file',
    optional=True,
    doc="Path to a source file containing the page's text, "
        + "relative to the repository root")

@source_file_field.after_load()
def _edit_info(self, context):
    if self.source_file is None:
        self.edit_info = None
    else:
        self.edit_info = self.course.repo_info.get_edit_info(self.source_file)


class StaticFile(Model):
    """Static file specific to a Lesson
    """
    init_arg_names = {'parent', 'filename'}
    pk_name = 'filename'
    parent_attrs = 'lesson', 'course'

    def get_pks(self):
        return {**self.parent.get_pks(), 'filename': self.filename}

    def get_path_or_file(self):
        return self.course.renderer.get_path_or_file(self.path)

    path = Field(RelativePathConverter(), doc="Relative path of the file")


class PageCSSConverter(BaseConverter):
    """Converter for CSS for a Page"""
    def load(self, value, context):
        return sanitize.sanitize_css(value)

    def dump(self, value, context):
        return value

    @classmethod
    def get_schema(cls, context):
        return {
            'type': 'string',
            'contentMediaType': 'text/css',
        }


class LicenseConverter(BaseConverter):
    """Converter for a licence (specified as its slug in JSON)"""
    load_arg_names = {'parent'}

    def load(self, value, context, *, parent):
        return parent.root.licenses[value]

    def dump(self, value, context):
        return value.slug

    @classmethod
    def get_schema(cls, context):
        return {
            'type': 'string',
        }


class Page(Model):
    """One page of teaching text
    """
    init_arg_names = {'parent', 'slug'}
    pk_name = 'slug'
    parent_attrs = 'lesson', 'course'

    subtitle = VersionField({
        (0, 2): Field(
            str, optional=True,
            doc="""Human-readable subpage title.
                Required for index subpages other than "index" (unless "title"
                is given).
                """
        ),
    })
    title = VersionField({
        (0, 2): Field(
            str, optional=True,
            doc="""Human-readable page title.

                Deprecated since API version 0.2: use lesson.title
                (and, for subpages other than index, page.subtitle)
                """
        ),
        (0, 0): Field(str, doc='Human-readable title'),
    })

    @title.after_load()
    def _generate_title(self, context):
        if self.title is None:
            if self.slug == 'index':
                self.title = self.lesson.title
            else:
                if self.subtitle is None:
                    raise ValueError('Either title or subtitle is required')
                self.title = f'{self.lesson.title} – {self.subtitle}'

    attribution = Field(ListConverter(HTMLFragmentConverter()),
                        doc='Lines of attribution, as HTML fragments')
    license = Field(
        LicenseConverter(),
        doc='License slugs. Only approved licenses are allowed.')
    license_code = Field(
        LicenseConverter(), optional=True,
        doc='Slug of licence for code snippets.')

    source_file = source_file_field

    css = Field(
        PageCSSConverter(), optional=True,
        doc="CSS specific to this page. (Subject to restrictions which " +
            "aren't yet finalized.)")

    solutions = Field(
        ListConverter(Solution, index_arg='index'),
        factory=list,
        doc="Solutions to problems that appear on the page.")

    modules = Field(
        DictConverter(str), factory=dict,
        doc='Additional modules as a dict with `slug` key and version values')

    content = Field(
        CourseHTMLFragmentConverter(),
        output=False,
        doc='Content, as HTML')

    def freeze(self):
        if self.content:
            self.content.freeze()


class Lesson(Model):
    """A lesson – collection of Pages on a single topic
    """
    init_arg_names = {'parent', 'slug'}
    pk_name = 'slug'
    parent_attrs = ('course', )

    title = VersionField({
        (0, 2): Field(str, doc='Human-readable lesson title')
    })

    static_files = Field(
        DictConverter(StaticFile, key_arg='filename'),
        factory=dict,
        doc="Static files the lesson's content may reference")
    pages = Field(
        DictConverter(Page, key_arg='slug', required={'index'}),
        doc="Pages of content. Used for variants (e.g. a page for Linux and "
            + "another for Windows), or non-essential info (e.g. for "
            + "organizers)")

    @pages.after_load()
    def _set_title(self, context):
        if self.title is None:
            self.title = self.pages['index'].title

    @property
    def material(self):
        """The material that contains this page, or None"""
        for session in self.course.sessions.values():
            for material in session.materials:
                if self == material.lesson:
                    return material

    def freeze(self):
        for page in self.pages.values():
            page.freeze()
        for static_file in self.static_files.values():
            # This should ensure the file exists.
            # (Maybe there should be more efficient API for that.)
            # XXX this can return an open file that isn't closed, but see https://github.com/pyvec/naucse/issues/53
            static_file.get_path_or_file()


class Material(Model):
    """Teaching material, usually a link to a lesson or external page
    """
    parent_attrs = 'session', 'course'
    pk_name = 'slug'

    slug = Field(str, optional=True)
    title = Field(str, optional=True, doc="Human-readable title")
    type = Field(
        str,
        doc="Type of the material (e.g. lesson, homework, cheatsheet, link, "
            + "special). Used for the icon in material lists.")
    external_url = Field(
        URLConverter(), optional=True,
        doc="URL for a link to content that's not a naucse lesson")
    lesson_slug = Field(
        str, optional=True,
        doc="Slug of the corresponding lesson")

    @lesson_slug.after_load()
    def _validate_lesson_slug(self, context):
        if self.lesson_slug and self.external_url:
            raise ValueError(
                'external_url and lesson_slug are incompatible'
            )

    @property
    def lesson(self):
        """Lesson for this Material, or None"""
        if self.lesson_slug is not None:
            return self.course.lessons[self.lesson_slug]

    def get_url(self, url_type='web', **kwargs):
        # The material has no URL itself; it refers to a lesson, an external
        # resource, or to nothing.
        if self.lesson_slug:
            return self.course.get_lesson_url(self.lesson_slug)
        if url_type != 'web':
            raise NoURLType(url_type)
        if self.external_url:
            return self.external_url
        raise NoURL(self)

    def url_or_none(self, *args, **kwargs):
        try:
            return self.get_url(*args, **kwargs)
        except NoURL:
            return None


class SessionPage(Model):
    """Session-specific page, e.g. the front cover
    """
    init_arg_names = {'parent', 'slug'}
    pk_name = 'slug'
    parent_attrs = 'session', 'course'

    content = Field(
        HTMLFragmentConverter(),
        factory=str,
        doc='Content, as HTML')

    def get_pks(self):
        return {**self.parent.get_pks(), 'page_slug': self.slug}


def set_prev_next(sequence):
    """Set "prev" and "next" attributes of each element of a sequence"""
    sequence = list(sequence)
    for prev, now, next in zip(
        [None] + sequence,
        sequence,
        sequence[1:] + [None],
    ):
        now.prev = prev
        now.next = next


class Session(Model):
    """A smaller collection of teaching materials

    Usually used for one meeting of an in-preson course or
    a self-contained section of a longer workshop.
    """
    init_arg_names = {'parent', 'index'}
    pk_name = 'slug'
    parent_attrs = ('course', )

    slug = Field(str)
    title = Field(str, doc="A human-readable session title")
    date = Field(
        DateConverter(), optional=True,
        doc="The date when this session occurs (if it has a set time)",
    )
    serial = VersionField({
        (0, 1): Field(
            str,
            optional=True,
            doc="""
                Human-readable string identifying the session's position
                in the course.
                The serial is usually numeric: `1`, `2`, `3`, ...,
                but, for example, i, ii, iii... can be used for appendices.
                Some courses start numbering sessions from 0.
            """
        ),
        # For API version 0.0, serial is generated in
        # Course._sessions_after_load.
    })

    description = Field(
        HTMLFragmentConverter(), optional=True,
        doc="Short description of the session.")

    source_file = source_file_field

    materials = Field(
        ListConverter(Material),
        factory=list,
        doc="The session's materials",
    )

    @materials.after_load()
    def _index_materials(self, context):
        set_prev_next(m for m in self.materials if m.lesson_slug)

    pages = Field(
        DictConverter(SessionPage, key_arg='slug'),
        optional=True,
        doc="The session's cover pages")
    @pages.after_load()
    def _set_pages(self, context):
        if not self.pages:
            self.pages = {}
        for slug in 'front', 'back':
            if slug not in self.pages:
                page = load(
                    SessionPage,
                    {'api_version': [0, 0], 'session-page': {}},
                    slug=slug, parent=self,
                )
                self.pages[slug] = page

    time = Field(
        DictConverter(SessionTimeConverter(), required=['start', 'end']),
        optional=True,
        doc="Time when this session takes place.")

    @time.after_load()
    def _fix_time(self, context):
        self.time = fix_session_time(
            self.time, self.date, self.course.default_time,
            self.course.timezone, self.slug,
        )


class AnyDictConverter(BaseConverter):
    """Converter of any JSON-encodable dict"""
    def load(self, data, context):
        return data

    def dump(self, value, context):
        return value

    @classmethod
    def get_schema(cls, context):
        return {'type': 'object'}


class _LessonsDict(collections.abc.Mapping):
    """Dict of lessons with lazily loaded entries"""
    def __init__(self, course):
        self.course = course

    def __getitem__(self, key):
        try:
            return self.course._lessons[key]
        except KeyError:
            self.course.load_lessons([key])
        return self.course._lessons[key]

    def __iter__(self):
        self.course.freeze()
        return iter(self.course._lessons)

    def __len__(self):
        self.course.freeze()
        return len(self.course._lessons)


class RepoInfoConverter(BaseConverter):
    """Converter of any JSON-encodable dict"""
    def load(self, data, context):
        return get_repo_info(data['url'], data['branch'])

    def dump(self, value, context):
        return value.as_dict()

    @classmethod
    def get_schema(cls, context):
        return {
            'type': 'object',
            'fields': {
                'url': {
                    'type': 'string',
                    'format': 'uri',
                },
                'branch': {
                    'type': 'string',
                },
            },
            'required': ['url', 'branch'],
        }


class Course(Model):
    """Collection of sessions
    """
    pk_name = 'slug'

    def __init__(
        self, *, parent, slug, renderer, is_meta=False, canonical=False,
    ):
        super().__init__(parent=parent)
        self.slug = slug
        self.renderer = renderer
        self.is_meta = is_meta
        self.course = self
        self._frozen = False
        self._freezing = False
        self.canonical = canonical

        self._lessons = {}
        self._requested_lessons = set()

    lessons = Field(
        DictConverter(Lesson), input=False, doc="""Lessons""")

    @lessons.default_factory()
    def _default_lessons(self):
        return _LessonsDict(self)

    title = Field(str, doc="""Human-readable title""")
    subtitle = Field(
        str, optional=True,
        doc="Human-readable subtitle, mainly used to distinguish several "
            + "runs of same-named courses.")
    description = Field(
        str, optional=True,
        doc="Short description of the course (about one line).")
    long_description = Field(
        HTMLFragmentConverter(), factory=str,
        doc="Long description of the course (up to several paragraphs).")
    vars = Field(
        AnyDictConverter(), factory=dict,
        doc="Defaults for additional values used for rendering pages")
    place = Field(
        str, optional=True,
        doc="Human-readable description of the venue")
    time_description = Field(
        str, optional=True,
        doc="Human-readable description of the time the course takes place "
            + "(e.g. 'Wednesdays')")

    default_time = Field(
        TimeIntervalConverter(), optional=True,
        doc="Default start and end time for sessions")

    timezone = VersionField({
        (0, 3): Field(
            ZoneInfoConverter(), data_key='timezone', optional=True,
            doc="Timezone for times specified without a timezone (i.e. as "
                + "HH:MM (rather than HH:MM+ZZZZ). "
                + "Mandatory if such times appear in the course."
        )
    })

    _edit_info = VersionField({
        (0, 4): Field(
            RepoInfoConverter(),
            doc="""Information about a repository where the content can be edited""",
            data_key='edit_info',
            optional=True,
        )
    })

    @property
    def repo_info(self):
        return self._edit_info or self.renderer.get_repo_info()

    @timezone.after_load()
    def set_timezone(self, context):
        if self.timezone is None and context.version < (0, 3):
            self.timezone = _OLD_DEFAULT_TIMEZONE

    sessions = Field(
        KeyAttrDictConverter(Session, key_attr='slug', index_arg='index'),
        doc="Individual sessions")

    @sessions.after_load()
    def _sessions_after_load(self, context):
        set_prev_next(self.sessions.values())

        for session in self.sessions.values():
            for material in session.materials:
                if material.lesson_slug:
                    self._requested_lessons.add(material.lesson_slug)

        if context.version < (0, 1) and len(self.sessions) > 1:
            # Assign serials to sessions (numbering from 1)
            for serial, session in enumerate(self.sessions.values(), start=1):
                session.serial = str(serial)

    source_file = source_file_field

    start_date = Field(
        DateConverter(),
        doc='Date when this course starts, or None')

    @start_date.default_factory()
    def _construct(self):
        dates = [getattr(s, 'date', None) for s in self.sessions.values()]
        return min((d for d in dates if d), default=None)

    end_date = Field(
        DateConverter(),
        doc='Date when this course ends, or None')

    @end_date.default_factory()
    def _construct(self):
        dates = [getattr(s, 'date', None) for s in self.sessions.values()]
        return max((d for d in dates if d), default=None)

    etag = Field(
        str, optional=True,
        doc="Optional string that should change when the course's content "
            + "changes, similar to the HTTP ETag.\n"
            + "If missing from the input course, the etag may be "
            + "generated by the naucse server."
    )

    @classmethod
    def from_renderer(
        cls, *, parent, renderer, canonical=False,
    ):
        data = renderer.get_course()
        slug = renderer.slug
        is_meta = (slug == 'courses/meta')
        result = load(
            cls, data, slug=slug, parent=parent, renderer=renderer,
            is_meta=is_meta, canonical=canonical,
        )
        return result

    # XXX: Is course derivation useful?
    derives = Field(
        str, optional=True,
        doc="Slug of the course this derives from (deprecated)")

    @derives.after_load()
    def _set_base_course(self, context):
        key = f'courses/{self.derives}'
        try:
            self.base_course = self.root.courses[key]
        except KeyError:
            self.base_course = None

    def get_recent_derived_runs(self):
        result = []
        if self.canonical:
            today = datetime.date.today()
            cutoff = today - datetime.timedelta(days=2*30)
            for course in self.root.courses.values():
                if (
                    course.start_date
                    and course.base_course == self
                    and course.end_date > cutoff
                ):
                    result.append(course)
        result.sort(key=lambda course: course.start_date, reverse=True)
        return result

    def get_lesson_url(self, slug, *, page='index', **kw):
        if slug not in self._lessons:
            if self._frozen:
                raise KeyError(slug)
            self._requested_lessons.add(slug)
        return self.root._url_for(
            Page, pks={'page_slug': page, 'lesson_slug': slug,
                       **self.get_pks()}
        )

    def load_lessons(self, slugs):
        if self._frozen:
            raise Exception('course is frozen')
        slugs = set(slugs) - set(self._lessons)
        rendered = self.course.renderer.get_lessons(
            slugs, vars=self.vars,
        )
        new_lessons = load(
            DictConverter(Lesson, key_arg='slug'),
            rendered,
            parent=self,
        )
        for slug in slugs:
            try:
                lesson = new_lessons[slug]
            except KeyError:
                raise ValueError(f'{slug} missing from rendered lessons')
            self._lessons[slug] = lesson
            self._requested_lessons.discard(slug)
            if self._freezing:
                lesson.freeze()

    def load_all_lessons(self):
        if self._frozen:
            return
        if self._freezing:
            for lesson in self.lessons.values():
                lesson.freeze()
        self._requested_lessons.difference_update(self._lessons)
        link_depth = 50
        while self._requested_lessons:
            self._requested_lessons.difference_update(self._lessons)
            if not self._requested_lessons:
                break
            self.load_lessons(self._requested_lessons)
            link_depth -= 1
            if link_depth < 0:
                # Avoid infinite loops in lessons
                raise ValueError(
                    f'Lessons in course {self.slug} are linked too deeply')

    def _has_lesson(self, slug):
        # HACK for getting "canonical lesson" info
        return (
            slug in self.course._lessons
            or slug in self.course._requested_lessons
        )

    def freeze(self):
        if self._frozen or self._freezing:
            return
        self._freezing = True
        self.load_all_lessons()
        self._frozen = True


class AbbreviatedDictConverter(DictConverter):
    """Dict that only shows URLs to its items when dumped"""
    def dump(self, value, context):
        return {
            key: {'$ref': v.get_url('api', external=True)}
            for key, v in value.items()
        }

    def get_schema(self, context):
        return {
            'type': 'object',
            'additionalProperties': {
                '$ref': '#/definitions/ref',
            },
        }


class RunYear(Model, collections.abc.MutableMapping):
    """Collection of courses given in a specific year

    A RunYear behaves as a dict (slug to Course).
    It should contain all courses that take place in a given year.
    One course may be in multiple RunYears if it doesn't start and end in the
    same calendar year.

    RunYear is just a grouping mechanism. It exists to limit the length of
    API responses.
    Some course slugs include a year in them; that's just for extra
    uniqueness and has nothing to do with RunYear.
    """
    pk_name = 'year'

    _naucse__converter = AbbreviatedDictConverter(Course)
    _naucse__converter.get_schema_url=_get_schema_url

    def __init__(self, year, *, parent=None):
        super().__init__(parent=parent)
        self.year = year
        self.runs = {}

    def __getitem__(self, slug):
        return self.runs[slug]

    def __setitem__(self, slug, course):
        self.runs[slug] = course

    def __delitem__(self, slug):
        del self.runs[slug]

    def __iter__(self):
        # XXX: Sort by ... start date?
        return iter(self.runs)

    def __len__(self):
        return len(self.runs)

    def get_pks(self):
        return {**self.parent.get_pks(), 'year': self.year}


class License(Model):
    """A license for content or code
    """
    init_arg_names = {'parent', 'slug'}
    pk_name = 'slug'

    url = Field(str)
    title = Field(str)

    def get_url(self, *args, **kwargs):
        # A Licence always has an external URL
        return self.url


class Root(Model):
    """Data for the naucse website

    Contains a collection of courses plus additional metadata.
    """
    # Also responsible for loading the courses from (meta)data on disk.

    def __init__(
        self, *,
        url_factories=None,
        schema_url_factory=None,
        renderers={},
        repo_info=None,
        # Overrides for tests:
        arca=None,
        trusted_repo_patterns=None,
    ):
        self.root = self
        self.url_factories = url_factories or {}
        self.schema_url_factory = schema_url_factory
        super().__init__(parent=self)
        self.renderers = renderers

        self.courses = {}
        self.run_years = {}
        self.licenses = {}
        self.self_study_courses = {}

        self._repo_info_override = repo_info

        # Repos we trust for code execution
        if trusted_repo_patterns is None:
            trusted = os.environ.get(
                'NAUCSE_TRUSTED_REPOS', None
            )
            if trusted is not None:
                trusted_repo_patterns = tuple(
                    line for line in trusted.split() if line
                )
        self.trusted_repo_patterns = trusted_repo_patterns or ()

        # Arca object for the Arca backend
        if arca is None:
            arca = Arca(settings={
                "ARCA_BACKEND": "arca.backend.CurrentEnvironmentBackend",
                "ARCA_BACKEND_CURRENT_ENVIRONMENT_REQUIREMENTS": "requirements.txt",
                "ARCA_BACKEND_VERBOSITY": 2,
                "ARCA_BACKEND_KEEP_CONTAINER_RUNNING": True,
                "ARCA_BACKEND_USE_REGISTRY_NAME": "docker.io/naucse/naucse.python.cz",
                "ARCA_SINGLE_PULL": True,
                "ARCA_IGNORE_CACHE_ERRORS": True,
                "ARCA_CACHE_BACKEND": "dogpile.cache.dbm",
                "ARCA_CACHE_BACKEND_ARGUMENTS": {
                    "filename": ".arca/cache/naucse.dbm"
                },
                "ARCA_BASE_DIR": str(Path('.arca').resolve()),
            })
        self.arca = arca

    pk_name = None

    self_study_courses = Field(
        AbbreviatedDictConverter(Course),
        doc="""Links to "canonical" courses – ones without a time span""")
    run_years = Field(
        AbbreviatedDictConverter(RunYear),
        doc="""Links to courses by year""")
    licenses = Field(
        DictConverter(License),
        doc="""Allowed licenses""")

    def set_repo_info(self, repo_info):
        self.repo_info = repo_info

        self.edit_info = self.repo_info.get_edit_info('.')
        self.runs_edit_info = self.repo_info.get_edit_info('runs')
        self.course_edit_info = self.repo_info.get_edit_info('courses')

    def load_local_courses(self, path):
        """Load local courses and lessons from the given path

        Note: Licenses should be loaded before calling load_local_courses,
        otherwise lessons will have no licences to choose from
        """
        self.set_repo_info(get_local_repo_info(path))

        def _load_local_course(slug, **renderer_kwargs):
            renderer = local_renderer.LocalRenderer(
                path=path,
                slug=slug,
                repo_info=self.repo_info,
                **renderer_kwargs,
            )
            course = Course.from_renderer(parent=self, renderer=renderer)
            self.add_course(course)

        for slug in local_renderer.get_course_slugs(path=path):
            print(path, slug)
            _load_local_course(slug)

        for link_path in chain(
            path.glob('courses/**/link.yml'),
            path.glob('runs/**/link.yml'),
        ):
            raise ValueError(
                '"link.yml" files are not supported since naucse 5.0'
            )

        compiled_path = path / 'courses.yml'
        fetcher = compiled_renderer.Fetcher()
        featured_courses = []
        if compiled_path.exists():
            with compiled_path.open() as f:
                courses_info = yaml.safe_load(f)
            for slug, course_info in courses_info.items():
                renderer = compiled_renderer.CompiledRenderer(
                    slug, course_info,
                    fetcher=fetcher,
                )
                course = Course.from_renderer(
                    renderer=renderer,
                    parent=self,
                    canonical=course_info.get('canonical', False),
                )
                self.add_course(course)
                feature_index = course_info.get('featured', None)
                if feature_index is not None:
                    featured_courses.append((feature_index, slug, course))
        # Sort featured courses by their index
        self.featured_courses = [c for i, s, c in sorted(featured_courses)]

    def add_course(self, course):
        slug = course.slug
        if slug in self.courses:
            # XXX: Replacing courses is untested
            old = self.courses[slug]
            if old.start_date:
                for year in range(old.start_date.year, old.end_date.year+1):
                    del self.run_years[year][slug]
            else:
                del self.self_study_courses[slug]

        self.courses[slug] = course
        if course.start_date:
            for year in range(course.start_date.year, course.end_date.year+1):
                if year not in self.run_years:
                    run_year = RunYear(year=year, parent=self)
                    self.run_years[year] = run_year
                self.run_years[year][slug] = course
        else:
            self.self_study_courses[slug] = course

    def freeze(self):
        for course in self.courses.values():
            course.freeze()

    def load_licenses(self, path):
        """Add licenses from files in the given path to the model"""
        for licence_path in path.iterdir():
            with (licence_path / 'info.yml').open() as f:
                info = yaml.safe_load(f)
            slug = licence_path.name
            license = load(
                License,
                {'api_version': [0, 0], 'license': info},
                parent=self, slug=slug,
            )
            self.licenses[slug] = license

    def get_course(self, slug):
        # XXX: RunYears shouldn't be necessary
        if slug == 'lessons':
            return self.courses[slug]
        year, identifier = slug.split('/')
        if year == 'courses':
            return self.courses[slug]
        else:
            return self.run_years[int(year)][slug]

    def get_pks(self):
        return {}

    def _url_for(self, obj_type, pks, url_type='web', *, external=False):
        try:
            urls = self.url_factories[url_type]
        except KeyError:
            raise NoURLType(url_type)
        if obj_type is None:
            obj_type = type(obj)
        try:
            url_for = urls[obj_type]
        except KeyError:
            raise NoURL(obj_type)
        return url_for(**pks, _external=external)
