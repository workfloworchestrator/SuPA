SuPA
====

SURFnet 8 ultimate Provider Agent.

An ultimate Provider Agent is an NSI Network Service Agent
that services NSI requests by coordinating with a local Network Resource Manager (NRM).
In case of SURFnet 8,
the NRM would be the Orchestrator.

Installation
------------

As we don't have an internal Python package repository
we need to check out the source code repository::

    $ git clone git@git.ia.surfsara.nl:automation/projects/supa.git

SuPA is developed using Python 3.8.
Hence we need a Python 3.8 virtual environment::

    $ cd supa
    $ python3.8 -m venv venv
    $ source venv/bin/activate

Now we can install SuPA for development purposes::

    $ pip install -U pip wheel
    $ pip install -e '.[dev,doc]'

This README is intentionally kept as brief as possible.
Build the documentation and read that for much more info regarding
installation, configuration and development::

    $ cd docs
    $ make html
    $ open _build/html/index.html


Running
-------

With an activated virtual environment
running SuPA should be as easy as::

    $ supa serve

However, that will hardly do exactly what you want.
Best to read the documentation on how to configure SuPA first.

.. note::

    If you think the lines in this README file
    or other parts of the documentation are wrapped strangely,
    please remember that we use `Semantic Line Breaks <https://sembr.org/>`_
