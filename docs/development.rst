.. vim:noswapfile:nobackup:nowritebackup:
.. highlight:: console

Development
===========

Some rules:

- Use type annotations for all non-generated code
- All public functions should have `Google Style Docstrings <https://www.sphinx-doc.org/en/master/usage/extensions/example_google.html>`_
- Regularly run:
    - ``mypy src/supa``
    - ``flake8``
    - ``pytest -n auto --cov``
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
