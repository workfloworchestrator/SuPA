SuPA
====

SURFnet 8 ultimate Provider Agent.

An ultimate Provider Agent is an NSI Network Service Agent that services NSI requests by coordinating with a local
Network Resource Manager (NRM). In case of SURFnet 8 the NRM would be the Orchestrator.

Installation
------------

As we don't have an internal Python package repository, we need to check out the source code repository::

    $ git clone git@git.ia.surfsara.nl:automation/projects/supa.git

`SuPA` is developed using Python 3.7. Hence we need a Python 3.7 virtual environment::

    $ cd supa
    $ python3.7 -m venv venv
    $ source venv/bin/activate

The virtual environment created by the `venv` module does not always contain the most recent version of `pip`. As we
are using some newer Python packaging standards (`PEP-518 <https://www.python.org/dev/peps/pep-0518/>`_) it is
probably a good idea have `pip` updated to its most recent version::

    $ pip install -U pip

Depending on whether we want to install `SuPA` for deployment or development we either execute::

    $ pip install .

or::

    $ pip install -e '.[dev]'

If the latter fails during the installation of the `grpcio-tools` package, complaining about _No suitable threading
library available_, we can educate that package about the wonders of other operating systems than the big three by means
of prepending the `pip` command with `CFLAGS="-DHAVE_PTHREAD=1"`. At least, that is what makes it work on FreeBSD 12.1::

    $ CFLAGS="-DHAVE_PTHREAD=1" pip install -e '.[dev]'

The `dev` installation installs `SuPA` in editable mode. Meaning that changes to its code will be directly
active/available in the virtual environment it is installed in. It will also install the `pre-commit` package but that
still needs to activated by means of::

    $ pre-commit install

Development
-----------

Some rules:

- Use type annotations for all non-generated code
- All public functions should have `Google Style Docstrings <https://www.sphinx-doc.org/en/master/usage/extensions/example_google.html>`_
- Regularly run:
    - `mypy src/supa`
    - `flake8`
    - `pytest -n auto --cov`
- Each MR should probably result in a version bump (`VERSION.txt`) and an update to `CHANGES.rst`

Importing new protobuf/gRPC definitions
+++++++++++++++++++++++++++++++++++++++

When new NSI protobuf/gRPC definitions are imported into the `protos` directory one should (re)generated the
corresponding Python code for it::

    $ python setup.py gen_code

PyCharm
+++++++

Included is a shell script `fmt_code.sh` that can easily run `black` and `isort` in succession from PyCharm. There are
two options to use this script:

- Run it as an external tool with a keyboard shortcut assigned to it
- Configure a file watcher to have it run automatically on file save

As I tend to prefer the former I'll document it. Configuring as a file watcher should be very similar.

Go to:

- `File | Settings | Tools | External Tools`
- Click on the `+` icon
- Fill out the fields:
    - Name: `Black + isort`
    - Program: `$ProjectFileDir$/fmt_code.sh`
    - Arguments: `$JDKPath$ $FilePath$`
    - Output paths to refresh: `$FilePath$`
    - Working directory: `$ProjectFileDir$`
    - Untick option _Open console for tool output_
    - Click `OK`  (Edit Tool dialog)
    - Click `Apply` (Settings dialog)
- Still in the Setting dialog, go to `Keymap`
- In search field type: `Black + isort`
- Right click on the entry found and select `Add keyboard shortcut`
- Press `Ctrl + Alt + L`  (or whatever you deem convenient)
- Click `OK` (Keyboard Shortcut dialog)
- Click `OK` (Settings dialog)

Now if you reformat the Python module under development using `Ctrl + Alt + L` the Git pre-commit hook will not
complain about the layout of your code.
