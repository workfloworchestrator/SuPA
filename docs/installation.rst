.. vim:noswapfile:nobackup:nowritebackup:
.. highlight:: console

Installation
============

The installation instructions assume that SuPA is installed together with PolyNSI.
Both applications are available as source code on GitHub,
or as prebuilt container through the GitHub Container Registry.
The PolyNSI repository also contains prebuilt JARs.
There are several methods to install and run the application:

- GitHub clone
- Docker compose
- Helm chart
- nsi-node Helm super chart


.. note::

    SuPA has been tested with Python version 3.11 upto and including 3.14.
    Compatibility with earlier Python versions will brake in the future or is already broken.
    Compatibility with later Python versions is untested.

    PolyNSI has been tested with Java 21.
    Compatibility with other Java versions is untested, but will probably just work.
    It is assumed that a suitable versions of Java is already installed. Use the Maven wrapper
    `mvnw` in the root of the repository to use the bundled Maven.

GitHub
++++++

SuPA
----

_`Clone the SuPA source code repository from GitHub`,
and checkout the desired branch or version,
for example version 0.3.4::

    git clone https://github.com/workfloworchestrator/supa.git
    cd supa
    git checkout 0.4.1

There are multiple ways to add an virtual Python environment, and you can choose
whatever suits you best. This example uses the standard ``venv`` module and assumes
that Python version 3.12 is already installed using your local package manager::

    python3.13 -m venv venv
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

_`Clone the PolyNSI source code repository from GitHub`,
and checkout the desired branch or version,
for example version 0.2.0::

    git clone https://github.com/workfloworchestrator/polynsi.git
    cd PolyNSI
    git checkout 0.4.0

And start the application::

    ./mvnw spring-boot:run

Docker compose
++++++++++++++

`Clone the SuPA source code repository from GitHub`_.
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

Both SuPA and PolyNSI have `Helm <https://helm.sh/>`_ charts
to easily deploy to Kubernetes.
Please refer to the supplied ``values.yaml`` files for Helm configuration details.

SuPA
----

`Clone the SuPA source code repository from GitHub`_.
The `chart` folder contains contains a Helm chart to deploy SuPA to a Kubernetes cluster::

    kubectl create namespace nsi
    helm upgrade --namespace nsi --install supa chart

PolyNSI
-------

`Clone the PolyNSI source code repository from GitHub`_.
The `chart` folder contains contains a Helm chart to deploy PolyNSI to a Kubernetes cluster::

    helm upgrade --namespace nsi --install polynsi chart


nsi-node Helm super chart
+++++++++++++++++++++++++

Both SuPA and PolyNSI can also be deployed by the nsi-node super chart,
that can also be used to deploy other pieces of the NSI stack for a more complete deployment.
Please refer to the documentation in the `nsi-node <https://github.com/BandwidthOnDemand/nsi-node>`_ GitHub repository.
