import pytest

from naucse import models

from test_naucse.conftest import assert_yaml_dump, API_VERSIONS


@pytest.mark.parametrize('version', API_VERSIONS)
@pytest.mark.parametrize('mode', ('in', 'out'))
@pytest.mark.parametrize(
    'cls', (models.Root, models.RunYear, models.Course))
def test_schema_unchanged(model, version, mode, cls):
    """Test that the API schema did not change"""
    schema = models.get_schema(
        cls, is_input=(mode == 'in'), version=version,
    )
    assert_yaml_dump(schema, f'schema/{cls.model_slug}-{version[0]}.{version[1]}-{mode}.json')
