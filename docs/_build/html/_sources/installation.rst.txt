.. vim:noswapfile:nobackup:nowritebackup:
.. highlight:: console

Installation
============

As we don't have an internal Python package repository,
we need to check out the source code repository::

    % git clone git@git.ia.surfsara.nl:automation/projects/supa.git

SuPA is developed using Python 3.8.
Hence we need a Python 3.8 virtual environment::

    % cd supa
    % python3.8 -m venv venv
    % source venv/bin/activate

The virtual environment created by the ``venv`` module does not always contain the most recent version of ``pip``.
As we are using some newer Python packaging standards (`PEP-518 <https://www.python.org/dev/peps/pep-0518/>`_)
it is probably a good idea have ``pip`` updated to its most recent version::

    % pip install -U pip wheel

We are including ``wheel`` as we will be building or using pre-built C++ extensions.

Depending on whether we want to install SuPA for deployment or development,
we either execute::

    % pip install .

or::

    % pip install -e '.[dev]'

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
