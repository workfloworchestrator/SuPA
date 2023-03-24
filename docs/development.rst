.. vim:noswapfile:nobackup:nowritebackup:
.. highlight:: console

Development
===========

Install development environment
-------------------------------

Install development environment::

    pip install -e '.[dev]'

If the latter fails during the installation of the ``grpcio-tools`` package,
complaining about *No suitable threading library available*,
we can educate that package about the wonders of other operating systems than the big three
by means of prepending the ``pip`` command with ``CFLAGS="-DHAVE_PTHREAD=1"``.
At least, that is what makes it work on FreeBSD 12.1::

    % CFLAGS="-DHAVE_PTHREAD=1" pip install -e '.[dev]'

The ``dev`` installation,
by virtue of the ``-e`` option,
installs SuPA in editable mode.
Meaning that changes to its code will be directly active/available in the virtual environment it is installed in.
It will also install the ``pre-commit`` package,
but that still needs to activated by means of::

    % pre-commit install

Another installation option is ``doc``.
This can be combined with the ``dev`` installation option as follows::

    % pip install -e '.[dev,doc]'

It installs the Sphinx documentation package
that allows the documentation in the ``docs`` directory to be build,
generating nicely formatted HTML output::

    % cd docs
    % make html
    % open _build/html/index.html

.. note::

    The ``Makefile`` uses GNU Make syntax,
    hence on FreeBSD one should use ``gmake``.
    Although, you might need to do a ``sudo pkg install gmake`` first to get it installed.
    The ``open`` command is MacOS specific;
    on FreeBSD and Linux this should be ``xdg-open``

Documentation can also be build by Setuptools.
From the root of the repository execute::

    % python setup.py build_sphinx

When using Setuptools to build the Sphinx based documentation,
the resulting artifacts end up in ``build/sphinx/html``
instead of ``docs/_build/html``.

Tips
++++

Pre-built packages for ``grpcio`` and ``grpcio-tools`` might not be available for all platforms.
Meaning that these packages will be built when ``pip`` installs SuPA.
As these packages use a lot of C++ code,
building them can take a long time.

With a recent enough versions of ``pip`` and ``wheel`` installed,
``pip`` caches the packages it builds.
Hence on subsequent installs in new or recreated virtual environments
it can skip the building part
and install the previously built packages from the cache.
To see ``pip``'s cache run::

    % pip cache list

However on OS or Python updates,
eg from FreeBSD 12.1-p5 to 12.1-p6,
or from Python 3.7 to 3.8,
``pip`` will rebuild the packages
as their names include the OS name and version down to the patch level and the version of Python used.
Eg. ``grpcio-1.29.0-cp37-cp37m-freebsd_12_1_RELEASE_p5_amd64.whl`` will not picked for an installation of FreeBSD 12.1-p6
or when used with Python 3.8.

To speed up builds under these circumstances,
consider always using `ccache <https://ccache.dev/>`_.
With ``ccache`` installed,
*always* execute the installation of SuPA by ``pip`` with::

    % CC="ccache cc" pip install -e '.[dev]'

if your primary C/C++ compiler is LLVM, or::

    % CC="ccache gcc" pip install -e '.[dev]'

if your primary C/C++ compiler is GCC

To see the ``ccache``'s cache, run::

    % ccache -s


Some rules
----------

- Use type annotations for all non-generated code
- All public functions should have `Google Style Docstrings <https://www.sphinx-doc.org/en/master/usage/extensions/example_google.html>`_
- Regularly run:
    - ``mypy src/supa``
    - ``flake8``
    - ``pytest -n auto --cov``
    - ``pytest --doctest-module src``
- Each MR should probably result in a version bump (``VERSION.txt``)
  and an update to ``CHANGES.rst``

Importing new protobuf/gRPC definitions
---------------------------------------

When new NSI protobuf/gRPC definitions are imported into the ``protos`` directory
one should (re)generated the corresponding Python code for it::

    % python setup.py clean gen_code

.. note::

    Cleaning the previously generated code is a good thing thing.
    We want to ensure that we don't accidentally depend on no longer used protobuf/gRPC definitions.
    Hence always run the ``gen_code`` in conjunction with
    and prepended by the ``clean`` command.


PyCharm
-------

Included is a shell script ``fmt_code.sh``
that can easily run ``black`` and ``isort`` in succession from within PyCharm.
There are two options to use this script:

- Run it as an external tool with a keyboard shortcut assigned to it
- Configure a file watcher to have it run automatically on file save

Configuring it as an external tool is detailed below.
Configuring as a file watcher should be very similar.

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

If you regularly reformat the Python module under development using ``Ctrl + Alt + L``,
the Git pre-commit hook will notcomplain about the layout of your code.

.. vim:noswapfile:nobackup:nowritebackup:
.. highlight:: console

Documentation
-------------

SuPA's documentation is written using `Sphinx <https://www.sphinx-doc.org>`_.
To generate and read it,
run::

    % python setup.py build_sphinx
    % open build/sphinx/html/index.html

This assumes you have installed SuPA with the ``doc`` option.
See :doc:`installation` on how to do that.

.. note::

    The above Setuptools way of generation documentation
    is probably only useful from a packaging point of view.

When working on the documentation
it is generally more convenient to generated it
using the Sphinx provided Makefile::

    % make -C docs html
    % open docs/_build/html/index.html

.. note::

    If ``make`` and/or ``open`` do not work on your OS,
    try ``gmake`` and/or ``xdg-open`` respectively.
    See also the relevant note in :doc:`installation`.

Semantic Line Breaks
++++++++++++++++++++

This documentation is written using `Semantic Line Breaks <https://sembr.org/>`_.
This allows for better diff generation
compared to documentation where lines are wrapped purely based on line length.

API Documentation
+++++++++++++++++

Be sure to document all modules,
classes,
methods
and functions
with appropriate docstrings.
When done correctly,
these docstrings can easily be made part of the Sphinx based documention
by carefully inserting the appropriate
`autodoc <https://www.sphinx-doc.org/en/master/usage/extensions/autodoc.html#module-sphinx.ext.autodoc>`_
directives in :doc:`api`

Build while Editting
++++++++++++++++++++

You might have wondered what the line:

.. code-block:: rst

   .. vim:noswapfile:nobackup:nowritebackup:

at the top of each reStructuredText file does.
It turns off Vim's specific way of writing files,
so that files are updated inplace.
This ensures that only one filesystem event per file save is generated.
That in turn, allows the Python script ``watchmedo`` to work efficiently.

``watchmedo`` is part of the Python package `watchdog <https://pypi.org/project/watchdog/>`_.
It allows for monitoring of filesystem events
and executing commands in response to them.
The following command,
when executed in the project root directory::

    % watchmedo shell-command \
        --patterns="*.rst;*.py" --recursive \
        --command='echo "${watch_src_path}"; make -C docs html' \
        --wait .

watches for changes made to documentation files and source code,
and rebuilds everything in response.

Having Vim generate only one filesystem event per file save
(instead of two)
is important to prevent kicking of the documention build multiple times.
