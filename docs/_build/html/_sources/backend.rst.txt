.. vim:noswapfile:nobackup:nowritebackup:
.. highlight:: console

Backend
=======

SuPA uses a plugable backend interface to communicate with different NRMs or network elements.
Please refer to the API documentation on :ref:`supa.nrm.backend` for more details.
At a minimum the ``activate()`` and ``deactivate()`` methods of the backend should be implemented,
and optionally the ``topology()`` method to automate topology updates.
If the backend interfaces to a NRM that also can reserve network resource,
any of the other backend methods,
that match the NSI primitives,
like ``reserve()`` and ``reserve_commit()``,
can be implemented.


Backends are just regular Python modules.
The name of the module to be used as backend can be specified with the ``backend`` configuration option,
without the ``.py`` file extention of course.
Just make sure that the the python module can be found somewhere on the `PYTHONPATH <https://docs.python.org/3/using/cmdline.html\#envvar-PYTHONPATH>`_.