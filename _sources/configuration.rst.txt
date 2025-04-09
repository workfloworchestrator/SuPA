.. vim:noswapfile:nobackup:nowritebackup:
.. highlight:: console

Configuration
=============

Overview
--------

The SuPA NSI gRPC interface is not (yet) standardised,
and there are not many NSI NSA out there that implement that interface,
that is why SuPA is usually deployed with the transparent NSI SOAP to gRPC proxy PolyNSI,
like is shown in the image below.

.. image:: images/SuPA\ and\ PolyNSI\ setup.png

In this setup it is PolyNSI that faces the NSI uRA,
that is why parts of configuration of the uPA are applied to PolyNSI instead of SuPA itself.
Please refer to the `PolyNSI configuration documentation <https://github.com/workfloworchestrator/PolyNSI/tree/documentation#configuration>`_
for more details.
Note that the discovery and topology documents are directly served by SuPA bypassing PolyNSI.

SuPA currently does not have TLS support,
but PolyNSI does.
If you want to run SuPA on it own and do require TLS,
then you have to put it behind a proxy that supports that,
or deploy SuPA as part of the `nsi-node <https://github.com/BandwidthOnDemand/nsi-node>`_ super chart that uses an Envoy proxy for that reason.

Running
-------

Running SuPA is done by means of the ``supa`` command line utility.
When run without any options it displays help info.
Exactly as it would when run with the ``-h`` or ``--help`` options.
To do anything useful ``supa`` has subcommands.
An example of a subcommand is ``serve`` to start SuPA in server mode::

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

options
-------

Global
......

The following global options are available:

  --log-level TEXT                Log level (DEBUG, INFO, WARNING, ERROR,
                                  CRITICAL)  [default: INFO]
  --database-file PATH            Location of the SQLlite database file

Subcommand serve
................

The ``serve`` subcommand is used to start SuPA in server mode.
The following configuration options,
through command line options,
`supa.env` configuration file,
or environment variables,
are available:

  --grpc-server-max-workers INTEGER
                                  Maximum number of workers to serve gRPC
                                  requests.  [default: 8]
  --grpc-server-insecure-host TEXT
                                  GRPC server host to listen on.  [default:
                                  localhost]
  --grpc-server-insecure-port TEXT
                                  GRPC server port to listen on.  [default:
                                  50051]
  --grpc-client-insecure-host TEXT
                                  Host that PolyNSI listens on.  [default:
                                  localhost]
  --grpc-client-insecure-port TEXT
                                  Port that PolyNSI listens on.  [default:
                                  9090]
  --document-server-host TEXT     Host that the document server listens on.
                                  [default: localhost]
  --document-server-port INTEGER  Port that the document server listens on.
                                  [default: 4321]
  --scheduler-max-workers INTEGER
                                  Maximum number of workers to execute
                                  scheduler jobs.  [default: 12]
  --domain TEXT                   Name of the domain SuPA is responsible for.
                                  [default: example.domain:2001]
  --topology TEXT                 Name of the topology SuPA is responsible
                                  for.  [default: topology]
  --manual-topology               Use SuPA CLI to manually administrate
                                  topology.
  --reserve-timeout INTEGER       Reserve timeout in seconds.  [default: 120]
  --backend TEXT                  Name of backend module.
  --nsa-host TEXT                 Name of the host where SuPA is exposed on.
                                  [default: localhost]
  --nsa-port TEXT                 Port where SuPA is exposed on.  [default:
                                  8080]
  --nsa-name TEXT                 Descriptive name for this uPA.  [default:
                                  example.domain uPA]
  --nsa-scheme TEXT               URL scheme of the exposed service.
                                  [default: http]
  --nsa-provider-path TEXT        Path of the NSI provider endpoint.
                                  [default: /provider]
  --nsa-topology-path TEXT        Path of the NSI topology endpoint.
                                  [default: /topology]
  --nsa-discovery-path TEXT       Path of the NSI discovery endpoint.
                                  [default: /discovery]
  --nsa-owner-timestamp TEXT      Timestamp when the owner information was
                                  last change.  [default: 19700101T000000Z]
  --nsa-owner-firstname TEXT      Firstname of the owner of this uPA.
                                  [default: Firstname]
  --nsa-owner-lastname TEXT       Lastname of the owner of this uPA.
                                  [default: Lastname]
  --nsa-latitude TEXT             Latitude of this uPA.  [default: -0.374350]
  --nsa-longitude TEXT            Longitude of this uPA.  [default:
                                  -159.996719]
  --topology-name TEXT            Descriptive name for the exposed topology.
                                  [default: example.domain topology]
  --topology-freshness INTEGER    Number of seconds before fetching topology
                                  from backend again.  [default: 60]
  --healthcheck-with-topology     SuPA health check with call to
                                  Backend.topology() to assess NRM health.
  --backend-health-check-interval INTEGER
                                  The interval between health checks of all
                                  active connections in the NRM.  [default:
                                  60]


Subcommand stp
..............

Normally the topology interface of the backend is used to automatically keep the STP administration up to date,
see the section on backends for more information.
This can be disabled by starting supa as follows: ``supa serve --manual-topology``,
then the ``stp`` subcommand is used to administrate the STPs this uPA is responsible for.
When an STP is disabled it remains in the administration
but is not exposed in the topology document anymore.

.. note::

    Once an STP was part of a reservation it cannot be removed from the administration,
    it can only be disabled to prevent it to be exposed in the topology document.

add
```

The ``stp add`` subcommand accepts the following options:

  --stp-id TEXT           Uniq ID of the STP.  [required]
  --port-id TEXT          ID of the corresponding port.  [required]
  --vlans TEXT            VLANs part of this STP.  [required]
  --description TEXT      STP description.
  --is-alias-in TEXT      Inbound STP ID from connected topology.
  --is-alias-out TEXT     Outbound STP ID to connected topology.
  --bandwidth INTEGER     Available bandwidth for this STP in Mbps.
                          [required]
  --enabled / --disabled  [default: enabled]

modify
``````

The ``stp modify`` subcommand accepts the following options:

  --stp-id TEXT         Uniq ID of the STP.  [required]
  --port-id TEXT        ID of the corresponding port.
  --vlans TEXT          VLANs part of this STP.
  --description TEXT    STP description.
  --is-alias-in TEXT    Inbound STP ID from connected topology.
  --is-alias-out TEXT   Outbound STP ID to connected topology.
  --bandwidth INTEGER   Available bandwidth for this STP in Mbps.

delete
``````

The ``stp delete`` subcommand accepts the following options:

  --stp-id TEXT
                          STP id to be deleted from topology.  [required]

enable
``````

The ``stp enable`` subcommand accepts the following options:

  --stp-id TEXT
                          STP id to be enabled.  [required]

disable
```````

The ``stp disable`` subcommand accepts the following options:

  --stp-id TEXT
                          STP id to be disabled.  [required]

list
````

The ``stp list`` subcommand accepts the following options:

  --only [enabled|disabled]
                           Limit list of ports [default: list all]

Subcommand reservation
......................

list
````

The ``reservation list`` subcommand accepts the following options:

  --only [current|past]
                                  Limit list of reservations [default: list
                                  all]
  --order-by [start_time|end_time]
                                  Order reservations  [default: start_time]

Subcommand connection
.....................

list
````

The ``connection list`` subcommand accepts the following options:

  --only [current|past]
                                  Limit list of connections [default: list
                                  all]
  --order-by [start_time|end_time]
                                  Order connections  [default: start_time]
