# -*- coding: utf-8 -*-
"""
Plotting
"""
__author__ = "\n".join(['Simon Knight'])
#    Copyright (C) 2009-2011 by Simon Knight, Hung Nguyen

__all__ = ['jsplot']

import networkx as nx
import AutoNetkit as ank
import logging
import os

from mako.lookup import TemplateLookup

# TODO: merge these imports but make consistent across compilers
from pkg_resources import resource_filename
import pkg_resources

import os

#import network as network

LOG = logging.getLogger("ANK")

import shutil
import glob
import itertools

import AutoNetkit as ank
from AutoNetkit import config

import pprint
pp = pprint.PrettyPrinter(indent=4)

# Check can write to template cache directory
#TODO: make function to provide cache directory
#TODO: move this into config
template_cache_dir = config.template_cache_dir

template_dir =  resource_filename("AutoNetkit","lib/templates")
lookup = TemplateLookup(directories=[ template_dir ],
        module_directory= template_cache_dir,
        #cache_type='memory',
        #cache_enabled=True,
        )


from AutoNetkit import config
settings = config.settings

LOG = logging.getLogger("ANK")

#TODO: add option to show plots, or save them


def jsplot(network, show=False, save=True):
    """ Plot the network """
    plot_dir = config.plot_dir
    if not os.path.isdir(plot_dir):
        os.mkdir(plot_dir)
    jsplot_dir = os.path.join(plot_dir, "jsplot")
    if not os.path.isdir(jsplot_dir):
        os.mkdir(jsplot_dir)

    js_template = lookup.get_template("arborjs/main_js.mako")
    css_template = lookup.get_template("arborjs/style_css.mako")
    html_template = lookup.get_template("arborjs/index_html.mako")

    node_list = {}
    node_list = dict( (node, data) for node, data in network.graph.nodes(data=True))
    edge_list = dict( ((src, dst), data) for src, dst, data in network.graph.edges(data=True))
    node_list = network.graph.nodes(data=True)
    edge_list = network.graph.edges(data=True)

    js_filename = os.path.join(jsplot_dir, "main.js")
    with open( js_filename, 'w') as f_js:
            f_js.write( js_template.render(
                node_list = node_list,
                edge_list = edge_list,
                ))

    html_filename = os.path.join(jsplot_dir, "index.html")
    with open( html_filename, 'w') as f_html:
            f_html.write( html_template.render())

    css_filename = os.path.join(jsplot_dir, "style.css")
    with open( css_filename, 'w') as f_css:
            f_css.write( css_template.render())

    arbor_js_src_filename = os.path.join(template_dir, "arborjs", "arbor.js")
    arbor_js_dst_filename = os.path.join(jsplot_dir, "arbor.js")
    shutil.copy(arbor_js_src_filename, arbor_js_dst_filename)

