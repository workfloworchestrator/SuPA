# NSI Circuit

NSI parent service to create domain specific L2VPN

Resources
- [NSI Design](https://link.excalidraw.com/l/AB194fPXvRw/3ZNhASMiLfS)

# Examples
```
configure
load merge terminal
resource-manager {
  id-pool VNI-RD-RT-SUFFIX {
    range 10000 49999;
  }
  id-pool ARISTA-INTERNAL-VLAN-EOS0 {
    range 2 4050;
  }
  id-pool ARISTA-INTERNAL-VLAN-EOS1 {
    range 2 4050;
  }
}
services {
  pdp SITE1-CUST-1 {
        device eos0;
        eos {
            interface 1/1;
        }
        role gxp;
        admin-state in-service;
        nsi {
          stp-id wix-esnet-1;
          description "WIX HundredGigE 1/1 to ESnet";
          is-alias es.net:2013:something;
          vlan-range 1000 2000;
        }
    }
    pdp SITE2-CUST-2 {
        device eos1;
        eos {
            interface 1/1;
        }
        role gxp;
        admin-state in-service;
        nsi {
          stp-id manlan-netherlight-1;
          description "MANLAN HundredGigE 1/1 to Netherlight";
          is-alias surf.net:2013:something;
          vlan-range 10 10;
          vlan-range 3000 4000;
        }
    }
    pdp SITE2-CUST-3 {
        device eos1;
        eos {
            interface 101/1/1;
        }
        role platform;
        admin-state in-service;
    }
    nsi-circuit TEST-1 {
        admin-state in-service;
        src-port-id {
            interface SITE1-CUST-1;
            vlan-id 1001;
        }
        dst-port-id {
            interface SITE2-CUST-2;
            vlan-id 3003;
        }
    }
}

CTRL-D
commit
```
