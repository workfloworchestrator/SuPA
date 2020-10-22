.. vim:noswapfile:nobackup:nowritebackup:
.. highlight:: console

Running
=======

Running SuPA is done by means of the ``supa`` command line utility.
When run without any options it displays help info.
Exactly as it would when run with the ``-h`` or ``--help`` options.
To do anything useful ``supa`` has subcommands.
An example of a subcommand is ``serve`` to start up the gRPC server::

    % supa serve

The subcommands of ``supa`` also accept options that modify their behaviour.
To get more information about those,
run the subcommands with either ``-h`` or ``--help`` options.
For instance::

    % supa serve --help

Configuration File
------------------

In addition to subcommand options,
``supa`` can be configured by means of a configurations file ``supa.env``.
Where this configuration file should live is dependent on how ``supa`` was installed
(regular or editable pip install).

When you start ``supa`` without any options it will display logging info
stating from what location it read or attempted to read ``supa.env``::

   % supa
   2020-09-10 09:14:19 [info     ] Using env file in source tree. path=/usr/home/guido/devel/surfnet/supa/supa.env

Generally speaking,
anything configurable in ``supa.env`` can be specified on the command with options supplied to the subcommands.

Environment Variables
---------------------

In addition to ``supa.env`` and command line options,
``supa`` will also honor settings by means of environment variables.
Regarding precedence:
command line options take precedence over environment variables,
that in turn,
take precedence over settings in ``supa.env``.
The following examples all achieve the same thing,
namely running the ``serve`` subcommand with 8 workers.

Using a command line option
(mind the dashes in option names instead of underscores)::

    % supa serve --max-workers=8

Using an environment variable
(mind the underscores in environment variable names instead of dashes)::

    % grpc_max_workers=8 supa serve

Using a setting in ``supa.env``
(set ``grpc_max_workers`` from ``6`` to ``8``)::

    % sed -i '' 's/^#\(grpc_max_workers=\)6$/\18/' supa.env
    % supa serve

.. note::

    The ``sed`` command is not how one would normally change the number of workers in ``supa.env``.
    However, for documentation purposes
    it helps to have something that can be executed by copy and pasting.
