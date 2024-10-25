from setuptools import setup

setup(
    name = "pocket", # pip install pocket
    description = "api wrapper for getpocket.com",
    #long_description=open('README.md', 'rt').read(),

    # version
    # third part for minor release
    # second when api changes
    # first when it becomes stable someday
    version = "0.3.7",
    author = 'Tapan Pandita',
    author_email = "tapan.pandita@gmail.com",

    url = 'http://github.com/tapanpandita/pocket/',
    license = 'BSD',

    # as a practice no need to hard code version unless you know program wont
    # work unless the specific versions are used
    install_requires = ["requests>=2.32.3"],

    py_modules = ["pocket"],

    zip_safe = True,
)

# TODO: Do all this and delete these lines
# register: Create an accnt on pypi, store your credentials in ~/.pypirc:
#
# [pypirc]
# servers =
#     pypi
#
# [server-login]
# username:<username>
# password:<pass>
#
# $ python setup.py register # one time only, will create pypi page for pocket
# $ python setup.py sdist --formats=gztar,zip upload # create a new release
#
