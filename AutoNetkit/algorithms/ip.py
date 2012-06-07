# -*- coding: utf-8 -*-
"""
IP Addressing
"""
__author__ = "\n".join(['Simon Knight'])
#    Copyright (C) 2009-2011 by Simon Knight, Hung Nguyen

__all__ = ['get_ip_as_allocs', 'allocate_subnets', 'alloc_interfaces',
           'alloc_tap_hosts', 'get_tap_host', 'int_id', 'ip_addr',
           'ip_to_net_ent_title_ios', 'create_ip_overlay',
           'ip_to_net_ent_title']

#toDo: add docstrings
from netaddr import IPNetwork, IPAddress
import AutoNetkit as ank
import math
import networkx as nx
import logging
LOG = logging.getLogger("ANK")
import pprint

def create_ip_overlay(network):
    print "creating ip overlay"
    overlay = nx.Graph(network.graph)
    #print [n.device_type for n in overlay.nodes(data=True)]
    for edge in overlay.edges(data=True):
        print edge

def get_ip_as_allocs(network):
    """ Returns list of Subnets allocated, by network"""
    return network.ip_as_allocs

def allocate_subnets(network, address_block=IPNetwork("10.0.0.0/8")):

    """Allocates subnets and IP addresses to links in the network.

    Args:
        address_block (IPNetwork):  The address block to use.

    Returns:
        ip_as_allocs

    Example usage:

    >>> network = ank.example_multi_as()
    >>> allocate_subnets(network)
    >>> print ank.debug_nodes(network.graph, "lo_ip")
    {'1a.AS1': IPNetwork('10.0.0.32/32'),
     '1b.AS1': IPNetwork('10.0.0.33/32'),
     '1c.AS1': IPNetwork('10.0.0.34/32'),
     '2a.AS2': IPNetwork('10.1.0.64/32'),
     '2b.AS2': IPNetwork('10.1.0.65/32'),
     '2c.AS2': IPNetwork('10.1.0.66/32'),
     '2d.AS2': IPNetwork('10.1.0.67/32'),
     '3a.AS3': IPNetwork('10.2.0.0/32')}
    
    >>> print ank.debug_edges(network.graph, "ip")
    {('1a.AS1', '1b.AS1'): IPAddress('10.0.0.10'),
     ('1a.AS1', '1c.AS1'): IPAddress('10.0.0.22'),
     ('1b.AS1', '1a.AS1'): IPAddress('10.0.0.9'),
     ('1b.AS1', '1c.AS1'): IPAddress('10.0.0.26'),
     ('1b.AS1', '3a.AS3'): IPAddress('10.0.0.17'),
     ('1c.AS1', '1a.AS1'): IPAddress('10.0.0.21'),
     ('1c.AS1', '1b.AS1'): IPAddress('10.0.0.25'),
     ('1c.AS1', '2a.AS2'): IPAddress('10.0.0.29'),
     ('2a.AS2', '1c.AS1'): IPAddress('10.0.0.30'),
     ('2a.AS2', '2b.AS2'): IPAddress('10.1.0.10'),
     ('2a.AS2', '2d.AS2'): IPAddress('10.1.0.26'),
     ('2b.AS2', '2a.AS2'): IPAddress('10.1.0.9'),
     ('2b.AS2', '2c.AS2'): IPAddress('10.1.0.18'),
     ('2c.AS2', '2b.AS2'): IPAddress('10.1.0.17'),
     ('2c.AS2', '2d.AS2'): IPAddress('10.1.0.30'),
     ('2d.AS2', '2a.AS2'): IPAddress('10.1.0.25'),
     ('2d.AS2', '2c.AS2'): IPAddress('10.1.0.29'),
     ('2d.AS2', '3a.AS3'): IPAddress('10.1.0.33'),
     ('3a.AS3', '1b.AS1'): IPAddress('10.0.0.18'),
     ('3a.AS3', '2d.AS2'): IPAddress('10.1.0.34')}

    
    >>> print ank.debug_edges(network.graph, "sn")
    {('1a.AS1', '1b.AS1'): IPNetwork('10.0.0.8/30'),
     ('1a.AS1', '1c.AS1'): IPNetwork('10.0.0.20/30'),
     ('1b.AS1', '1a.AS1'): IPNetwork('10.0.0.8/30'),
     ('1b.AS1', '1c.AS1'): IPNetwork('10.0.0.24/30'),
     ('1b.AS1', '3a.AS3'): IPNetwork('10.0.0.16/30'),
     ('1c.AS1', '1a.AS1'): IPNetwork('10.0.0.20/30'),
     ('1c.AS1', '1b.AS1'): IPNetwork('10.0.0.24/30'),
     ('1c.AS1', '2a.AS2'): IPNetwork('10.0.0.28/30'),
     ('2a.AS2', '1c.AS1'): IPNetwork('10.0.0.28/30'),
     ('2a.AS2', '2b.AS2'): IPNetwork('10.1.0.8/30'),
     ('2a.AS2', '2d.AS2'): IPNetwork('10.1.0.24/30'),
     ('2b.AS2', '2a.AS2'): IPNetwork('10.1.0.8/30'),
     ('2b.AS2', '2c.AS2'): IPNetwork('10.1.0.16/30'),
     ('2c.AS2', '2b.AS2'): IPNetwork('10.1.0.16/30'),
     ('2c.AS2', '2d.AS2'): IPNetwork('10.1.0.28/30'),
     ('2d.AS2', '2a.AS2'): IPNetwork('10.1.0.24/30'),
     ('2d.AS2', '2c.AS2'): IPNetwork('10.1.0.28/30'),
     ('2d.AS2', '3a.AS3'): IPNetwork('10.1.0.32/30'),
     ('3a.AS3', '1b.AS1'): IPNetwork('10.0.0.16/30'),
     ('3a.AS3', '2d.AS2'): IPNetwork('10.1.0.32/30')}
    
    """
    LOG.debug("Allocating subnets")
    # Initialise IP list to be graph edge format
    ip_as_allocs = {}

    # allocates subnets to the edges and loopback in network graph
    # Put into dictionary, indexed by ASN (the name attribute of each as graph)
    # for easy appending of eBGP links
    asgraphs = dict((my_as.asn, my_as) for my_as in ank.get_as_graphs(network))

    # Simple method: break address_block into a /16 for each network
    #TODO: check this is feasible - ie against required host count
    subnet_list = address_block.subnet(16)

    ebgp_edges = ank.ebgp_edges(network)
    visited_ebgp_edges = set()
    for src, dst in sorted(ebgp_edges):
      # Add the dst (external peer) to AS of src node so they are allocated
        # a subnet. (The AS choice is arbitrary)
        if (dst, src) in visited_ebgp_edges:
            continue
        src_as = asgraphs[src.asn]
        src_as.add_edge(src, dst)
# record for DNS purposes
        ank.dns_advertise_link(src, dst)
        visited_ebgp_edges.add( (src, dst))

    for my_as in sorted(asgraphs.values(), key = lambda x: x.asn):
        asn = my_as.asn
        as_subnet =  subnet_list.next()

        as_internal_nodes = [n for n in sorted(my_as.nodes()) if network.asn(n) == asn]

        host_count = my_as.number_of_nodes()

        # record this subnet
        ip_as_allocs[my_as.asn] = as_subnet

        # split into subnets for loopback and ptp
        ptp_count = my_as.number_of_edges()

        # Now subnet network into subnets of the larger of these two
        # TODO tidy up this comment
        # Note ptp subnets required a /30 ie 4 ips
        req_sn_count = max(host_count, 4*ptp_count)

        if req_sn_count == 0:
            # Nothing to allocate for this AS
            continue

        req_pref_len = int(32 - math.ceil(math.log(req_sn_count, 2)) )
        # Subnet as subnet into subnets of this size
        sn_iter = as_subnet.subnet(req_pref_len)
        # And allocate a subnet for each ptp and loopback

        if ptp_count > 0:
            # Don't allocate a ptp subnet if there are no ptp links
            ptp_subnet = sn_iter.next()
        loopback_subnet = sn_iter.next()

        if ptp_count > 0:
            link_subnet = ptp_subnet.subnet(30)

            # Now iterate over edges in this as and apply
            for src, dst in sorted(my_as.edges()):
                # Note we apply this back to the main graph
                # not to the as graph!

                subnet = link_subnet.next()

                #TODO: fix the technique for accessing edges
                # as it breaks with multigraphs, as it creates a new edge
                if network.asn(dst) != asn:
# eBGP link where dst has IP allocated from subnet of this AS
                    network.graph[dst][src]['remote_as_sn_block'] = True

                network.graph[src][dst]['sn'] = subnet
                network.graph[dst][src]['sn'] = subnet
                # allocate an ip to each end
                network.graph[src][dst]['ip'] = subnet[1]
                network.graph[dst][src]['ip'] = subnet[2]

        # Allocate an loopback interface to each router
        #TODO: check if next step is necessary
        loopback_ips = loopback_subnet.subnet(32)
    
        for rtr in sorted(as_internal_nodes):
            lo_ip = loopback_ips.next()
            network.graph.node[rtr]['lo_ip'] = lo_ip

    network.ip_as_allocs = ip_as_allocs

def alloc_interfaces(network):
    """Allocated interface IDs for each link in network

    >>> network = ank.example_multi_as()
    >>> alloc_interfaces(network)
    >>> print ank.debug_edges(network.graph, "id")
    {('1a.AS1', '1b.AS1'): 0,
     ('1a.AS1', '1c.AS1'): 1,
     ('1b.AS1', '1a.AS1'): 0,
     ('1b.AS1', '1c.AS1'): 1,
     ('1b.AS1', '3a.AS3'): 2,
     ('1c.AS1', '1a.AS1'): 0,
     ('1c.AS1', '1b.AS1'): 1,
     ('1c.AS1', '2a.AS2'): 2,
     ('2a.AS2', '1c.AS1'): 0,
     ('2a.AS2', '2b.AS2'): 1,
     ('2a.AS2', '2d.AS2'): 2,
     ('2b.AS2', '2a.AS2'): 0,
     ('2b.AS2', '2c.AS2'): 1,
     ('2c.AS2', '2b.AS2'): 0,
     ('2c.AS2', '2d.AS2'): 1,
     ('2d.AS2', '2a.AS2'): 0,
     ('2d.AS2', '2c.AS2'): 1,
     ('2d.AS2', '3a.AS3'): 2,
     ('3a.AS3', '1b.AS1'): 0,
     ('3a.AS3', '2d.AS2'): 1}
    
    """
    LOG.debug("Allocating interfaces")
    for rtr in sorted(network.graph):
        for index, (src, dst) in enumerate(sorted(network.graph.edges(rtr))):
            network.graph[src][dst]['id'] = index

def get_tap_host(network):
    """ Returns tap host in network """
    return network.tap_host

def alloc_tap_hosts(network, address_block=IPNetwork("172.16.0.0/16")):
    """Allocates TAP IPs for connecting using Netkit

    >>> network = ank.example_multi_as()
    >>> alloc_tap_hosts(network)
    >>> print ank.debug_nodes(network.graph, "tap_ip")
    {'1a.AS1': IPAddress('172.16.1.1'),
     '1b.AS1': IPAddress('172.16.1.2'),
     '1c.AS1': IPAddress('172.16.1.3'),
     '2a.AS2': IPAddress('172.16.2.1'),
     '2b.AS2': IPAddress('172.16.2.2'),
     '2c.AS2': IPAddress('172.16.2.3'),
     '2d.AS2': IPAddress('172.16.2.4'),
     '3a.AS3': IPAddress('172.16.3.1')}
    """
    LOG.debug("Allocating TAP hosts")
    network.tap_sn = address_block

    as_graph = ank.get_as_graphs(network)
    # Try allocating /24 to each subnet as cleaner
    # then check if this is feasible 
    prefix_len = 24
    # Check this will fit into provided network
    #TODO: check what these 2 lines of code are doing
    if prefix_len <= address_block.prefixlen:
        # Try with smaller prefix len
        prefix_len += 1
   
    # Number of bits required for AS subnet (network bits)
    # need to add one on for tap host subnet, eg 172.16.0.0 and 172.16.0.1 hosts
    req_network_bits = int( math.ceil(math.log(len(as_graph) + 1, 2)) )
    upper_bound = prefix_len 
    # Find the subnet with the most hosts in it

    max_req_hosts = max(len(my_as) for my_as in as_graph)
    req_host_bits = int(math.ceil(math.log(max_req_hosts, 2)))
#TODO: there is an off by one error here mking the tap subnets /9 rather than /8
# so end up with 172.16.64.1 and 172.16.128.1 not .1 .2 etc

    # Check subnetting is feasible
    lower_bound = address_block.prefixlen + req_network_bits
    upper_bound = lower_bound + req_host_bits
    if upper_bound > 32:
        #TODO: throw error
        print "Unfeasible tap subnet allocation"
        return
    else:
        prefix_len = lower_bound

    # Neatness: use a Class C, B, A (in order of preference) if feasible
    for x in [24, 16, 8]:
        if lower_bound < x < upper_bound:
            prefix_len = x
        elif lower_bound < upper_bound < x:
# eg both fit inside a class A, B or C
            prefix_len = x

    def set_tap_ips(network, nodes, host_ips):
        # Allocate in order of node name
        for node in sorted(nodes, key=network.label):
            network.graph.node[node]['tap_ip'] = host_ips.next()
        return

    # assign /required subnet size to each as then append pops to list
    if len(as_graph) == 1:
        # Single AS, don't need to subnet the address block
        host_ips = address_block.iter_hosts()
        network.tap_host = host_ips.next()
        _ = host_ips.next() # IP of tap VM
        my_as = as_graph.pop()
        # Allocate directly from address block
        set_tap_ips(network, my_as.nodes(), host_ips)
    else:
        sn_iter = address_block.subnet(prefix_len)
        tap_host_subnet = sn_iter.next()
        #TODO: make consistent with previous section [1] vs .next()
        network.tap_host = tap_host_subnet[1]
        for my_as in as_graph:
            LOG.debug("Setting tap IPs for %s" % my_as.asn)
            host_ips = sn_iter.next().iter_hosts()
            set_tap_ips(network, my_as.nodes(), host_ips)
        
    #TODO: make this a generic function which allocates items from an
    # generator to each node in the specified network
    # rather than IP addresses specifically
    return

def int_id(network, src, dst):
    return network.graph[src][dst]['id']

def ip_addr(network, src, dst):
    return network.graph[src][dst]['ip']

def ip_to_net_ent_title(ip):
    """ Converts an IP address into an OSI Network Entity Title
    suitable for use in IS-IS on Junos.

    >>> ip_to_net_ent_title(IPAddress("192.168.19.1"))
    '49.0001.1921.6801.9001.00'
    """
    LOG.debug("Converting IP to OSI ENT format")
    area_id = "49.0001"
# Pad with leading zeros, eg 1->001, 12->012, 123->123
    ip_octets = ["%03d" % int(octet) for octet in ip.words]
# Condense to single string
    ip_octets = "".join(ip_octets)
# and split into bytes
    ip_octets = ip_octets[0:4] + "." + ip_octets[4:8] + "." + ip_octets[8:12]
    return area_id + "." + ip_octets + "." + "00"


def ip_to_net_ent_title_ios(ip):
    """ Converts an IP address into an OSI Network Entity Title
    suitable for use in IS-IS on IOS.

    >>> ip_to_net_ent_title_ios(IPAddress("192.168.19.1"))
    '49.1921.6801.9001.00'
    """
    LOG.debug("Converting IP to OSI ENT format")
    area_id = "49"
# Pad with leading zeros, eg 1->001, 12->012, 123->123
    ip_octets = ["%03d" % int(octet) for octet in ip.words]
# Condense to single string
    ip_octets = "".join(ip_octets)
# and split into bytes
    ip_octets = ip_octets[0:4] + "." + ip_octets[4:8] + "." + ip_octets[8:12]
    return area_id + "." + ip_octets + "." + "00"
