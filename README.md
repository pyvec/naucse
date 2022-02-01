# naucse

This is a server for open course material.

To use it, you will need some content.
Usually, the repository with the content will require the `naucse` module,
and will run using `python -m naucse`.

We use content at https://github.com/pyvec/naucse.python.cz to generate
[naucse.python.cz](https://naucse.python.cz).


## Installation

Install from a virtual environment.

To install the latest release:

    (venv)$ python -m pip install naucse

To install from a cloned repository, for development:

    (venv)$ python -m pip install -e.[dev]


## Running

To run the serve, either change (`cd`) to the directory with content,
or set `NAUCSE_ROOT_PATH` to that directory.
Then run:

    (venv)$ python -m naucse serve

Instead of `serve`, you can run `freeze` to generate a static website.
See [Elsa](https://pypi.org/project/elsa/) for other usage, including
deployment to GitHub Pages.


## Served courses

The courses on the served website are taken from two sources:

- `courses.yml` in `$NAUCSE_ROOT_PATH`, with entries like:

  ```yaml
    course_slug:
        url: https://github.com/user/repo
        branch: main
        path: _compiled
  ```

  The named repositories will be cloned. At the given path in the given branch,
  naucse expects compiled course info, as prepared by
  `python -m naucse_render compile`.

  This is intended for the production site, which aggregates lots of individual
  courses.

  If `courses.yml` is present, naucse will use a pretty homepage
  (rather than listing all courses on the homepage).

- Any courses found by `python -m naucse_render ls`.
  This is useful when developing a course locally.


## Tests

Tests can be run using `tox`:

    (venv)$ tox

or `pytest` directly:

    (venv)$ python -m pytest


## Licence

The code is licensed under the terms of the MIT license, see [LICENSE.MIT] file
for full text. By contributing code to this repository, you agree to have it
licensed under the same license.

Content has its own license specified in the appropriate matadata.
Only [free content licenses] are used. By contributing to an already licensed
document, you agree to have it licensed under the same license.
(And feel free to add yourself to the authors list in its metadata.)
When contributing new document(s) a license must be specified in the metadata.

[LICENSE.MIT]: https://github.com/pyvec/naucse.python.cz/blob/master/LICENSE.MIT
[free content licenses]: https://en.wikipedia.org/wiki/List_of_free_content_licenses
