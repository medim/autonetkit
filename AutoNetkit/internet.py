"""
Internet wrapper for AutoNetkit   
"""
__author__ = """\n""".join(['Simon Knight (simon.knight@adelaide.edu.au)',
                            'Hung Nguyen (hung.nguyen@adelaide.edu.au)'])
#    Copyright (C) 2009-2010 by 
#    Simon Knight  <simon.knight@adelaide.edu.au>
#    Hung Nguyen  <hung.nguyen@adelaide.edu.au>
#    All rights reserved.
#    BSD license.
#
                              
#TODO: use re.compile when using regexes to make faster
 
#TODO: move netkit deploy etc into plugins - provide basic access to a
#netkit machine (local/remote) and rest is scripted from there as a plugin - 
#also move analysis into seperate plugins then
#TODO: configure svn so can store encrypted passwords
#TODO: see if netaddr 0.7.5 fixes pickle issue
#TODO: Setup network to use rsync as default deploy instead of scp

#TODO: Make default plugin expose config and logger
#TODO: add plugins to documentation
#TODO: Can check syntax of plugin by running python compiler across it alone 
#TODO: Write simple plugin manager for network that auto fetches from Internet

import os

import AutoNetkit as ank
from AutoNetkit import network

from netaddr import IPNetwork

import config

import logging
LOG = logging.getLogger("ANK")

#.............................................................................
class Internet:  
    """Create Internet, loading from filename.
    
    Args:
       filename:    file to load network topology from

    Returns:
       None

    Example usage:

    >>> inet = Internet("simple.graphml") 

    """
    
    def __init__(self, filename=None, tapsn=IPNetwork("172.16.0.0/16"),
            netkit=True, cbgp=False, gns3=False, junos=False): 
        self.network = network.Network()
        if isinstance(tapsn, str):
            # Convert to IPNetwork
            #TODO: exception handle this failing eg incorrect subnet
            tapsn = IPNetwork(tapsn)
        self.tapsn = tapsn
        self.compile_targets = {
                'netkit': netkit,
                'cbgp': cbgp,
                'gns3': gns3,
                'junos': junos,
                }
        if filename:
            self.load(filename)
        
        self.services = []
         

    def add_dns(self):        
        """Set compiler to configure DNS.

        Args:
           None

        Returns:
           None

        Example usage:

        >>> inet.add_dns() 

        """
        self.services.append("DNS")   
    
    def load(self, filename):   
        """Loads the network description from a graph file.
        Note this is done automatically if a filename is given to
        the Internet constructor.

        Args:
           filename:    The file to load from

        Returns:
           None

        Example usage:

        >>> inet.load("simple.graphml")

        """
        LOG.info("Loading")
        # Look at file extension
        ext = os.path.splitext(filename)[1]
        if ext == ".gml":
            # GML file from Topology Zoo
            ank.load_zoo(self.network, filename)
        elif ext == ".graphml":
            ank.load_graphml(self.network, filename)
        elif ext == ".yaml":
            # Legacy ANK file format
            LOG.warn("AutoNetkit no longer supports yaml file format")
    
    def plot(self, show=False, save=True): 
        """Plot the network topology

        Args:
           None

        Returns:
           None

        Example usage:

        >>> inet.plot()

        """              
        LOG.info("Plotting")      
        ank.plot(self.network, show, save)        
       
    def save(self):  
        LOG.info("Saving")
        self.network.save()
    
    def optimise(self):   
        """Optimise each AS within the network.

        Args:
           None

        Returns:
           None

        Example usage:

        >>> inet.optimise()

        """
          
        #LOG.info("Optimising")
        #self.network.optimise_igp_weights() 

    def compile(self):             
        """Compile into device configuration files.

          Args:
             None

          Returns:
             None

          Example usage:

          >>> inet.compile()

          """

        
        LOG.info("Compiling")

        # Sanity check
        if self.network.graph.number_of_nodes() == 0:
            LOG.warn("Cannot compile empty network")
            return

# Clean up old archives
        ank.tidy_archives()
      
        #TODO: 
        #config.get_plugin("Inv Cap").run(self.network)   
        #ank.inv_cap_weights(self.network)
        #config.get_plugin("Test").run()
        ank.initialise_bgp(self.network)
        
        # Ensure nodes have a type set
        self.network.update_node_type(default_type="netkit_router")

        # Allocate to machines
        ank.allocate_to_netkit_hosts(self.network)
        
        # Allocations  
        ank.allocate_subnets(self.network, IPNetwork("10.0.0.0/8")) 
        ank.alloc_interfaces(self.network)

        ank.alloc_tap_hosts(self.network, self.tapsn)
        
        # now configure
        if self.compile_targets['netkit']:
            nk_comp = ank.NetkitCompiler(self.network, self.services)
            # Need to allocate DNS servers so they can be configured in Netkit
            if("DNS" in self.services): 
                ank.allocate_dns_servers(self.network)
            nk_comp.initialise()     
            nk_comp.configure()

        if self.compile_targets['gns3']:
            gns3_comp = ank.Gns3Compiler(self.network, self.services)
            gns3_comp.initialise()     
            gns3_comp.configure()

        if self.compile_targets['cbgp']:
            cbgp_comp = ank.CbgpCompiler(self.network, self.services)
            cbgp_comp.configure()

        if self.compile_targets['junos']:
            junos_comp = ank.JunosCompiler(self.network, self.services)
            junos_comp.initialise()
            junos_comp.configure()

    def deploy(self, host, username, xterm = False, platform="netkit" ):  
        """Deploy compiled configuration files."

        Args:
           host:    host to deploy to (if remote machine)
           username: username on remote host
           platform:    platform to deploy to 
           xterm: if to load an xterm window for each VM

        Returns:
           None

        Example usage:

        >>> inet.deploy(host = my_hostname, username = my_username)

        """
        if platform == "netkit":
            import netkit
            LOG.info("Deploying to Netkit")   
            #TODO: make netkit a plugin also
            netkit_server = netkit.Netkit(host, username, tapsn=self.tapsn)

            # Get the deployment plugin
            nkd = ank.NetkitDeploy()
            # Need to tell deploy plugin where the netkit files are
            netkit_dir = config.lab_dir
            nkd.deploy(netkit_server, netkit_dir, self.network, xterm)
        else:
            LOG.warn("Currently only Netkit deployment is supported")

    def verify(self, host, username, platform="netkit" ):  
        """Deploy compiled configuration files."

        Args:
           host:    host to deploy to (if remote machine)
           username: username on remote host
           platform:    platform to deploy to 

        Returns:
           None

        Example usage:

        >>> inet.deploy(host = my_hostname, username = my_username)

        """
        #TODO: implement this 
        #LOG.info("Verifyng Netkit lab")
        #nk = netkit_deploy.NetkitDeploy(host, username)  
        #nkd = config.get_plugin("Netkit Deploy")
        #nkd.verify(self.network)
        pass

