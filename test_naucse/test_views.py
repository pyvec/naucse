import pytest
import yaml

from naucse.views import make_app

from test_naucse.conftest import fixture_path, setup_repo

@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv('NAUCSE_ROOT_PATH', str(fixture_path / 'test_content'))

    app = make_app()

    # Make debugging easier
    app.config['DEBUG'] = True
    app.config['TRAP_HTTP_EXCEPTIONS'] = True

    with app.test_client() as client:
        yield client


def test_dev_homepage(client):
    """Test the list of courses appears if no `courses.yml` is present."""

    rv = client.get('/')
    assert b'normal-course' in rv.data


def test_main_homepage(client, tmp_path, monkeypatch):
    """Test the main homepage appears if `courses.yml` is present."""

    with (tmp_path / 'courses.yml').open('w') as f:
        yaml.dump({}, f)
    monkeypatch.setenv('NAUCSE_ROOT_PATH', str(tmp_path))

    rv = client.get('/')
    assert 'pohání weby i rakety'.encode() in rv.data

@pytest.mark.parametrize(
    ('url', 'expected_part'),
    [
        ('/', 'pohání weby i rakety'),
        ('/courses/', 'g'),
    ]
)
def test_compiled_course(client, tmp_path, monkeypatch, url, expected_part):
    """Test the main homepage appears if `courses.yml` is present."""

    repo_path = tmp_path / 'repo'
    setup_repo(fixture_path / 'compiled-course', repo_path, branch='main')

    with (tmp_path / 'courses.yml').open('w') as f:
        yaml.dump({'compiled': {
            'url': repo_path.as_uri(),
            'branch': 'main',
        }}, f)
    monkeypatch.setenv('NAUCSE_ROOT_PATH', str(tmp_path))

    rv = client.get(url)
    assert expected_part in rv.data.decode()


@pytest.mark.parametrize(
    ('url', 'expected_part'),
    [
        ('/', 'Kurzy nalezené'),
        ('/course/+default/', 'top-level course'),
        ('/course/+default/sessions/test-session/', 'Test lesson'),
        ('/course/+default/test/test/', 'Main page'),
        ('/course/+default/test/test/sub/', 'Subpage'),
        ('/course/+default/test/test/static/circle.svg', '</svg>'),
        ('/2000/run-with-times/', 'Test run with scheduled times'),
        ('/2000/run-without-times/', 'A normal lesson'),
        ('/course/normal-course/', 'plain vanilla'),
    ]
)
def test_course_pages(client, tmp_path, monkeypatch, url, expected_part):
    """Test pages of a default course are rendered."""
    rv = client.get(url)
    assert expected_part in rv.data.decode()
