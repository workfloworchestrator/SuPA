.. vim:noswapfile:nobackup:nowritebackup:
.. highlight:: console

Documentation
=============

SuPA's documentation is written using `Sphinx <https://www.sphinx-doc.org>`_.
To generate and read it,
run::

    % python setup.py build_sphinx
    % open build/sphinx/html/index.html

This assumes you have installed SuPA with the ``doc`` option.
See :doc:`installation` on how to do that.

The above Setuptools way of generation documentation
is probably only useful from a packaging point of view.
When working on the documentation
it is generally more convenient to generated it from directly from within the ``docs`` folder::

    % cd docs
    % make html
    % open _build/html/index.html

.. note::

    If ``make`` and/or ``open`` do not work on your OS,
    try ``gmake`` and/or ``xdg-open`` respectively.
    See also the relevant note in :doc:`installation`.

Semantic Line Breaks
--------------------

This documentation is written using `Semantic Line Breaks <https://sembr.org/>`_.
This allows for better diff generation
compared to documentation where lines are wrapped purely based on line length.

API Documentation
-----------------

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
--------------------

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
