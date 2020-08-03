import datetime
from pathlib import Path
import functools
import calendar
import os

from flask import Flask, render_template, jsonify, url_for, Response, abort, g, redirect
from flask import send_from_directory
import ics
from arca import Arca

from naucse import models
from naucse.urlconverters import register_url_converters
from naucse.templates import setup_jinja_env

import mkepub
from bs4 import BeautifulSoup


app = Flask('naucse')
app.config['JSON_AS_ASCII'] = False


@app.before_request
def _get_model():
    """Set `g.model` to the root of the naucse model

    A single model is used (and stored in app config).

    In debug mode (elsa serve), the model is re-initialized for each request,
    so changes are picked up.

    In non-debug mode (elsa freeze), the model is initialized once, and
    frozen (so all course data is requested and rendered upfront).
    """
    freezing = os.environ.get('NAUCSE_FREEZE', not app.config['DEBUG'])
    initialize = True

    try:
        g.model = app.config['NAUCSE_MODEL']
    except KeyError:
        g.model = init_model()
        app.config['NAUCSE_MODEL'] = g.model
    else:
        if freezing:
            # Model already initialized; don't look for changes
            return

    # (Re-)initialize model

    load_path = Path(os.environ.get('NAUCSE_ROOT_PATH', '.'))

    g.model.load_licenses(Path(app.root_path) / 'licenses')
    g.model.load_local_courses(load_path)

    if freezing:
        g.model.freeze()


def init_model():
    trusted = os.environ.get('NAUCSE_TRUSTED_REPOS', None)
    if trusted is None:
        trusted_repo_patterns = ()
    else:
        trusted_repo_patterns = tuple(
            line for line in trusted.split() if line
        )
    return models.Root(
        url_factories={
            'api': {
                models.Root: lambda **kw: url_for('api', **kw),
                models.Course: lambda **kw: url_for('course_api', **kw),
                models.RunYear: lambda **kw: url_for('run_year_api', **kw),
            },
            'web': {
                models.Lesson: lambda **kw: url_for('page',
                    page_slug='index', **kw),
                models.Page: lambda **kw: url_for('page', **kw),
                models.Solution: lambda **kw: url_for('solution', **kw),
                models.Course: lambda **kw: url_for('course', **kw),
                models.Session: lambda **kw: url_for('session', **kw),
                models.SessionPage: lambda **kw: url_for(
                    'session', **kw),
                models.StaticFile: lambda **kw: url_for('page_static', **kw),
                models.Root: lambda **kw: url_for('index', **kw)
            },
        },
        schema_url_factory=lambda m, is_input, **kw: url_for(
            'schema', model_slug=m.model_slug,
            is_input=is_input, **kw),
        arca=Arca(settings={
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
        }),
        trusted_repo_patterns=trusted_repo_patterns,
    )


register_url_converters(app)
setup_jinja_env(app.jinja_env)


@app.route('/')
def index():
    return render_template("index.html", edit_info=g.model.edit_info)


@app.route('/courses/')
def courses():
    return render_template(
        "course_list.html",
        featured_courses=g.model.featured_courses,
        edit_info=g.model.course_edit_info,
    )


@app.route('/runs/')
@app.route('/<int:year>/')
@app.route('/runs/<any(all):all>/')
def runs(year=None, all=None):
    # XXX: Simplify?
    today = datetime.date.today()

    # List of years to show in the pagination
    # If the current year is not there (no runs that start in the current year
    # yet), add it manually
    all_years = sorted(g.model.explicit_run_years)
    if today.year not in all_years:
        all_years.append(today.year)
    first_year, last_year = min(all_years), max(all_years)

    if year is not None:
        if year > last_year:
            # Instead of showing a future year, redirect to the 'Current' page
            return redirect(url_for('runs'))
        if year not in all_years:
            # Otherwise, if there are no runs in requested year, return 404.
            abort(404)

    if all is not None:
        run_data = {}
        courses = g.model.courses
        for slug, course in g.model.courses.items():
            if course.start_date:
                run_data.setdefault(course.start_date.year, {})[slug] = course

        paginate_prev = {'year': first_year}
        paginate_next = {'all': 'all'}
    elif year is None:
        # Show runs that are either ongoing or ended in the last 3 months
        runs = {**g.model.run_years.get(today.year, {}),
                **g.model.run_years.get(today.year - 1, {})}
        ongoing = {slug: run for slug, run in runs.items()
                   if run.end_date >= today}
        cutoff = today - datetime.timedelta(days=3*31)
        recent = {slug: run for slug, run in runs.items()
                  if today > run.end_date > cutoff}
        run_data = {"ongoing": ongoing, "recent": recent}

        paginate_prev = {'year': None}
        paginate_next = {'year': last_year}
    else:
        run_data = {year: g.model.run_years.get(year, {})}

        past_years = [y for y in all_years if y < year]
        if past_years:
            paginate_next = {'year': max(past_years)}
        else:
            paginate_next = {'all': 'all'}

        future_years = [y for y in all_years if y > year]
        if future_years:
            paginate_prev = {'year': min(future_years)}
        else:
            paginate_prev = {'year': None}

    return render_template(
        "run_list.html",
        run_data=run_data,
        today=datetime.date.today(),
        year=year,
        all=all,
        all_years=all_years,
        paginate_next=paginate_next,
        paginate_prev=paginate_prev,
        edit_info=g.model.runs_edit_info,
    )


@app.route('/<course:course_slug>/')
def course(course_slug, year=None):
    try:
        course = g.model.courses[course_slug]
    except KeyError:
        print(g.model.courses)
        abort(404)

    recent_runs = course.get_recent_derived_runs()

    return render_template(
        "course.html",
        course=course,
        recent_runs=recent_runs,
        edit_info=course.edit_info,
    )

@app.route('/<course:course_slug>.epub')
def course_as_epub(course_slug, year=None):
    try:
        course = g.model.courses[course_slug]
    except KeyError:
        print(g.model.courses)
        abort(404)

    # logger.debug(course.base_path)

    img_counter = 1

    epub_path = str(course.base_path) + '/' + course.slug + '.epub'

    if (os.path.exists(epub_path)):
        os.remove(epub_path)

    epub_course = mkepub.Book(course.title, language='cs')

    course_url =  'file://' + str(course.base_path)

    for session_slug in course.sessions:
        session = course.sessions[session_slug]
        head_chapter = epub_course.add_page(session.title or 'title', '<head/>')

        for material in [material for material in session.materials if material.type == 'lesson']:
            lesson = material.lesson
            is_canonical_lesson, canonical_url = _get_canonicality_info(lesson)

            page = lesson.pages['index']

            lesson_chapter_html_raw = render_template(
                                "lesson.html",
                                page=page,
                                content=page.content,
                                course=course,
                                canonical_url=canonical_url,
                                is_canonical_lesson=is_canonical_lesson,
                                page_attribution=page.attribution,
                                edit_info=page.edit_info,
                                is_epub=True,
                            )


            # je nutné upravit adresy img
            chap_tree = BeautifulSoup(lesson_chapter_html_raw, 'html.parser')

            sols = chap_tree.find_all('div', class_='solution')
            for sol in sols:
                sol.decompose()

            images = chap_tree.find_all('img')
            for image in images:
                img_base_name = os.path.basename(image['src'])
                static = lesson.static_files[img_base_name]
                image_path = static.path

                image_ext = os.path.splitext(image_path)[1]
                image_in_epub = '%05d.%s' % (img_counter, image_ext)
                img_counter = img_counter + 1

                # logger.debug(image_path)

                image['src'] = 'images/%s' % image_in_epub

                with open(image_path, 'rb') as img:
                    epub_course.add_image(image_in_epub, img.read())

            lesson_chapter_html = str(chap_tree)

            epub_course.add_page(material.title or 'bez titulu',
                    lesson_chapter_html,
                    parent = head_chapter)

    epub_course.save(str(course.base_path) +  '/' + course.slug + '.epub')

    return send_from_directory(course.base_path, course.slug + '.epub', cache_timeout = 0)


@app.route('/<course:course_slug>/sessions/<session_slug>/',
              defaults={'page_slug': 'front'})
@app.route('/<course:course_slug>/sessions/<session_slug>/<page_slug>/')
def session(course_slug, session_slug, page_slug):
    try:
        course = g.model.courses[course_slug]
        session = course.sessions[session_slug]
        page = session.pages[page_slug]
    except KeyError:
        abort(404)

    template = {
        'front': 'coverpage.html',
        'back': 'backpage.html',
    }[page.slug]

    materials_by_type = {}
    for material in session.materials:
        materials_by_type.setdefault(material.type, []).append(material)

    return render_template(
        template,
        session=session,
        course=session.course,
        edit_info=session.edit_info,
        materials_by_type=materials_by_type,
        page=page,
    )


def _get_canonicality_info(lesson):
    """Get canonical URL -- i.e., a lesson from 'lessons' with the same slug"""
    # XXX: This could be made much more fancy
    lessons_course = g.model.get_course('lessons')
    is_canonical_lesson = (lessons_course == lesson.course)
    if is_canonical_lesson:
        canonical_url = None
    else:
        if lessons_course._has_lesson(lesson.slug):
            canonical = lessons_course.lessons[lesson.slug]
            canonical_url = canonical.get_url(external=True)
        else:
            canonical_url = None
    return is_canonical_lesson, canonical_url


@app.route('/<course:course_slug>/<lesson:lesson_slug>/',
              defaults={'page_slug': 'index'})
@app.route('/<course:course_slug>/<lesson:lesson_slug>/<page_slug>/')
def page(course_slug, lesson_slug, page_slug='index'):
    try:
        course = g.model.courses[course_slug]
        lesson = course.lessons[lesson_slug]
        page = lesson.pages[page_slug]
    except KeyError:
        raise abort(404)

    is_canonical_lesson, canonical_url = _get_canonicality_info(lesson)

    return render_template(
        "lesson.html",
        page=page,
        content=page.content,
        course=course,
        canonical_url=canonical_url,
        is_canonical_lesson=is_canonical_lesson,
        page_attribution=page.attribution,
        edit_info=page.edit_info,
    )


@app.route('/<course:course_slug>/<lesson:lesson_slug>/<page_slug>'
              + '/solutions/<int:solution_index>/')
def solution(course_slug, lesson_slug, page_slug, solution_index):
    try:
        course = g.model.courses[course_slug]
        lesson = course.lessons[lesson_slug]
        page = lesson.pages[page_slug]
        solution = page.solutions[solution_index]
    except KeyError:
        raise abort(404)

    is_canonical_lesson, canonical_url = _get_canonicality_info(lesson)

    return render_template(
        "lesson.html",
        page=page,
        content=solution.content,
        course=course,
        canonical_url=canonical_url,
        is_canonical_lesson=is_canonical_lesson,
        page_attribution=page.attribution,
        edit_info=page.edit_info,
        solution=solution,
    )


@app.route('/<course:course_slug>/<lesson:lesson_slug>/static/<path:filename>')
def page_static(course_slug, lesson_slug, filename):
    try:
        course = g.model.courses[course_slug]
        lesson = course.lessons[lesson_slug]
        static = lesson.static_files[filename]
    except KeyError:
        raise abort(404)

    print('sending', static.base_path, static.filename)
    return send_from_directory(static.base_path, static.path)


def list_months(start_date, end_date):
    """Return a span of months as a list of (year, month) tuples

    The months of start_date and end_date are both included.
    """
    months = []
    year = start_date.year
    month = start_date.month
    while (year, month) <= (end_date.year, end_date.month):
        months.append((year, month))
        month += 1
        if month > 12:
            month = 1
            year += 1
    return months


@app.route('/<course:course_slug>/calendar/')
def course_calendar(course_slug):
    try:
        course = g.model.courses[course_slug]
    except KeyError:
        abort(404)

    if not course.start_date:
        abort(404)

    sessions_by_date = {
        s.date: s for s in course.sessions.values()
        if hasattr(s, 'date')
    }

    return render_template(
        'course_calendar.html',
        course=course,
        sessions_by_date=sessions_by_date,
        months=list_months(course.start_date, course.end_date),
        calendar=calendar.Calendar(),
        edit_info=course.edit_info,
    )


@app.route('/<course:course_slug>/calendar.ics')
def course_calendar_ics(course_slug):
    try:
        course = g.model.courses[course_slug]
    except KeyError:
        abort(404)

    if not course.start_date:
        abort(404)

    events = []
    for session in course.sessions.values():
        time = getattr(session, 'time', None)
        if time is None:
            # Sessions without times don't show up in the calendar
            continue

        created = os.environ.get('NAUCSE_CALENDAR_DTSTAMP', None)
        cal_event = ics.Event(
            name=session.title,
            begin=time['start'],
            end=time['end'],
            uid=session.get_url(external=True),
            created=created,
        )
        events.append(cal_event)

    cal = ics.Calendar(events=events)
    return Response(str(cal), mimetype="text/calendar")


@app.route('/v0/schema/<is_input:is_input>.json', defaults={'model_slug': 'root'})
@app.route('/v0/schema/<is_input:is_input>/<model_slug>.json')
def schema(model_slug, is_input):
    try:
        cls = models.models[model_slug]
    except KeyError:
        abort(404)
    return jsonify(models.get_schema(
        cls, is_input=is_input, version=models.API_VERSION,
    ))


@app.route('/v0/naucse.json')
def api():
    return jsonify(models.dump(g.model, version=models.API_VERSION))


@app.route('/v0/years/<int:year>.json')
def run_year_api(year):
    try:
        run_year = g.model.run_years[year]
    except KeyError:
        abort(404)
    return jsonify(models.dump(run_year, version=models.API_VERSION))


@app.route('/v0/<course:course_slug>.json')
def course_api(course_slug):
    try:
        course = g.model.courses[course_slug]
    except KeyError:
        abort(404)
    return jsonify(models.dump(course, version=models.API_VERSION))
