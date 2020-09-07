SuPA
====

SURFnet 8 ultimate Provider Agent.

An ultimate Provider Agent is an NSI Network Service Agent that services NSI requests by coordinating with a local
Network Resource Manager (NRM). In case of SURFnet 8 the NRM would be the Orchestrator.

Installation
------------

As we don't have an internal Python package repository, we need to check out the source code repository::

    $ git clone git@git.ia.surfsara.nl:automation/projects/supa.git

SuPA is developed using Python 3.8. Hence we need a Python 3.8 virtual environment::

    $ cd supa
    $ python3.8 -m venv venv
    $ source venv/bin/activate

The virtual environment created by the ``venv`` module does not always contain the most recent version of ``pip``. As we
are using some newer Python packaging standards (`PEP-518 <https://www.python.org/dev/peps/pep-0518/>`_) it is probably
a good idea have ``pip`` updated to its most recent version::

    $ pip install -U pip wheel

Depending on whether we want to install SuPA for deployment or development we either execute::

    $ pip install .

or::

    $ pip install -e '.[dev]'

If the latter fails during the installation of the ``grpcio-tools`` package, complaining about
*No suitable threading library available*, we can educate that package about the wonders of other operating systems
than the big three by means of prepending the ``pip`` command with ``CFLAGS="-DHAVE_PTHREAD=1"``. At least, that is
what makes it work on FreeBSD 12.1::

    $ CFLAGS="-DHAVE_PTHREAD=1" pip install -e '.[dev]'

The ``dev`` installation, by virtue of the ``-e`` option, installs SuPA in editable mode. Meaning that changes to
its code will be directly active/available in the virtual environment it is installed in. It will also install the
``pre-commit`` package but that still needs to activated by means of::

    $ pre-commit install

Another installation option is ``doc``. This can be combined with the ``dev`` installation option as follows::

    $ pip install -e '.[dev,doc]'

It installs the Sphinx documentation package that allows the documentation in the ``docs`` directory to be build,
generating nicely formatted HTML output::

    $ cd docs
    $ make html

The ``Makefile`` uses GNU Make syntax, hence on FreeBSD the build command should be ``gmake docs``.

Tips
++++

Pre-built packages for ``grpcio`` and ``grpcio-tools`` might not be available for all platforms. Meaning that these
packages will be built when ``pip`` installs SuPA. As these packages use a lot of C++ code, building them can take a
long time.

With a recent enough versions of ``pip`` and ``wheel`` installed, ``pip`` caches the packages it builds. Hence on
subsequent installs in new or recreated virtual environments it can skip the building part and install the previously
built packages from the cache. To see ``pip``'s cache run::

    pip cache list

However on OS or Python updates, eg from FreeBSD 12.1-p5 to 12.1-p6, or from Python 3.7 to 3.8, ``pip`` will rebuild the
packages as their names include the OS name and version down to the patch level and the version of Python used. Eg.
``grpcio-1.29.0-cp37-cp37m-freebsd_12_1_RELEASE_p5_amd64.whl`` will not picked for an installation of FreeBSD 12.1-p6 or
when used with Python 3.8.

To speed up builds under these circumstances, consider always using `ccache <https://ccache.dev/>`_. With ``ccache``
installed, *always* execute the installation of SuPA by ``pip`` with::

    CC="ccache cc" pip install -e '.[dev]'

if your primary C/C++ compiler is LLVM, or::

    CC="ccache gcc" pip install -e '.[dev]'

if your primary C/C++ compiler is GCC

To see the ``ccache`` cache, run::

   ccache -s

Documentation
-------------

SuPA's documentation is written using `Sphinx <https://www.sphinx-doc.org>_`. To
generate, it run::

    $ python setup.py build_sphinx

Development
-----------

Some rules:

- Use type annotations for all non-generated code
- All public functions should have `Google Style Docstrings <https://www.sphinx-doc.org/en/master/usage/extensions/example_google.html>`_
- Regularly run:
    - ``mypy src/supa``
    - ``flake8``
    - ``pytest -n auto --cov``
- Each MR should probably result in a version bump (``VERSION.txt``) and an update to ``CHANGES.rst``

Importing new protobuf/gRPC definitions
+++++++++++++++++++++++++++++++++++++++

When new NSI protobuf/gRPC definitions are imported into the ``protos`` directory one should (re)generated the
corresponding Python code for it::

    $ python setup.py clean gen_code

Cleaning the previously generated code is a good thing thing. We want to ensure that we don't accidentally depend on no
longer used protobuf/gRPC definitions. Hence always run the ``gen_code`` in conjunction with and prepended by the
``clean`` command.


PyCharm
+++++++

Included is a shell script ``fmt_code.sh`` that can easily run ``black`` and ``isort`` in succession from PyCharm. There
are two options to use this script:

- Run it as an external tool with a keyboard shortcut assigned to it
- Configure a file watcher to have it run automatically on file save

As I tend to prefer the former I'll document it. Configuring as a file watcher should be very similar.

Go to:

- ``File | Settings | Tools | External Tools``
- Click on the ``+`` icon
- Fill out the fields:
    - Name: ``Black + isort``
    - Program: ``$ProjectFileDir$/fmt_code.sh``
    - Arguments: ``$JDKPath$ $FilePath$``
    - Output paths to refresh: ``$FilePath$``
    - Working directory: ``$ProjectFileDir$``
    - Untick option *Open console for tool output*
    - Click ``OK``  (Edit Tool dialog)
    - Click ``Apply`` (Settings dialog)
- Still in the Setting dialog, go to ``Keymap``
- In search field type: ``Black + isort``
- Right click on the entry found and select ``Add keyboard shortcut``
- Press ``Ctrl + Alt + L``  (or whatever you deem convenient)
- Click ``OK`` (Keyboard Shortcut dialog)
- Click ``OK`` (Settings dialog)

Now if you reformat the Python module under development using ``Ctrl + Alt + L`` the Git pre-commit hook will not
complain about the layout of your code.

Running
-------

Running SuPA is done by means of the ``supa`` command line utility. When run without any options it displays help
info.  Exactly as it would when run with the ``-h`` or ``--help`` options. To do anything useful ``supa`` has
subcommands. An example of a subcommand is ``serve`` to start up the gRPC server::

    $ supa serve

The subcommands of ``supa`` also accept options that modify their behaviour. To get more information about those, run
the subcommands with either ``-h`` or ``--help`` options. For instance::

    $ supa serve --help

In addition to subcommand options, ``supa`` can be configured by means of a configurations file ``supa.env``.  Where
this configuration file should live is dependent on how ``supa`` was installed (regular or editable pip install).  When
you start ``supa`` without any options it will display logging info stating from what location it read or attempted to
read ``supa.env``. Generally speaking anything configurable in ``supa.env`` can be specified on the command with options
supplied to the subcommands.

In addition to ``supa.env`` and command line options, ``supa`` will also honor settings by means of environment
variables.  Regarding precedence: command line options take precedence over environment variables, that in turn, take
precedence over settings in ``supa.env``. The following examples all achieve the same thing, namely running the
``serve`` subcommand with 16 workers.

Using a command line option (mind the dashes in option names instead of underscores)::

    $ supa serve --max-workers=16

Using an environment variable (mind the underscores in environment variable names instead of dashes)::

    $ max_workers=16 supa serve

Using a setting in ``supa.env`` (set ``max_workers`` from ``10`` to ``16``)::

    $ sed -i '' 's/^#\(max_workers=\)10$/\116/' supa.env
    $ supa serve
