import pytest
import yaml

from naucse.views import app

from test_naucse.conftest import fixture_path

@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv('NAUCSE_ROOT_PATH', fixture_path / 'test_content')

    app.config['DEBUG'] = True

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
    monkeypatch.setenv('NAUCSE_ROOT_PATH', tmp_path)

    rv = client.get('/')
    assert 'pohání weby i rakety'.encode() in rv.data
