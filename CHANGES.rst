.. currentmodule:: supa

Version 0.2.0
-------------

2023-03-09
++++++++++

- Implemented messages:
    - connection provider:
        - QueryRecursive
        - QueryNotification
        - QueryNotificationSync
        - QueryResult
        - QueryResultSync
    - connection requester:
        - ErrorEvent
        - QueryRecursiveConfirmed
        - QueryNotificationConfirmed
        - QueryResultConfirmed

Version 0.1.0
-------------

2022-07-07
++++++++++

- data plane fsm and job to manage connection (de)activation
- generation of discovery, topology and healthcheck documents
- plugable backend
- CLI commands to list reservations and connection
- Implemented messages:
    * connection provider:
        - Provision
        - Release
        - Terminate
    * connection requester:
        - ProvisionConfirmed
        - ReleaseConfirmed
        - TerminateConfirmed
        - Error
        - DataPlaneStateChange
        - ReserveTimeout

Version 0.0.1
-------------

2020-10-08
++++++++++

- First release
- Utilize PEP-518 to generate Python code from \*.proto files during installation
- Integrated Advanced Python Scheduler for running 'async' processes
- Implemented reservation system
- Ports management system (registering Orchestrator port in SuPA)
- Implemented messages:
    * connection provider:
        - Reserve
        - ReserveCommit
        - ReserveAbort
    * connection requester:
        - ReserveFailed
        - ReserveConfirmed
        - ReserveCommitFailed
        - ReserveCommitConfirmed
        - ReserveAbortConfirmed
