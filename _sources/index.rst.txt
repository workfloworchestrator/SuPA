.. vim:noswapfile:nobackup:nowritebackup:

SURFnet 8 ultimate Provider Agent (SuPA)
========================================

Welcome to SuPA's documentation.
SuPA,
short for SURFnet 8 ultimate Provider Agent,
is an implementation of an NSI Network Service Agent.
An ultimate provider agent,
such as SuPA,
services NSI requests by coordinating with a local Network Resource Manager (NRM).
In case of SURFnet 8 the NRM would be the Orchestrator.

NSI (Network Service Interface) is an `Open Grid Forum <https://www.ogf.org>`_ (OGF)
`protocol (pdf) <https://www.ogf.org/documents/GFD.237.pdf>`_ that:

    ... enables the reservation, creation, management and removal of circuits (connections)
    that transit several networks managed by different providers.

It is currently mostly used to create dedicated, temporary connections between
`NRENs <https://en.wikipedia.org/wiki/National_research_and_education_network>`_,
such as SURF.

.. note::

    SuPA is kind of special in that it does not speak NSI's native 'language' SOAP.
    Instead, it relies on an `gRPC <https://grpc.io/>`_ version of the NSI protocol
    as implemented by `PolyNSI <https://git.ia.surfsara.nl/automation/projects/polynsi/>`_,
    a SOAP <-> gRPC translating proxy that is developed concurrently with SuPA.

    The idea is that a modern underlying protocol such gRPC
    should make it easier to develop NSI Network Service Agents
    in a wider range of languages than SOAP would have allowed.
    After all, due to its inherent complexity and ambiguity,
    support for SOAP was only every fully implemented for
    .NET, Java and C/C++.
    With the programming language barrier lifted
    we hope to increase the adoption of the NSI protocol.


.. toctree::
   :maxdepth: 2
   :caption: Contents:

   installation
   documentation
   running
   development
   changelog

.. toctree::
   :maxdepth: 2
   :Caption: API Reference

   api


Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
