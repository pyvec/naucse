import elsa

from naucse.views import app


def main():
    elsa.cli(app, base_url='https://naucse.python.cz')
