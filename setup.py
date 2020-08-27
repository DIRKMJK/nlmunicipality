import pathlib
from setuptools import setup

HERE = pathlib.Path(__file__).parent
README = (HERE / "README.md").read_text()


setup(name='nlmunicipality',
    version='0.0.0',
    description='Guess official municipality name from user-provided location name',
    long_description=README,
    long_description_content_type="text/markdown",
    author='dirkmjk',
    author_email='info@dirkmjk.nl',
    url='https://github.com/DIRKMJK/nlmunicipality',
    license="MIT",
    packages=['nlmunicipality'],
    install_requires=['pandas', 'requests', 'cbsodata', 'fuzzywuzzy', 'bs4'],
    zip_safe=False)
