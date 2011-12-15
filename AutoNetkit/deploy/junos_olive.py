# -*- coding: utf-8 -*-
"""
Deploy a given Netkit lab to a Netkit server
"""
__author__ = "\n".join(['Simon Knight'])
#    Copyright (C) 2009-2011 by Simon Knight, Hung Nguyen, Askar Jaboldinov 

import logging
LOG = logging.getLogger("ANK")
                                 
                                 

import time
import os
import time
import AutoNetkit.config as config
import pxssh
import sys

# Used for EOF and TIMEOUT variables
import pexpect

LINUX_PROMPT = "~#"   

from mako.lookup import TemplateLookup
from pkg_resources import resource_filename

template_cache_dir = config.template_cache_dir

template_dir =  resource_filename("AutoNetkit","lib/templates")
lookup = TemplateLookup(directories=[ template_dir ],
        module_directory= template_cache_dir,
        #cache_type='memory',
        #cache_enabled=True,
        )

class OliveDeploy():  
    """ Deploy a given Junos lab to an Olive Host"""

    def __init__(self, host=None, username=None):
        self.server = None    
        self.lab_dir = None
        self.network = None
        self.host = host
        self.username = username
        self.shell = None
        self.shell_type ="bash"
        self.logfile = open( os.path.join(config.log_dir, "pxssh.log"), 'w')

    def connect_to_server(self):  
        """Connects to Netkit server (if remote)"""   
        
        #TODO: make internal (private) function
        
        #TODO: check state is disconnected
        
        # Connects to the Linux machine running the Netkit lab   
        shell = None     
        if self.host and self.username:  
            # Connect to remote machine

            ssh_link = self.shell
            if ssh_link != None: 
                # ssh_link already set
                return ssh_link

            shell = pxssh.pxssh()    
            shell.logfile = self.logfile
            LOG.info(  "Connecting to {0}".format(self.host) ) 

            shell.login(self.host, self.username)
            # with pass: shell.login(self.host, self.username, self.password)

            LOG.info(  "Connected to " + self.host )  
            #TODO: set state to Netkit
        else:   
            shell = pexpect.spawn (self.shell_type) 
            shell.sendline("uname")
            
            shell.logfile = self.logfile    
            shell.setecho(True)  
            # Check Linux machine (Netkit won't run on other Unixes)   
            i = shell.expect(["Linux", "Darwin", pexpect.EOF, LINUX_PROMPT]) 
            if i == 0:
                # Machine is running Linux. Send test command (ignore result)
                shell.sendline("ls") 
            elif i == 1:
                LOG.warn("Specified Netkit host is running Mac OS X, "
                    "please specify a Linux Netkit host.")
                return None 
            else:
                LOG.warn("Provided Netkit host is not running Linux")

        self.shell = shell   
        return

    def check_required_programs(self):
        # check prerequisites
        shell = self.shell
        for program in ['tunctl', 'vde_switch', 'qemu', 'qemu-img', 'mkisofs']:
            chk_cmd = 'hash %s 2>&- && echo "Present" || echo >&2 "Absent"\n' % program
            shell.sendline(chk_cmd)
            program_installed = shell.expect (["Absent", "Present"])    
            if program_installed:
                print "%s installed" % program
            else:
                #TODO: convert print to LOGs
                print "%s not installed" % program
                return False
            shell.prompt() 

    def start_olive(self):
        """ Starts Olives inside Qemu
        Steps:
        1. Create bash script to start the Olives
        2. Copy bash script to remote host
        3. Start bash script as sudo
        """
        shell = self.shell
        print "starting olives"

        base_image = "/space/base-image.img"
        snapshot_folder = "/space/snapshots"
# need to create this folder if not present
        socket_folder = "/space/sockets"
        test_folder = "/space/test"
        required_folders = [snapshot_folder, socket_folder, test_folder]
        shell.setecho(False)
        for folder in required_folders:
                shell.sendline('[ -d ' + folder + ' ] && echo >&2 "Present" || echo >&2 "Absent"\n')
                folder_exists = shell.expect (["Absent", "Present"])    
                print "folder %s exists %s " % (folder, folder_exists)
                if folder_exists:
                    print "%s exists" % folder
                else:
                    #TODO: convert print to LOGs
                    print "%s not exists" % folder
                shell.prompt() 


# need to create this folder if not present
        #config_folder 

        return


        bash_template = lookup.get_template("autonetkit/olive_startup.mako")
        junos_dir = config.junos_dir
        if not os.path.isdir(junos_dir):
            os.mkdir(junos_dir)
        bash_script_filename = os.path.join(junos_dir, "start_olive.sh")
        with open( bash_script_filename, 'w') as f_bash:
            f_bash.write( bash_template.render(
                test = "AAAAAAA",
                ))
        
    def start_switch(self):
        tap_name = "ank_tap_olive"
        vde_socket_name = "ank_vde_olive"
        vde_mgmt_socket_name = "ank_vde_olive_mgmt"
        shell = self.shell

        print "Please enter sudo password and type '^]' to return to AutoNetkit"
        shell.sendline('sudo tunctl -t %s' % tap_name)
	sys.stdout.write (shell.after)
	sys.stdout.flush()
        shell.interact()
        print
        print "Starting vde_switch"

# start vde switch
        start_vde_switch_cmd = "vde_switch -d -t %s -n 2000 -s /tmp/%s -M /tmp/%s" % (tap_name, 
                vde_socket_name, vde_mgmt_socket_name)
        shell.sendline('sudo %s' % start_vde_switch_cmd)
        i = shell.expect ([
            "vde_switch: Could not bind to socket '/tmp/%s/ctl': Address already in use"%vde_socket_name,
                pexpect.EOF])
        if i:
# started ok
            pass
        else:
            print "vde_switch already running"

        return





olive_deploy = OliveDeploy(host="trc1", username="sknight")
olive_deploy.connect_to_server()
olive_deploy.check_required_programs()
#olive_deploy.start_switch()
olive_deploy.start_olive()
