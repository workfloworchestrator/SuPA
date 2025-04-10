# NSI Circuit NSO Service Package

This package implements an NSO service to manage NSI (Network Service Interface) L2VPN circuits.

Various files will need to be modified for your local NSO installation. 
 - The template file should create a service that implements an L2VPN.
 - The GetNsiStp action needs to be modified to query NSI metadata from your installation 

## Package Structure

```
nsi-circuit/
├── package-meta-data.xml    # NSO package metadata
├── python/                  # Python service implementation
│   └── nsi-circuit/
│       ├── __init__.py
│       └── main.py         # Main service implementation
├── src/
│   ├── Makefile
│   └── yang/              
│       └── nsi-circuit.yang # YANG service model
└── templates/
    └── nsi-circuit-template.xml # Service template
```

## Features

- Creates and manages L2VPN circuits with source and destination endpoints
- Validates VLAN assignments against allowed ranges
- Provides NSI STP (Service Termination Point) discovery
- Handles alias ports

## Components

### Service Model 
The package implements a YANG service model for NSI circuits that includes:
- Circuit ID
- Administrative state
- Source/Destination port configurations with interface and VLAN IDs
- Bandwidth settings

### Python Implementation
The main implementation includes:
- `NsiCircuit` - Main service class handling circuit creation
- `GetNsiStp` - Action handler for discovering available STPs
- VLAN validation against configured ranges

## Requirements
- NSO version 5.5 or higher
- Python 3.x

## Usage
Install the package in your NSO environment and use it to configure NSI L2VPN circuits through the NSO northbound interfaces.