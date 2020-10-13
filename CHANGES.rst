.. currentmodule:: supa

Version 0.1.0
-------------

2020-10-08
++++++++++

- First release
- Utilize PEP-518 to generate Python code from \*.proto files during installation
- Integrated Advanced Python Scheduler for running 'async' processes
- Implemented reservation system
- Ports management system (registering Orchestrator port in SuPA)
- Implemented messages:
    * NSA/AG -> SuPA:
        - Reserve
        - ReserveCommit
    * SuPA -> NSA/AG:
        - ReserveFailed
        - ReserveConfirmed
        - ReserveCommitFailed
        - ReserveCommitConfirmed
