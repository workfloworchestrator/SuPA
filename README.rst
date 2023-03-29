SURF ultimate Provider Agent (SuPA)
===================================

The SURF ultimate Provider Agent (SuPA) implements the `Connection Service <https://www.ogf.org>`_ (CS) version 2.1 protocol that:

    ... enables the reservation, creation, management and removal of circuits (connections)
    that transit several networks managed by different providers.

The CS protocol is one of several in the Network Service Interface (NSI) protocol suite;
the CS works together with these NSI services to deliver an integrated `Network Services Framework <https://ogf.org/documents/GFD.213.pdf>`_ (NSF).
One of the active deployments is the `Automated GOLE <https://www.gna-g.net/join-working-group/autogole-sense/>`_
which is part of the `Global Network Advancement Group <https://www.gna-g.net>`_ (GNA-G),
a worldwide collaboration of open exchange points and R&E networks
to deliver network services end-to-end in a fully automated way.

This provider agent uses a plugable backend
to interface with a local Network Resource Manager (NRM),
or to talk directly to a network device.

SuPA is kind of special in that it does not speak NSI's native 'language' SOAP.
Instead, it relies on an `gRPC <https://grpc.io/>`_ version of the NSI protocol
as implemented by `PolyNSI <https://github.com/workfloworchestrator/polynsi/>`_,
a SOAP <-> gRPC translating proxy that was developed as a companion for SuPA.

The idea is that a modern underlying protocol such gRPC
should make it easier to develop NSI Network Service Agents
in a wider range of languages than SOAP would have allowed.
After all, due to its inherent complexity and ambiguity,
support for SOAP was only every fully implemented for
.NET, Java and C/C++.
With the programming language barrier lifted
we hope to increase the adoption of the NSI protocol.

Documentation
-------------

For more information on how to install and configure SuPA,
or help develop the software,
please have a look at the `documentation <https://workfloworchestrator.org/SuPA/>`_.
