"""
Generate Netkit configuration files for a network
"""
from mako.lookup import TemplateLookup

from pkg_resources import resource_filename
import pkg_resources

import os

#import network as network

import logging
LOG = logging.getLogger("ANK")

            #TODO: replace other if node in servers with node.is_server
import shutil
import glob
import time
import tarfile

import AutoNetkit as ank
from AutoNetkit import config
settings = config.settings

import pprint

# Check can write to template cache directory
#TODO: make function to provide cache directory
template_cache_dir = config.template_cache_dir

template_dir =  resource_filename("AutoNetkit","lib/templates")
lookup = TemplateLookup(directories=[ template_dir ],
                        module_directory= template_cache_dir,
                        #cache_type='memory',
                        #cache_enabled=True,
                       )

#TODO: make a check_dir function that tries to create directory, if unable then recursively try/except to create parent directories

#TODO: add more detailed exception handling to catch writing errors
# eg for each subdir of templates

#TODO: make this a module
#TODO: make this a netkit compiler plugin
#TODO: clear up label vs node id

#TODO: Move these into a netkit helper function*****
def lab_dir():
    return config.lab_dir

def netkit_dir(network, rtr):
    """Returns Netkit path"""
    #TODO: reinstate this for multi-machine ANK
    #nk_dir =  ank.netkit_hostname(network, rtr)
    #return os.path.join(lab_dir(), nk_dir)
    return lab_dir()

def shared_dir():
# Shared dir for the lab
# Refer http://wiki.netkit.org/man/man1/lstart.1.html#lbAE
    return os.path.join(lab_dir(), "shared")

def shared_etc_dir():
    return os.path.join(shared_dir(), "etc")

def router_dir(network, rtr):
    """Returns path for router rtr"""
    foldername = ank.rtr_folder_name(network, rtr)
    return os.path.join(netkit_dir(network, rtr), foldername)

def root_dir(network, rtr):
    """Returns root path for router rtr"""
    #TODO: rewrite these using join
    return os.path.join(router_dir(network, rtr), "root")

def dot_ssh_dir(network, rtr):
    """Returns .ssh path for router rtr"""
    #TODO: rewrite these using join
    return os.path.join(root_dir(network, rtr), ".ssh")

def etc_dir(network, rtr):
    """Returns etc path for router rtr"""
    #TODO: rewrite these using join
    return os.path.join(router_dir(network, rtr), "etc")

def sshd_dir(network, rtr):
    """Returns formatted ssh path"""
    return os.path.join(etc_dir(network, rtr), "ssh")

def zebra_dir(network, rtr):
    """Returns formatted Zebra path"""
    return os.path.join(etc_dir(network, rtr), "zebra")

def bind_dir(network, rtr):
    """Returns bind path for router rtr"""
    return os.path.join(etc_dir(network, rtr), "bind")

def lo_interface(int_id=0):
    """Returns Linux format lo_interface id for int_id"""
    #TODO: use this throughout the module
    return "lo%s" % int_id


class NetkitCompiler:
    """Compiler main"""

    def __init__(self, network, services, zebra_password="1234"):
        self.network = network
        self.services = services
        self.zebra_password = zebra_password
        self.interface_id = ank.interface_id('netkit')
        self.tap_interface_id = ank.tap_interface_id
        self.lo_interface = lo_interface
        self.default_weight = 1
        # Speed improvement: grab eBGP and iBGP  graphs
        #TODO: fetch eBGP and iBGP graphs and cache them

    def initialise(self):
        """Creates lab folder structure"""

        # TODO: clean out netkitdir
        # Don't just remove the whole folder
        # Note is ok to leave lab.conf as this will be over ridden
        #TODO: make this go into one dir for each netkithost
        if not os.path.isdir(lab_dir()):
            os.mkdir(lab_dir())
        else:
            # network dir exists, clean out all (based on glob of ASxry)
            #TODO: see if need * wildcard for standard glob
            for item in glob.iglob(os.path.join(lab_dir(), "*")):
                if os.path.isdir(item):
                    shutil.rmtree(item)
                else:
                    os.unlink(item)

        # Create folder for netkit hosts
        #TODO: reinstate for multi-machine ANK
        if not os.path.isdir(shared_dir()):
            os.mkdir(shared_dir())
        if not os.path.isdir(shared_etc_dir()):
            os.mkdir(shared_etc_dir())
        
        dns_servers = set(self.network.dns_servers())

        for device in self.network.devices():
                # Make folders - note order counts:
                # need to make router dir before zebra, etc dirs
#TODO: only append root_dir and sshd_dir if netkit ssh key set
                for test_dir in [router_dir(self.network, device),
                                 etc_dir(self.network, device),
                                 sshd_dir(self.network, device),
                                 root_dir(self.network, device),
                                 dot_ssh_dir(self.network, device),
                                 zebra_dir(self.network, device)]:
                    if not os.path.isdir(test_dir):
                        os.mkdir(test_dir)

                if device in dns_servers:
                    b_dir = bind_dir(self.network, device)
                    if not os.path.isdir(b_dir):
                        os.mkdir(b_dir)
        return

    def configure_netkit(self):
        """Generates Netkit and Zebra/Quagga specific configuration files."""

        # Sets up netkit related files
        tap_host = ank.get_tap_host(self.network)

        ank_version = pkg_resources.get_distribution("AutoNetkit").version
        date = time.strftime("%Y-%m-%d %H:%M", time.localtime())

        lab_template = lookup.get_template("netkit/lab.mako")
        startup_template = lookup.get_template("netkit/startup.mako")
        zebra_daemons_template = lookup.get_template(
            "quagga/zebra_daemons.mako")
        zebra_template = lookup.get_template("quagga/zebra.mako")
        sshd_template = lookup.get_template("linux/sshd.mako")
        motd_template = lookup.get_template("quagga/motd.mako")

        # Shared (common) configuration
        startup_daemon_list = []
        #Setup ssh
        shutil.copy(resource_filename("AutoNetkit","lib/shadow"), shared_etc_dir())
        startup_daemon_list.append("ssh")
        # Need to chown root dir for ssh keys
# refer http://list.dia.uniroma3.it/pipermail/netkit.users/2010-February/000552.html
        use_ssh_key = False
        if config.settings['Netkit']['ssh key']:
            #chown root:root /root
            use_ssh_key = True

        f_startup = open( os.path.join(lab_dir(), "shared.startup"), 'wb')
        f_startup.write(startup_template.render(
            interfaces=[],
            add_localhost=True,
            #don't send out the tap interface
            del_default_route=True,
            daemons=startup_daemon_list,
            use_ssh_key = use_ssh_key,
            ))
        f_startup.close()


# Files for indvidual node configuration

        #TODO: this needs to be created for each netkit host machine
        f_lab = open(os.path.join(lab_dir(), "lab.conf"), 'wb')

        lab_conf = {}
        tap_list_strings = {}

        ibgp_routers = ank.ibgp_routers(self.network)
        ebgp_routers = ank.ebgp_routers(self.network)
        igp_graph = ank.igp_graph(self.network)

        dns_servers = set(self.network.dns_servers())
        routers = set(self.network.routers())

        for node in self.network.devices():
            #TODO: see if rtr label is still needed, if so replace with
            # appropriate naming module function
            rtr_folder_name = ank.rtr_folder_name(self.network, node)

            # sshd options
            f_sshd = open( os.path.join(sshd_dir(self.network, node), "sshd_config"), 'wb')
            f_sshd.write(sshd_template.render())
            f_sshd.close()

            lab_conf[rtr_folder_name] = []
            startup_daemon_list = ["zebra"]
            startup_int_list = []

            # convert tap list from ips into strings
            # tap_int_id cannot conflict with already allocated interfaces
            # assume edges number sequentially, so next free int id is number of
            # edges
            node_tap_id = self.tap_interface_id(self.network, node)
            tap_list_strings[rtr_folder_name] = (node_tap_id,
                                                 self.network[node].get('tap_ip'))

            if node in dns_servers:
                startup_daemon_list.append("bind")
                dns_memory = 64 # Allocate more memory to DNS server 
                #TODO: remove key, val and make it just key: val
                lab_conf[rtr_folder_name].append( ('mem', dns_memory))

            if config.settings['Netkit']['ssh key']:
                f_auth_keys = open(os.path.join(dot_ssh_dir(self.network, node), "authorized_keys"), "wb")
                f_auth_keys.write(config.settings['Netkit']['ssh key'])
                f_auth_keys.close()

            # Zebra Daemons
            zebra_daemon_list = []
            f_zdaemons = open( os.path.join(zebra_dir(self.network, node),
                                            "daemons"), 'wb')
# Always start Zebra
            zebra_daemon_list.append("zebra")

            if igp_graph.degree(node) > 0:
                zebra_daemon_list.append("ospfd") # Only start IGP process if IGP links
            if (node in ibgp_routers) or (node in ebgp_routers):
                zebra_daemon_list.append("bgpd")

            f_zdaemons.write(zebra_daemons_template.render(
                entryList = zebra_daemon_list,
            ))
            f_zdaemons.close()
# MOTD
            f_zmotd = open( os.path.join(zebra_dir(self.network, node),
                                            "motd.txt"), 'wb')

            f_zmotd.write(motd_template.render(
                date = date,
                version = ank_version,
                password = self.zebra_password,
            ))

            # Main Zebra config
            f_z = open( os.path.join(zebra_dir(self.network, node),
                                     "zebra.conf"), 'wb')
            f_z.write( zebra_template.render(
                hostname = node.device_hostname,
                password = self.zebra_password,
                enable_password = self.zebra_password,
                use_snmp = True,
                use_debug = True,
                ))
            f_z.close()

            # Loopback interface
            lo_ip = self.network.lo_ip(node)
            startup_int_list.append({
                'int':          'lo:1',
                'ip':           str(lo_ip.ip),
                'netmask':      str(lo_ip.netmask),
            })

            # Ethernet interfaces
            for link in self.network.links(node):
                int_id = self.interface_id(link.id)
                subnet = link.subnet

                # replace the / from subnet label
                collision_domain = "%s.%s" % (subnet.ip, subnet.prefixlen)
    
                # lab.conf has id in form host[0]=... for eth0 of host
                lab_conf[rtr_folder_name].append((link.id, collision_domain))
                startup_int_list.append({
                    'int':          int_id,
                    'ip':           str(link.ip),
                    'netmask':      str(subnet.netmask),
                    'broadcast':    str(subnet.broadcast),
                })

            default_route = None
            if node.is_server:
                default_route = ank.default_route(node)
# add default_route for server to router

            chown_bind = False
            if node in ank.dns_servers(self.network):
                chown_bind = True

            #Write startup file for this router
            f_startup = open( os.path.join(netkit_dir(self.network, node),
                "{0}.startup".format(rtr_folder_name)), 'wb')

            f_startup.write(startup_template.render(
                interfaces=startup_int_list,
                add_localhost=True,
                #don't send out the tap interface
                del_default_route=True,
                default_route = default_route,
                daemons=startup_daemon_list,
                chown_bind = chown_bind,
                ))
            f_startup.close()

        # Write lab file for whole lab
        f_lab.write(lab_template.render(
            conf = lab_conf,
            tapHost = tap_host,
            tapList = tap_list_strings,
            lab_description = "AutoNetkit generated lab",
            lab_version = date,
            #TODO: get this from config file
            lab_email = "autonetkit@googlegroups.com",
            lab_author = "AutoNetkit %s" % ank_version,
            #TODO: get this from config file
            lab_web =  "www.autonetkit.org",
        ))

    def configure_igp(self):
        """Generates IGP specific configuration files (eg ospfd)"""
        LOG.debug("Configuring IGP")
        template = lookup.get_template("quagga/ospf.mako")
        default_weight = 1

        # configures IGP for each AS
        as_graphs = ank.get_as_graphs(self.network)
        for my_as in as_graphs:
            asn = my_as.asn
            LOG.debug("Configuring IGP for AS %s " % asn)
            if my_as.number_of_edges() == 0:
                # No edges, nothing to configure
                LOG.debug("Skipping IGP for AS%s as no internal links" % asn)
                continue

            for router in self.network.routers(asn):
                #TODO: can probably through most of these straight into the template and use properties there!

                interface_list = []
                network_list = []

                # Add loopback info
                lo_ip = router.lo_ip 
                interface_list.append ( {'id':  "lo", 'weight':  1,
                                        'remote_router': "NA (loopback)",
                                        'remote_int': "Loopback"})
                network_list.append ( { 'cidr': lo_ip.cidr, 'ip': lo_ip.ip,
                                    'netmask': lo_ip.netmask,
                                    'area': 0, 'remote_ip': "Loopback" })

                for link in self.network.links(router, my_as):

                    int_id = self.interface_id(link.id)
                    weight = link.weight or default_weight
                    interface_list.append ({ 'id':  int_id,
                                            'weight': weight,
                                            'remote_router': link.remote_host, } )

                    # fetch and format the ip details
                    subnet = link.subnet
                    local_ip = link.local_ip
                    remote_ip = link.remote_ip
                    network_list.append ( { 'cidr': subnet.cidr, 'ip': local_ip,
                                        'netmask': subnet.netmask,
                                        'remote_ip': remote_ip, 'area': 0, } )

                #TODO: see if need to use router-id for ospfd in quagga
                f_handle = open( os.path.join(zebra_dir(self.network, router),
                        "ospfd.conf"), 'wb')

                f_handle.write(template.render
                               (
                                   hostname = router.device_hostname,
                                   password = self.zebra_password,
                                   enable_password = self.zebra_password,
                                   interface_list = interface_list,
                                   network_list = network_list,
                                   routerID = router,
                                   use_igp = True,
                                   logfile = "/var/log/zebra/ospfd.log",
                                   use_debug = False,
                               ))

    def configure_interfaces(self, device):
        LOG.debug("Configuring interfaces for %s" % self.network.fqdn(device))
        """Interface configuration"""
        lo_ip = self.network.lo_ip(device)
        interfaces = []

        interfaces.append({
            'id':          'lo0',
            'ip':           lo_ip.ip,
            'netmask':      lo_ip.netmask,
            'wildcard':      lo_ip.hostmask,
            'prefixlen':    lo_ip.prefixlen,
            'network':       lo_ip.network,
            'description': 'Loopback',
        })

        for src, dst, data in self.network.graph.edges(device, data=True):
            subnet = data['sn']
            int_id = self.interface_id(data['id'])
            description = 'Interface %s -> %s' % (
                    ank.fqdn(self.network, src), 
                    ank.fqdn(self.network, dst))

# Interface information for router config
            interfaces.append({
                'id':          int_id,
                'ip':           data['ip'],
                'network':       subnet.network,
                'prefixlen':    subnet.prefixlen,
                'netmask':    subnet.netmask,
                'wildcard':      subnet.hostmask,
                'broadcast':    subnet.broadcast,
                'description':  description,
                'weight':   data.get('weight', self.default_weight),
            })

        return interfaces

    def configure_bgp(self):
        """Generates BGP specific configuration files"""

        ip_as_allocs = ank.get_ip_as_allocs(self.network)

        LOG.debug("Configuring BGP")
        template = lookup.get_template("quagga/bgp.mako")

        route_maps = {}

        ibgp_graph = ank.get_ibgp_graph(self.network)
        ebgp_graph = ank.get_ebgp_graph(self.network)
        physical_graph = self.network.graph

        for my_as in ank.get_as_graphs(self.network):
            asn = my_as.asn
            LOG.debug("Configuring IGP for AS %s " % asn)
            # get nodes ie intersection
            #H = nx.intersection(my_as, ibgp_graph)
            # get ibgp graph that contains only nodes from this AS

            for router in self.network.routers(asn):
                #TODO: look at making this a set for greater comparison efficiency
                bgp_groups = {}
                route_maps = []
                ibgp_neighbor_list = []
                ibgp_rr_client_list = []
                route_map_groups = {}

                if router in ibgp_graph:
                        for src, neigh, data in ibgp_graph.edges(router, data=True):
                            route_maps_in = self.network.g_session[neigh][router]['ingress']
                            rm_group_name_in = None
                            if len(route_maps_in):
                                rm_group_name_in = "rm_%s_in" % neigh.folder_name
                                route_map_groups[rm_group_name_in] = [match_tuple 
                                        for route_map in route_maps_in
                                        for match_tuple in route_map.match_tuples]

                            route_maps_out = self.network.g_session[router][neigh]['egress']
                            rm_group_name_out = None
                            if len(route_maps_out):
                                rm_group_name_in = "rm_%s_out" % neigh.folder_name
                                route_map_groups[rm_group_name_out] = [match_tuple 
                                        for route_map in route_maps_out
                                        for match_tuple in route_map.match_tuples]

                            description = data.get("rr_dir") + " to " + ank.fqdn(self.network, neigh)
                            if data.get('rr_dir') == 'down':
                                ibgp_rr_client_list.append(
                                        {
                                            'id':  self.network.lo_ip(neigh).ip,
                                            'description':      description,
                                            'route_maps_in': rm_group_name_in,
                                            'route_maps_out': rm_group_name_out,
                                            })
                            elif (data.get('rr_dir') in set(['up', 'over', 'peer'])
                                    or data.get('rr_dir') is None):
                                ibgp_neighbor_list.append(
                                        {
                                            'id':  self.network.lo_ip(neigh).ip,
                                            'description':      description,
                                            'route_maps_in': rm_group_name_in,
                                            'route_maps_out': rm_group_name_out,
                                            })

                        bgp_groups['internal_peers'] = {
                            'type': 'internal',
                            'neighbors': ibgp_neighbor_list
                            }
                        if len(ibgp_rr_client_list):
                            bgp_groups['internal_rr'] = {
                                    'type': 'internal',
                                    'neighbors': ibgp_rr_client_list,
                                    'cluster': self.network.lo_ip(router).ip,
                                    }

                if router in ebgp_graph:
                    external_peers = []
                    for peer in ebgp_graph.neighbors(router):
                        route_maps_in = self.network.g_session[peer][router]['ingress']
                        rm_group_name_in = None
                        if len(route_maps_in):
                            rm_group_name_in = "rm_%s_in" % peer.folder_name
                            route_map_groups[rm_group_name_in] = [match_tuple 
                                    for route_map in route_maps_in
                                    for match_tuple in route_map.match_tuples]

# Now need to update the sequence numbers for the flattened route maps

                        route_maps_out = self.network.g_session[router][peer]['egress']
                        rm_group_name_out = None
                        if len(route_maps_out):
                            rm_group_name_out = "rm_%s_out" % peer.folder_name
                            route_map_groups[rm_group_name_out] = [match_tuple 
                                    for route_map in route_maps_out
                                    for match_tuple in route_map.match_tuples]

                        peer_ip = physical_graph[peer][router]['ip'] 

                        external_peers.append({
                            'id': peer_ip, 
                            'route_maps_in': rm_group_name_in,
                            'route_maps_out': rm_group_name_out,
                            'peer_as': self.network.asn(peer)})
                    bgp_groups['external_peers'] = {
                            'type': 'external', 
                            'neighbors': external_peers}

# Ensure only one copy of each route map, can't use set due to list inside tuples (which won't hash)
# Use dict indexed by name, and then extract the dict items, dict hashing ensures only one route map per name
                community_lists = {}
                prefix_lists = {}
                node_bgp_data = self.network.g_session.node.get(router)
                if node_bgp_data:
                    community_lists = node_bgp_data.get('tags')
                    prefix_lists = node_bgp_data.get('prefixes')
                policy_options = {
                'community_lists': community_lists,
                'prefix_lists': prefix_lists,
                'route_maps': route_map_groups,
                }
            
                f_handle = open(os.path.join(zebra_dir(self.network, router),
                                                "bgpd.conf"),'wb')

                #TODO: remove community_lists and prefix_lists as they are put into policy_options
                f_handle.write(template.render(
                        hostname = router.device_hostname,
                        asn = self.network.asn(router),
                        password = self.zebra_password,
                        enable_password = self.zebra_password,
                        router_id = self.network.lo_ip(router).ip,
                        community_lists = community_lists,
                        policy_options = policy_options,
                        prefix_lists = prefix_lists,
                        #TODO: see how this differs to router_id
                        identifying_loopback = self.network.lo_ip(router),
                        bgp_groups = bgp_groups,
                        ibgp_neighbor_list = ibgp_neighbor_list,
                        ibgp_rr_client_list = ibgp_rr_client_list,
                        route_maps = route_maps,
                        logfile = "/var/log/zebra/bgpd.log",
                        debug=True,
                        use_debug=True,
                        dump=False,
                        snmp=False,
                        interfaces = self.configure_interfaces(router)
                ))

    def configure_dns(self):
        """Generates BIND configuration files for DNS

        Can check configs eg:

        Forward::

            bash-3.2$ named-checkzone -d AS3 ank_lab/netkit_lab/AS3_l3_3_dns_1/etc/bind/db.AS3
            loading "AS3" from "ank_lab/netkit_lab/AS3_l3_3_dns_1/etc/bind/db.AS3" class "IN"
            zone AS3/IN: loaded serial 2008080101
            OK


        Reverse::

            bash-3.2$ named-checkzone -d 0.10.in-addr.arpa ank_lab/netkit_lab/AS3_l3_3_dns_1/etc/bind/db.0.10.in-addr.arpa. 
            loading "0.10.in-addr.arpa" from "ank_lab/netkit_lab/AS3_l3_3_dns_1/etc/bind/db.0.10.in-addr.arpa." class "IN"
            zone 0.10.in-addr.arpa/IN: loaded serial 2008080101
            OK


        named::

            bash-3.2$ named-checkconf ank_lab/netkit_lab/AS3_l3_3_dns_1/etc/bind/named.conf 
        
        """
        import netaddr
        ip_localhost = netaddr.IPAddress("127.0.0.1")
        linux_bind_dir = "/etc/bind"
        resolve_template = lookup.get_template("linux/resolv.mako")
        forward_template = lookup.get_template("bind/forward.mako")

        named_template = lookup.get_template("bind/named.mako")
        reverse_template = lookup.get_template("bind/reverse.mako")
        root_template = lookup.get_template("bind/root.mako")

        root_dns_template = lookup.get_template("bind/root_dns.mako")
        root_dns_named_template = lookup.get_template("bind/root_dns_named.mako")

        ip_as_allocs = ank.get_ip_as_allocs(self.network)

        dns_servers = ank.dns_servers(self.network)
        root_servers = list(ank.root_dns_servers(self.network))
        auth_servers = ank.dns.dns_auth_servers(self.network)
        caching_servers = ank.dns.dns_cache_servers(self.network)
        clients = ank.dns.dns_clients(self.network)
        routers = set(self.network.routers())

#TODO: use with for opening files

        for server in root_servers:
            children = ank.dns.dns_hiearchy_children(server)
            child_servers = []
            for child in children:
                advertise_block = ip_as_allocs[child.asn]
                reverse_identifier = ank.rev_dns_identifier(advertise_block)
                child_servers.append( (child.domain, reverse_identifier, ank.server_ip(child)))
            f_root_db = open(os.path.join(bind_dir(self.network, server), "db.root"), 'wb') 
            f_root_db.write( root_dns_template.render(
                dns_servers = child_servers,
                server = server,
            ))

            f_named = open( os.path.join(bind_dir(self.network, server), "named.conf"), 'wb')
            f_named.write(root_dns_named_template.render(
                logging = False,
            ))

        for server in caching_servers:
            #root_db_hint = ( ("ns.AS%s" % n.asn, ank.server_ip(n)) for n in ank.dns_hiearchy_parents(server))
            root_db_hint = ( ("ROOT-SERVER", ank.server_ip(n)) for n in root_servers)
            root_db_hint = list(root_db_hint)
#TODO: make caching use parent rather than global root
            f_root = open( os.path.join(bind_dir(self.network, server), "db.root"), 'wb')
            f_root.write( root_template.render( root_servers = root_db_hint))
            f_named = open( os.path.join(bind_dir(self.network, server), "named.conf"), 'wb')
            f_named.write(named_template.render(
                entry_list = [],
                bind_dir = linux_bind_dir,
                logging = False,
            ))
            f_named.close()

        for server in auth_servers:
            named_list = []
            advertise_links = list(ank.advertise_links(server))
            advertise_hosts = list(ank.dns_auth_children(server))
            LOG.debug("DNS server %s advertises %s" % (server, advertise_links))
#TODO: make reverse dns handle domains other than /8 /16 /24
            advertise_block = ip_as_allocs[server.asn]
# remove trailing fullstop
            reverse_identifier = ank.rev_dns_identifier(advertise_block).rstrip(".")
#TODO: look at using advertise_block.network.reverse_dns - check what Bind needs
            named_list.append(reverse_identifier)

            f_named = open( os.path.join(bind_dir(self.network, server), "named.conf"), 'wb')
            f_named.write(named_template.render(
                domain = server.domain,
                entry_list = named_list,
                bind_dir = linux_bind_dir,
                logging = False,
            ))
            f_named.close()

            for_entry_list = list( (self.interface_id(link.id), link.local_host.dns_host_portion_only, link.ip) 
                    for link in advertise_links)
# Add loopbacks for routers
            for_entry_list += ( (self.lo_interface(0), host.dns_host_portion_only, host.lo_ip.ip)
                    #TODO: make thise check l3 group rather than asn (generalise)
                    for host in advertise_hosts if host.is_router and host.asn == server.asn)
            
            rev_entry_list = list( 
                    (ank.reverse_subnet(link.ip, advertise_block.prefixlen), self.interface_id(link.id), link.local_host.dns_hostname) 
                    for link in advertise_links)
            # Add loopbacks for routers
            rev_entry_list += ( (ank.reverse_subnet(host.lo_ip.ip, advertise_block.prefixlen), self.lo_interface(0), host.dns_host_portion_only)
                    #TODO: make thise check l3 group rather than asn (generalise)
                    for host in advertise_hosts if host.is_router and host.asn == server.asn)

            #TODO: provide better way to get eg eth0.host than string concat inside the template

            host_cname_list = []
            for host in advertise_hosts:
                if host.asn != server.asn:
# host is from another asn, skip.
#TODO: extend this to make sure matches same asn, l3group and l2group
                    continue

                if host.is_router:
# has lo_ip
                    cname = "%s.%s" % (self.lo_interface(), host.dns_host_portion_only)
                else:
# choose an interface - arbitrary choice, choose first host link
                    interface = self.interface_id(ank.server_interface_id(host))
                    cname = "%s.%s" % (interface, host.dns_host_portion_only)
            
                host_cname_list.append( (host.dns_host_portion_only, cname))

            #Sort to make format nicer
            host_cname_list = sorted(host_cname_list, key = lambda x: x[1])
            for_entry_list = sorted(for_entry_list)
            for_entry_list = sorted(for_entry_list, key = lambda x: x[1])
            
            f_forward = open ( os.path.join(bind_dir(self.network, server), "db.%s" % server.domain), 'wb')
            f_forward.write(forward_template.render(
                        domain = server.domain,
                        entry_list = for_entry_list,
                        host_cname_list =  host_cname_list,
                        dns_server = server.dns_hostname,
                        dns_server_ip = ank.server_ip(server),
                ))

            f_reverse = open(os.path.join(bind_dir(self.network, server), "db.%s" % reverse_identifier), 'wb')

            f_reverse.write(reverse_template.render(
                domain = server.domain,
                identifier = reverse_identifier,
                entry_list = rev_entry_list,
                dns_server= server.dns_hostname,
                ))

            #TODO: make l2 use l3 for caching
#TODO: ROOT-SERVER can't be part of a domain...  - need to correctly handle case of multiple root servers
# and also need to handle this for case of single root server (ie no hiearchy) probably ok as /etc/resolv.conf points to server itself, not through dns hints
            root_db_hint = ( ("ROOT-SERVER", ank.server_ip(n)) for n in ank.dns_hiearchy_parents(server))
            f_root = open( os.path.join(bind_dir(self.network, server), "db.root"), 'wb')
            f_root.write( root_template.render( root_servers = root_db_hint))

        for server in dns_servers:
            f_resolv = open( os.path.join(etc_dir(self.network, server), "resolv.conf"), 'wb')
            f_resolv.write ( resolve_template.render(
                nameservers = [ank.server_ip(server)],
                domain = server.domain))

# Configure clients
        for client in clients:
            server_ips = (ank.server_ip(server) for server in ank.dns_hiearchy_parents(client))
            f_resolv = open( os.path.join(etc_dir(self.network, client), "resolv.conf"), 'wb')
            f_resolv.write ( resolve_template.render(
                nameservers = server_ips,
                domain = client.domain))

        return

    def configure(self):
        """Configure Netkit"""
        LOG.info("Configuring Netkit")
        self.configure_netkit()
        self.configure_igp()
        self.configure_bgp()
        self.configure_dns()

        # create .tgz
        tar_filename = "netkit_%s.tar.gz" % time.strftime("%Y%m%d_%H%M", time.localtime())
        tar = tarfile.open(os.path.join(config.ank_main_dir, tar_filename), "w:gz")
# Store using directory structure, eg ank_lab/netkit_lab/
# Note: this differs to Junos which flattens file structure
        tar.add(lab_dir())
        self.network.compiled_labs['netkit'] = tar_filename
        tar.close()

