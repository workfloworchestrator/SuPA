.. vim:noswapfile:nobackup:nowritebackup:
.. highlight:: console

Installation
============

The installation instructions assume that SuPA is installed together with PolyNSI.
There are several methods to install and run the application:

- GitHub clone
- Docker compose
- Helm chart
- nsi-node Helm super chart


.. note::

    SuPA was developed using Python 3.8.
    Compatibility with other Python versions is untested.

    PolyNSI was developed using Java 11 and Maven 3.8.5.
    Compatibility with other Java and Maven versions is untested.
    It is assumed that a suitable versions of Java and Maven are already installed.

GitHub
++++++

SuPA
----

.. _clone:

Clone the SuPA source code repository from GitHub,
and checkout the desired branch or version,
for example version 0.2.0::

    git clone https://github.com/workfloworchestrator/supa.git
    cd supa
    git checkout 0.2.0

There are multiple ways to add an virtual Python environment, and you can choose
whatever suits you best. This example uses the standard ``venv`` module and assumes
that Python version 3.8 is already installed using your local package manager::

    python3.8 -m venv venv
    source venv/bin/activate

The virtual environment created by the ``venv`` module does not always contain the most recent version of ``pip``.
As we are using some newer Python packaging standards (`PEP-518 <https://www.python.org/dev/peps/pep-0518/>`_)
it is probably a good idea to have ``pip`` updated to its most recent version::

    pip install --upgrade pip wheel

We are including ``wheel`` as we will be building or using pre-built C++ extensions.

Now install all dependencies needed by SuPA::

    pip install .

And start the application::

    supa serve

PolyNSI
-------

Clone the PolyNSI source code repository from GitHub,
and checkout the desired branch or version,
for example version 0.2.0::

    git clone https://github.com/workfloworchestrator/polynsi.git
    cd PolyNSI
    git checkout 0.2.0

And start the application::

    mvn spring-boot:run

Docker compose
++++++++++++++

First clone_ the SuPA repository from GitHUB.
The `docker` folder contains the following:

::

    docker
    ├── application.properties
    ├── docker-compose.yml
    ├── polynsi-keystore.jks
    ├── polynsi-truststore.jks
    └── supa.env

The `supa.env` is used to override parts of the SuPA default configuration.
PolyNSI is configured to use the supplied `polynsi-keystore.jks` and `polynsi-truststore.jks`
by setting the approriate options in `application.properties`.
The `docker-compose.yml` has three services defined,
one to create an empty folder `db` in the current folder
that will be used to store the SQLite database file used by SuPA,
a seconds service to start PolyNSI,
and last be not least a third service to start SuPA itself.
By default the latest prebuilt SuPA and PolyNSI containers from the GitHub container registry will be used.

To start SuPA and PolyNSI just execute the following commands::

    cd docker
    docker compose up

Helm chart
++++++++++

First clone_ the SuPA repository from GitHUB.
The `chart` folder contains contains a Helm chart to deploy SuPA and PolyNSI to a Kubernetes cluser::

    kubectl create namespace nsi
    helm upgrade --namespace nsi --install supa chart

nsi-node Helm super chart
+++++++++++++++++++++++++

Both SuPA and PolyNSI can also be deployed by the nsi-node super chart,
that can also be used to deploy other pieces of the NSI stack for a more complete deployment.
Please refer to the documentation in the `nsi-node <https://github.com/BandwidthOnDemand/nsi-node>`_ GitHub repository.
