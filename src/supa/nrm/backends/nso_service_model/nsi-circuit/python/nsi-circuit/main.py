import ncs
from ncs.application import Service
from ncs.dp import Action
from ncs.maagic import get_root


class NsiCircuit(Service):
    @Service.create
    def cb_create(self, tctx, root, service, proplist):
        self.log.info("Service create(service=", service._path, ")")

        if validate_vlan(self, root, service.src_port_id.interface, service.src_port_id.vlan_id):
            self.log.info(
                f"VLAN {service.src_port_id.vlan_id} is allowed for NSI use on PDP {service.src_port_id.interface}"
            )
        else:
            raise Exception(
                f"VLAN {service.src_port_id.vlan_id} not allowed for NSI use on PDP {service.src_port_id.interface}"
            )

        if validate_vlan(self, root, service.dst_port_id.interface, service.dst_port_id.vlan_id):
            self.log.info(
                f"VLAN {service.dst_port_id.vlan_id} is allowed for NSI use on PDP {service.dst_port_id.interface}"
            )
        else:
            raise Exception(
                f"VLAN {service.dst_port_id.vlan_id} not allowed for NSI use on PDP {service.dst_port_id.interface}"
            )

        template = ncs.template.Template(service)
        template.apply("nsi-circuit-template")

    # @Service.pre_modification
    # def cb_pre_modification(self, tctx, op, kp, root, proplist):
    #     self.log.info('Service premod(service=', kp, ')')

    # @Service.post_modification
    # def cb_post_modification(self, tctx, op, kp, root, proplist):
    #     self.log.info('Service postmod(service=', kp, ')')


class GetNsiStp(Action):
    @Action.action
    def cb_action(self, uinfo, name, kp, input, output, trans):
        root = get_root(trans)

        # Iterate through all PDPs
        for pdp in root.services.pdp:
            # Check if PDP has NSI configured
            if pdp.nsi:
                # Create a new list item in the output
                self.log.info(f"Creating NSI output for {pdp.name}")
                stp_info = output.stp_list.create(pdp.nsi.stp_id)
                stp_info.port_id = pdp.name
                stp_info.description = pdp.nsi.description
                stp_info.bandwidth = pdp.nsi.bandwidth
                stp_info.is_alias = pdp.nsi.is_alias

                # Convert NSI VLAN ranges into a comma-separated string format.
                # Example output: "10,1000-2000,3000-4000"
                vlan_ranges = []
                for vrange in pdp.nsi.vlan_range:
                    if vrange.lower == vrange.upper:
                        vlan_ranges.append(str(vrange.lower))
                    else:
                        vlan_ranges.append(f"{vrange.lower}-{vrange.upper}")
                stp_info.vlans = ",".join(vlan_ranges)


class Main(ncs.application.Application):
    def setup(self):
        self.log.info("Main RUNNING")
        self.register_service("nsi-servicepoint", NsiCircuit)
        self.register_action("get-nsi-stp-action", GetNsiStp)

    def teardown(self):
        self.log.info("Main FINISHED")


def validate_vlan(self, root, pdp_name, vlan):
    """Check to make sure NSI VLAN is allowed on a PDP"""
    pdp = root.services.pdp[pdp_name]
    for r in pdp.nsi.vlan_range:
        self.log.info(f"Checking if {vlan} is in NSI VLAN range {r.lower}-{r.upper} for PDP {pdp.name}")
        if r.lower <= vlan <= r.upper:
            return True
    return False
