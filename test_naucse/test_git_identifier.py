import re

import pytest
from hypothesis import given, example
from hypothesis.strategies import text

from naucse.compiled_renderer import git_identifer

# The variable names are case-insensitive -> use only lowercase.
# Allow only alphanumeric characters and -, and start with
# an alphabetic character
IDENTIFIER_RE = re.compile('^[a-z][a-z0-9-]*$')

@given(text())
def test_git_identifer_valid(text):
    result = git_identifer(text)
    assert IDENTIFIER_RE.match(result)


@given(text(), text())
@example('0', 'x0')  # regression test (these used to give the same result)
def test_git_identifers_different(text1, text2):
    """Identifiers from different strings must be different"""
    if text1 == text2:
        assert git_identifer(text1) == git_identifer(text2)
    else:
        assert git_identifer(text1) != git_identifer(text2)


@pytest.mark.parametrize(('input', 'output'), (
    ('simple', 'simple'),
    ('CaPiTaL', 'x-a-i-a--c43c50c54c4c'),
    ('→Fünny 😸 letters\0!', 'x---nny---letters---u2192c46cfcc20v0001f638c20c00c21'),
    ('yap://foo.bar/some-words_here/', 'yap---foo-bar-some-words-here--msspsdrs'),
))
def test_git_identifer_example(input, output):
    assert git_identifer(input) == output
