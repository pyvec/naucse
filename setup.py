from pathlib import Path
from setuptools import setup

setup(
    name='naucse',
    version='0.2',
    description='Website for course materials',
    long_description=Path('README.md').read_text(),
    long_description_content_type='text/markdown',
    author='Petr Viktorin & others',
    author_email='encukou@gmail.com',
    license='MIT',
    license_files=['LICENSE.MIT'],
    url='https://github.com/pyvec/naucse',
    packages=['naucse'],
    install_requires=[
        'elsa',
        'ics',
        'python-dateutil',
        'arca[docker]',
        'cssutils',
        'PyYAML',
        'Flask',
        'Jinja2',
        'Werkzeug',
        'jsonschema',
        'lxml',
        'naucse-render',
        'mkepub',
        'beautifulsoup4',
    ],
    extras_require={
        'dev': ['tox', 'pytest'],
    },
    include_package_data=True,
    zip_safe=False,
)
