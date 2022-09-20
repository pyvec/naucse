import elsa

from naucse.views import make_app


def main():
    elsa.cli(make_app(), base_url='https://naucse.python.cz')
