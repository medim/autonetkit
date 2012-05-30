# -*- coding: utf-8 -*-
"""
Parse BGP policy from a file. 


Example Policies::

    (asn = 1) egress-> (node = a.b): (if Origin(asn=2) then addTag a100)
    (asn = 1) egress-> (asn = 2): (if tags contain abc then setMED 200)
    (asn = 1) egress-> (asn = 2): (if tag = cde then addTag a300) else (if tag = def then setMED 200) 
    (asn = 1) egress-> (asn = 2): (if tag = ghi then addTag a300)           
    (asn = 2) ->ingress (asn = 1): (if tag = xyz then setLP 100)          
    (asn = 2) ->ingress (asn = 1): (if tag = zzz then setLP 150 & reject route)    

    importLibrary library.txt

    includePolicy somefile.txt 

    (asn =1 ) ->ingress (asn=2): (setLP 200)         
    (asn = 1) egress-> (asn = 3): (if Transit(asn = 2) then addTag t_test)
    (asn = 1) egress-> (asn = 3): (if Origin(asn = 2) then addTag o_test)             
    (asn = 1) egress-> (asn = 2): (if tag = abc then reject route)       

.. warning::

    Work in progress.

"""
__author__ = "\n".join(['Simon Knight'])
#    Copyright (C) 2009-2012 by Simon Knight, Hung Nguyen

import networkx as nx
import logging
import AutoNetkit as ank
import os
from AutoNetkit import config
LOG = logging.getLogger("ANK")
#TODO: only import from pyparsing what is needed
from pyparsing import Literal, Word, alphas, alphanums, nums, Combine, Group, ZeroOrMore, Suppress, quotedString, removeQuotes, oneOf, Forward, Optional, delimitedList
import pyparsing
import operator
import pprint
import itertools
import re
from collections import namedtuple

LOG = logging.getLogger("ANK")


def tag_to_pl(tag):
    """Adds prefix list prefix to tag

    >>> tag_to_pl("network_eq_as1")
    'pl_network_eq_as1'
    """
    return "pl_%s" % tag

def tag_to_cl(tag):
    """Adds community list prefix to tag

    >>> tag_to_cl("network_eq_as1")
    'cl_network_eq_as1'
    
    """
    return "cl_%s" % tag

def parse_fail_action(s,loc,expr,err):
    #TODO: make this LOG.debug not info
    LOG.info('Parse error at %s' % s[loc:])
    raise pyparsing.ParseFatalException('Error at %s' % s[loc:])
    return


#TODO: see if can return in a data structure that pretty-print works nicely on
class match_tuple (namedtuple('match_tuple', "match_clauses, action_clauses, reject")):
    __slots__ = ()
    def __repr__(self):
        return "if %s then %s reject: %s" % (self.match_clauses, self.action_clauses, self.reject)

class match_tuple_with_seq_no (namedtuple('match_tuple', "seq_no, match_clauses, action_clauses, reject")):
    __slots__ = ()
    def __repr__(self):
        return "seq %s if %s then %s reject: %s" % (self.seq_no, 
                self.match_clauses, 
                self.action_clauses, 
                self.reject)

class route_map_tuple (namedtuple('route_map', "name, match_tuples")):
    __slots__ = ()
    def __repr__(self):
        return "%s %s" % (self.name, self.match_tuples)

class match_clause (namedtuple('match_clause', 'type, comparison, value')):
    __slots__ = ()
    def __repr__(self):
        return "%s %s %s" % (self.type, self.comparison, self.value)

class action_clause (namedtuple('action_clause', 'action, value')):
    __slots__ = ()
    def __repr__(self):
        return "%s %s" % (self.action, self.value)


class BgpPolicyParser:
    """Parser class"""
    def __init__(self, network):
        self.network = network
        self.g_business_relationship = nx.DiGraph()
        self.user_defined_sets = {}
        self.user_library_calls = []
        self.user_defined_functions = {}

        # Grammars
#TODO: tidy this up
        attribute_unnamed = Word(alphanums+'_'+".")
        attribute = attribute_unnamed.setResultsName("attribute")
        self.attribute = attribute

        lt = Literal("<").setResultsName("<")
        le = Literal("<=").setResultsName("<=")
        eq = Literal("=").setResultsName("=")
        ne = Literal("!=").setResultsName("!=")
        ge = Literal(">=").setResultsName(">=")
        gt = Literal(">").setResultsName(">")
        wildcard = Literal("*").setResultsName("wildcard")
        self.wildcard = wildcard

        self.prefix_lists = {}
        self.tags_to_allocate = set()
        self.allocated_tags = {}

        self._opn = {
                '<': operator.lt,
                '<=': operator.le,
                '=': operator.eq,
                '!=': operator.ne,
                '>=': operator.ge,
                '>': operator.gt,
                '&': set.intersection,
                '|': set.union,
                }

        # map alphanum chars to alphanum equivalents for use in tags
        self._opn_to_tag = {
                '<': "lt",
                '<=': "le",
                '=': "eq",
                '!=': "ne",
                '>=': "ge",
                '>': "gt",
                '&': "and",
                '|': "or",
                }

# Both are of comparison to access in same manner when evaluating
        comparison = (lt | le | eq | ne | ge | gt).setResultsName("comparison")
        stringComparison = (eq | ne).setResultsName("comparison")
#
#quoted string is already present
        float_string = Word(nums).setResultsName("value").setParseAction(lambda t: float(t[0]))
        integer_string = Word(nums).setResultsName("value").setParseAction(lambda t: int(t[0]))
#TODO: use numString, and make integer if fiull stop

#TODO: allow parentheses? - should be ok as pass to the python parser
        ipField = Word(nums, max=3)
        ipAddress = Combine( ipField + "." + ipField + "." + ipField + "." + ipField ).setResultsName("ipAddress")

        boolean_and = Literal("&").setResultsName("&")
        boolean_or = Literal("|").setResultsName("|")
        boolean = (boolean_and | boolean_or).setResultsName("boolean")
        self._boolean = boolean # need to use in checking

#TODO fix this matching 2a.ab when that should match a string
        numericQuery = Group(attribute + comparison + float_string).setResultsName( "numericQuery")


        stringValues = (attribute_unnamed | quotedString.setParseAction(removeQuotes)
                ).setResultsName("value")

        stringQuery =  Group(attribute + stringComparison + stringValues).setResultsName( "stringQuery")
        wildcardQuery = wildcard.setResultsName("wildcardQuery")

        singleQuery = numericQuery | stringQuery | wildcardQuery
        singleQuery.setFailAction(parse_fail_action)
        self.nodeQuery = singleQuery + ZeroOrMore(boolean + singleQuery)

        self.u_egress = Literal("egress->").setResultsName("u_egress") 
        self.v_ingress = Literal("->ingress").setResultsName("v_ingress")
        self.u_ingress = Literal("ingress<-").setResultsName("u_ingress")
        self.v_egress = Literal("<-egress").setResultsName("v_egress") 
        edgeType = ( self.u_egress | self.u_ingress | self.v_egress
                | self.v_ingress).setResultsName("edgeType").setFailAction(parse_fail_action)
        self.edgeQuery = ("(" + self.nodeQuery.setResultsName("query_a") + ")"
                + edgeType
                + "(" + self.nodeQuery.setResultsName("query_b")
                + ")").setFailAction(parse_fail_action)

#start of BGP queries
        originQuery = (Literal("Origin").setResultsName("attribute") + 
                #this is a workaround for the match, comparison, value 3-tuple in processing
                Literal("(").setResultsName("comparison") +  
                Group(self.nodeQuery).setResultsName("value") + Suppress(")")).setResultsName("originQuery")
        transitQuery = (Literal("Transit").setResultsName("attribute") +
                #this is a workaround for the match, comparison, value 3-tuple in processing
                Literal("(").setResultsName("comparison") +  
                Group(self.nodeQuery).setResultsName("value") + Suppress(")")).setResultsName("transitQuery")

        prefixList = Literal("prefix_list")
        matchPl = (prefixList.setResultsName("attribute")
                + comparison
                + attribute.setResultsName("value"))

        matchTag = (Literal("tag").setResultsName("attribute")
                + comparison
                + attribute.setResultsName("value"))


        #tags contain -> tag = aaa
        inTags = (                Literal("tags").setResultsName("attribute").setParseAction(lambda x: "tag")
                + Literal("contain").setResultsName("comparison").setParseAction(lambda x: "=")
                + attribute_unnamed.setResultsName("value")
                )

        bgpMatchQuery = Group(matchPl | matchTag | inTags | originQuery | transitQuery ).setResultsName("bgpMatchQuery").setFailAction(parse_fail_action)
        self.bgpMatchQuery = bgpMatchQuery

        setLP = (Literal("setLP").setResultsName("attribute") 
                + integer_string.setResultsName("value")).setResultsName("setLP")
        setMED = (Literal("setMED").setResultsName("attribute") 
                + integer_string.setResultsName("value")).setResultsName("setMED")

        addTag = (Literal("addTag").setResultsName("attribute") 
                + attribute.setResultsName("value")).setResultsName("addTag")
        removeTag = (Literal("removeTag").setResultsName("attribute") 
                + attribute.setResultsName("value")).setResultsName("removeTag")
        #TODO: need to set blank value
        reject = Literal("reject")
#TODO: remove once move quagga output inside module
        self.reject = reject
        rejectAction = (reject.setResultsName("attribute") +
                Literal("route").setResultsName("value")).setResultsName("reject")
        setNextHop = (Literal("setNextHop").setResultsName("attribute") + ipAddress.setResultsName("value")).setResultsName("setNextHop")

        setOriginAttribute = (Literal("setOriginAttribute").setResultsName("attribute") 
                + (oneOf("IGP BGP None").setResultsName("value"))).setResultsName("setOriginAttribute")

        bgpAction = Group(addTag | setLP | setMED | removeTag |
                setNextHop | setOriginAttribute | rejectAction).setResultsName("bgpAction")

        # The Clauses
        ifClause = Group(Suppress("if") + bgpMatchQuery 
                + ZeroOrMore(Suppress(boolean_and)
                    + bgpMatchQuery)).setResultsName("if_clause")

        actionClause = bgpAction + ZeroOrMore(Suppress(boolean_and) + bgpAction)
        thenClause = Group(Suppress("then") + actionClause).setResultsName("then_clause")
        ifThenClause = Group(Suppress("(") + 
                ifClause + thenClause + Suppress(")")).setResultsName("ifThenClause")
        elseActionClause = Group(Suppress("(") + actionClause 
                + Suppress(")")).setResultsName("else_clause")
# Support actions without a condition (ie no "if")
        unconditionalAction =  Group(Suppress("(")
            + Group(actionClause).setResultsName("unconditionalActionClause")
            + Suppress(")")).setResultsName("bgpSessionQuery")

# Query may contain itself (nested)
        bgpSessionQuery = Forward()
        bgpSessionQuery << ( ifThenClause +
                Optional( Suppress("else") + (elseActionClause | bgpSessionQuery))
                ).setResultsName("bgpSessionQuery")
        bgpSessionQuery =  bgpSessionQuery | unconditionalAction
        self.bgpSessionQuery = bgpSessionQuery

        self.bgpApplicationQuery = self.edgeQuery + Suppress(":") + self.bgpSessionQuery

# Library stuff
        set_values = Suppress("{") + delimitedList( attribute, delim=',').setResultsName("set_values") + Suppress("}")
#Set to empty set, rather than empty list as empty list is processed differently somewhere in parser
        empty_set = Literal("{}").setResultsName("set_values").setParseAction(lambda x: set())
        self.set_definition = attribute.setResultsName("set_name") + Suppress("=") + (empty_set | set_values)

        library_params = attribute | Group(set_values) | empty_set
        library_function = attribute.setResultsName("def_name") + Suppress("(") + delimitedList( library_params, delim=',').setResultsName("def_params") + Suppress(")")
        library_function.setFailAction(parse_fail_action)

        self.library_def = Suppress("define") + library_function

        self.library_call = Suppress("apply") + library_function
        self.library_def.setFailAction(parse_fail_action)
        self.library_edge_query = (self.attribute.setResultsName("query_a")
                + edgeType + self.attribute.setResultsName("query_b"))
        self.library_edge_query.setFailAction(parse_fail_action)
        library_edge_definition = self.library_edge_query + Suppress(":") + self.bgpSessionQuery
        library_global_definition = "global tags = {" + delimitedList( attribute, delim=',').setResultsName("tags") + "}"
        self.library_entry = library_global_definition.setResultsName("global_tags") | library_edge_definition.setResultsName("library_edge")
        self.library_entry.setFailAction(parse_fail_action)

        self.bgpPolicyLine = (
                self.bgpApplicationQuery.setResultsName("bgpApplicationQuery")
                | self.library_call.setResultsName("library_call")
                | self.set_definition.setResultsName("set_definition")
                )


        #TODO: allow shorthand of (1) -> (2) for (asn=1) -> (asn=2)

    def clear_policies(self):
        for src, dst in self.network.g_session.edges():
            self.network.g_session[src][dst]['ingress'] = []
            self.network.g_session[src][dst]['egress'] = []


    def apply_bgp_policy(self, qstring):
        """Applies policy to network 

        >>> inet = ank.internet.Internet("2routers") 
        >>> inet.compile()
        >>> node_a = inet.network.find("a.AS1")
        >>> node_b = inet.network.find("b.AS2")
        >>> pol_parser = ank.BgpPolicyParser(inet.network)

        >>> pol_parser.apply_bgp_policy("(asn=1) ->ingress (asn=2): (setLP 200)")
        >>> inet.network.g_session[node_a][node_b]['ingress']
        [[if [] then [setLP 200] reject: False]]

        >>> pol_parser.clear_policies()
        >>> pol_parser.apply_bgp_policy("(asn=1) ->ingress (asn=2): (setMED 200)")
        >>> inet.network.g_session[node_a][node_b]['ingress']
        [[if [] then [setMED 200] reject: False]]

        >>> pol_parser.clear_policies()
        >>> pol_parser.apply_bgp_policy("(asn=1) ->ingress (*): (setMED 200)")
        >>> inet.network.g_session[node_a][node_b]['ingress']
        [[if [] then [setMED 200] reject: False]]

        >>> pol_parser.clear_policies()
        >>> pol_parser.apply_bgp_policy("(asn=1) ->ingress (asn=2): (if tag = test then setLP 100)")
        >>> inet.network.g_session[node_a][node_b]['ingress']
        [[if [tag = test] then [setLP 100] reject: False]]

        >>> pol_parser.clear_policies()
        >>> pol_parser.apply_bgp_policy("(asn=1) ->ingress (asn=2): (if tags contain test then setLP 100)")
        >>> inet.network.g_session[node_a][node_b]['ingress']
        [[if [tag = test] then [setLP 100] reject: False]]

        >>> pol_parser.clear_policies()
        >>> pol_parser.apply_bgp_policy("(asn=1) ->ingress (asn=2): (if prefix_list = pl_asn_eq_2 then addTag cl_asn_eq_2))")
        >>> inet.network.g_session[node_a][node_b]['ingress']
        [[if [prefix_list = pl_asn_eq_2] then [addTag cl_asn_eq_2] reject: False]]
        
        >>> pol_parser.clear_policies()
        >>> pol_parser.apply_bgp_policy("(asn=1) ->ingress (asn=2): (addTag ABC & setLP 90))")
        >>> inet.network.g_session[node_a][node_b]['ingress']
        [[if [] then [addTag ABC, setLP 90] reject: False]]

        >>> pol_parser.clear_policies()
        >>> pol_parser.apply_bgp_policy("(asn=1) ->ingress (asn=2): (if Origin(asn=2) then addTag a100 ))")
        >>> inet.network.g_session[node_a][node_b]['ingress']
        [[if [tag = origin_cl_asn_eq_2] then [addTag a100] reject: False]]

        >>> pol_parser.clear_policies()
        >>> pol_parser.apply_bgp_policy("(asn=1) ->ingress (asn=2): (if Transit(asn=2) then addTag a100 ))")
        >>> inet.network.g_session[node_a][node_b]['ingress']
        [[if [tag = transit_cl_asn_eq_2] then [addTag a100] reject: False]]

        >>> pol_parser.clear_policies()
        >>> pol_parser.apply_bgp_policy("(asn=1) ->ingress (asn=2): (if Transit(asn=2) then addTag a100 ))")
        >>> inet.network.g_session[node_a][node_b]['ingress']
        [[if [tag = transit_cl_asn_eq_2] then [addTag a100] reject: False]]

        >>> pol_parser = ank.BgpPolicyParser(ank.network.Network(ank.load_example("multias")))

#TODO: move these tests out

        Testing internals:

        >>> attributestring = "2a.as1"
        >>> result = pol_parser.attribute.parseString(attributestring)

        Node and edge queries::

        >>> nodestring = "node = '2ab.ab'"
        >>> result = pol_parser.nodeQuery.parseString(nodestring)
        >>> result = pol_parser.edgeQuery.parseString("(" + nodestring + ") egress-> (node = b)")
        >>> result = pol_parser.edgeQuery.parseString("(node = a.b) egress-> (node = b)")

        Full policy queries::

        >>> pol_parser.apply_bgp_policy("(node = '2a.AS2') egress-> (*): (if prefix_list = pl_asn_eq_2 then addTag cl_asn_eq_2)")
        >>> pol_parser.apply_bgp_policy("(Network = AS1 ) ->ingress (Network = AS2): (if tag = deprefme then setLP 90) ")
        >>> pol_parser.apply_bgp_policy("(Network = AS1 ) ->ingress (Network = AS2): (addTag ABC & setLP 90) ")
        >>> pol_parser.apply_bgp_policy("(asn = 1) egress-> (asn = 1): (if Origin(asn=2) then addTag a100 )")
        >>> pol_parser.apply_bgp_policy("(asn = 1) egress-> (asn = 1): (if Transit(asn=2) then addTag a100 )")
        >>> pol_parser.apply_bgp_policy("(node = a_b ) ->ingress (Network = AS2): (addTag ABC & setLP 90) ")
        >>> pol_parser.apply_bgp_policy("(node = a_b ) ->ingress (Network = AS2): (if Transit(asn=2) then addTag a100 ) ")
        """
        LOG.debug("Applying BGP policy %s" % qstring)
        result = self.bgpPolicyLine.parseString(qstring)
        if 'set_definition' in result:
            LOG.debug("Storing set definition %s" % result.set_name)
            self.user_defined_sets[result.set_name] = set(a for a in result.set_values)
            return
        if 'library_call' in result:
            def_params = []
            for param in result.def_params:
                if isinstance(param, basestring):
                    def_params.append(param)
                else:
# is a sequence, extract value
                    def_params.append([p for p in param])

            self.user_library_calls.append( (result.def_name, def_params))
            return

        LOG.debug("Query string is %s " % qstring)
        set_a = self.node_select_query(result.query_a)
        LOG.debug("Set a is %s " % set_a)
        set_b = self.node_select_query(result.query_b)
        LOG.debug("Set b is %s " % set_b)
        select_type = result.edgeType
        per_session_policy = self.process_if_then_else(result.bgpSessionQuery)

# use nbunch feature of networkx to limit edges to look at
        node_set = set_a | set_b

        edges = self.network.g_session.edges(node_set)
        #LOG.debug("Edges are %s " % edges)
# 1 ->, 2 <-, 3 <->

        def select_fn_u_to_v( (u, v), src_set, dst_set):
            """ u -> v"""
            return (u in src_set and v in dst_set)

        def select_fn_u_from_v( (u, v), src_set, dst_set):
            """ u <- v"""
            return (u in dst_set and v in src_set)

        def select_fn_v_to_from_u( (u, v), src_set, dst_set):
            """ u <-> v"""
            return (u in src_set and v in dst_set) or (u in dst_set and v in src_set)

        if select_type in [self.u_egress, self.v_ingress]:
# u -> v
            select_function = select_fn_u_to_v
        if select_type in [self.u_ingress, self.v_egress]:
# u <- v
            select_function = select_fn_u_from_v

        # Determine which direction to apply policy to
        ingress_or_egress = None
        if select_type in [self.u_ingress, self.v_ingress]:
            ingress_or_egress = 'ingress'
        if select_type in [self.u_egress, self.v_egress]:
            ingress_or_egress = 'egress'

        # apply policy to edges
        selected_edges = list( e for e in edges if select_function(e, set_a, set_b))
        LOG.debug("Selected edges are %s" % selected_edges)
        for u,v in selected_edges:
            LOG.debug("Applying policy %s to %s of %s->%s" % ( per_session_policy, ingress_or_egress, 
                self.network.fqdn(u), self.network.fqdn(v)))
            self.network.g_session[u][v][ingress_or_egress].append(per_session_policy)

    def evaluate_node_stack(self, stack):
        """Evaluates a stack of nodes with join queries"""
        LOG.debug("Evaluating node stack %s" % stack)
        if len(stack) == 1:
            return set(stack.pop())
        else:
            a = set(stack.pop())
            op = stack.pop()
            return self._opn[op](a, self.evaluate_node_stack(stack))

    def node_select_query(self, qstring):
        """
        >>> pol_parser = ank.BgpPolicyParser(ank.network.Network(ank.load_example("multias")))
        >>> pol_parser.node_select_query("asn = 1")
        set(['n0', 'n1', 'n3'])
        >>> pol_parser.node_select_query("name = a.b")
        set([])
        >>> pol_parser.node_select_query("name = a_b")
        set([])
        """
        LOG.debug("Processing node select query %s" % qstring)
        if isinstance(qstring, str):
            result = self.nodeQuery.parseString(qstring)
        else:
# don't parse as likely came from edge parser
            result = qstring

#TODO: rearrange so remove stack and iterate over nodes only once
# so execute the boolean as function, rather than using stack on node sets
# ie test each node for all the required matches in one step
# and use data(=True) so get the dictionary reference once -> faster
# especially if using short circuits so when False stop executing

        def comp_fn_string(token, n):
            #TODO: allow partial string matches - beginswith, endswith, etc - map to python functions
            return self._opn[token.comparison](self.network.graph.node[n].get(token.attribute), token.value)

        def comp_fn_numeric(token, n):
            return self._opn[token.comparison](float(self.network.graph.node[n].get(token.attribute)), token.value)

        stack = []

        for token in result:
            if token in self._boolean:
                stack.append(token)
                continue

# different function depending on value type: numeric or string
            if token == self.wildcard:
                result_set = set(n for n in self.network.routers() )
                stack.append(result_set)
                continue
            elif token.attribute == "node":
                result_set = set([token.value])
                stack.append(result_set)
                continue
            elif isinstance(token.value, str):
                comp_fn = comp_fn_string
            elif isinstance(token.value, float):
                comp_fn = comp_fn_numeric
        
            if comp_fn:
                #TODO: change to generator expressions and evaluate as sets in the evaluate function
                result_set = set(n for n in self.network.graph 
                        if token.attribute in self.network.graph.node[n] and comp_fn(token, n) )
                stack.append(result_set)

        final_set = self.evaluate_node_stack(stack)
        return final_set

    def allocate_tags(self):
        """Allocates community values to tags"""
        LOG.debug("Allocating community values to tags")
        tag_id = itertools.count(1)
        generic_asn = "1234"
        for tag in sorted(self.tags_to_allocate):
            self.allocated_tags[tag] = "%s:%s" % (generic_asn, tag_id.next() * 10)


    def get_prefixes(self, nodes):
        """Return prefixes for given node set"""
        LOG.debug("Returning prefixes for nodes %s" % nodes)
        prefixes = set()
        for node in nodes:
            # Arbitrary choice of out edges, as bi-directional edge for each subnet
            prefixes.update([data.get("sn")
                for u, v, data in self.network.graph.out_edges(node, data=True) 
                if data.get("sn")])

        return prefixes

    def query_to_tag(self, query):
        """ flattens a node select query into a tag
        """
# flatten items into single list in lexicographic order
        retval = (item for sublist in query for item in sublist)
# replace char if in mapping, else leave, eg = -> eq
        retval = (self._opn_to_tag[item] if item in self._opn_to_tag else item
                for item in retval)
# ensure all strings
# format integers as strings with no decimal points
        retval = ("%i"%item if isinstance(item, float) and int(item) == item else item
                for item in retval)
        retval = (str(item).lower() for item in retval)
        return "_".join(retval)

    def proc_ot_match(self, match_type, match_query):
        """Processes origin or transit match query"""
        LOG.debug("Processing Origin/Transit query %s %s" % (match_type, match_query))
# extract the node queryParser
#TODO: handle case of multiple matches......
# rather than getting first element, iterate over
#TODO: need to handle origin different here to transit - diff policy
        policy = None
        nodes = self.node_select_query(match_query)
        tag = self.query_to_tag(match_query)
        tag_pl = "%s_%s" % (match_type.lower(), tag_to_pl(tag))
        tag_cl = "%s_%s" % (match_type.lower(), tag_to_cl(tag))
        if match_type == "Transit":
                policy = "(addTag %s)" % tag_cl
                LOG.debug("Transit policy: %s" % policy)
        else:

# efficiency: check if query has already been executed (ie if already prefixes for this tag)
#TODO: see if need to have unique name for prefix list and comm val: eg pl_tag and 
            if tag_pl in self.prefix_lists:
                LOG.debug( "already executed prefix lookup for %s" % tag_pl)
            else:
                prefixes = self.get_prefixes(nodes)
                self.prefix_lists[tag_pl] = prefixes
# and mark prefixes
                policy = "(if prefix_list = %s then addTag %s)" % (tag_pl, tag_cl)
                LOG.debug("Origin policy: %s" % policy)
# now apply policy to all egress from nodes
# store tag
                self.tags_to_allocate.update([tag])

        if policy:
            # Parse the string into policy tuples
            parsed = self.bgpSessionQuery.parseString(policy)
            per_session_policy = self.process_if_then_else(parsed.bgpSessionQuery)

            for node in nodes:
                for u, v in self.network.g_session.out_edges(node):
                    LOG.debug("Applying %s policy to %s egress -> %s" % (match_type, u, v))
                    self.network.g_session[u][v]['egress'].append(per_session_policy)
        return match_clause("tag", "=", tag_cl)

    def process_if_then_else(self, parsed_query):
        """Processes if-then-else query"""
        LOG.debug("Processing if-then-else query %s" % parsed_query)
        retval = []

        for token in parsed_query:
            if not parsed_query.ifThenClause:
# Special case of action only clause (no "if" clause)
                reject = any(True for (action, value) in token if action == self.reject)
                else_tuples = [action_clause (action, value) for
                        (action, value) in token
                        if action != self.reject]
                retval.append(match_tuple([], else_tuples, reject))

            elif token == parsed_query.else_clause:
# Special case of else (at end)
                reject = any(True for (action, value) in token if action == self.reject)
                else_tuples = [action_clause (action, value) for
                        (action, value) in token
                        if action != self.reject]
                retval.append(match_tuple([], else_tuples, reject))
            else:
                #TODO: check is in ifthen
                (if_clause, then_clause) = token
#TODO: base this on the keywords used in the parser itself for continuity
                origin_transit_keywords = set(["Origin", "Transit"])
# Check for reject
                if_tuples = [
                        self.proc_ot_match(attribute, value) if attribute in origin_transit_keywords
                        else match_clause(attribute, comparison, value)
                        for (attribute, comparison, value) in if_clause]
                reject = any(True for (action, value) in then_clause if action == self.reject)
                then_tuples = [action_clause (action, value) for
                        (action, value) in then_clause
                        if action != self.reject]
                retval.append(match_tuple(if_tuples, then_tuples, reject))
        return retval

    def cl_and_pl_per_node(self):
        """extract tags and prefixes used from sessions
        Also applies sequence numbers to match clauses"""
        LOG.debug("Extracting community lists and prefix lists per node, adding sequence numbers")
# Store in g_session for future use
        self.network.g_session.graph['tags'] = self.allocated_tags
        self.network.g_session.graph['prefixes'] = self.prefix_lists
        for node in self.network.g_session:
            prefixes = set()
            tags = set()
# also sets routemap names
            for (dst, src, session_data) in self.network.g_session.in_edges(node, data=True):
                counter = itertools.count(1)
                session_policy_tuples = []
                for match_tuples in session_data['ingress']:
                    seq_no = itertools.count(1)
                    match_tuples_with_seqno = []
                    for match_tuple in match_tuples:
                        for match_clause in match_tuple.match_clauses:
                            if 'prefix_list' in match_clause.type:
                                prefixes.update([match_clause.value])
                            if 'tag' in match_clause.type:
                                tags.update([match_clause.value])
                        for action_clause in match_tuple.action_clauses:
                            if action_clause.action in set(['addTag']):
                                tags.update([action_clause.value])
                        match_tuples_with_seqno.append(match_tuple_with_seq_no(seq_no.next(), 
                            match_tuple.match_clauses, match_tuple.action_clauses, match_tuple.reject))
                    route_map_name = "rm_ingress_%s_%s" % (self.network.fqdn(dst).replace(".", "_"), counter.next())
# allocate sequence number
                    session_policy_tuples.append(route_map_tuple(route_map_name, match_tuples_with_seqno))
                # Update with the named policy tuples
                if len(session_policy_tuples):
                    LOG.debug("Storing session tuples %s to %s->%s ingress" % (session_policy_tuples, self.network.fqdn(src), self.network.fqdn(dst)))
                self.network.g_session[dst][src]['ingress'] = session_policy_tuples

            for (src, dst, session_data) in self.network.g_session.out_edges(node, data=True):
                counter = itertools.count(1)
                session_policy_tuples = []
                for match_tuples in session_data['egress']:
                    seq_no = itertools.count(1)
                    match_tuples_with_seqno = []
                    for match_tuple in match_tuples:
                        for match_clause in match_tuple.match_clauses:
                            if 'prefix_list' in match_clause.type:
                                prefixes.update([match_clause.value])
                            if 'tag' in match_clause.type:
                                tags.update([match_clause.value])
                        for action_clause in match_tuple.action_clauses:
                            if action_clause.action in set(['addTag']):
                                tags.update([action_clause.value])
                        match_tuples_with_seqno.append(match_tuple_with_seq_no(seq_no.next(), 
                            match_tuple.match_clauses, match_tuple.action_clauses, match_tuple.reject))
                    route_map_name = "rm_egress_%s_%s" % (self.network.fqdn(dst).replace(".", "_"), 
                            counter.next())
# allocate sequence number
                    session_policy_tuples.append(route_map_tuple(route_map_name, match_tuples_with_seqno))
                # Update with the named policy tuples
                self.network.g_session[src][dst]['egress'] = session_policy_tuples
                if len(session_policy_tuples):
                    LOG.debug("Storing session tuples %s to %s->%s egress" % (session_policy_tuples, src.fqdn, dst.fqdn))

            self.network.g_session.node[node]['tags'] = tags
            self.network.g_session.node[node]['prefixes'] = prefixes
# and update the global list of tags with any new tags found
            self.tags_to_allocate.update(tags)

    def store_tags_per_router(self):
        """Stores the list of tags/community value mappings in the router in session graph"""
        LOG.debug("Storing allocated tags to routers")
        for node, data in self.network.g_session.nodes(data=True):
            tags = dict( (tag, self.allocated_tags[tag]) for tag in data['tags'])
            self.network.g_session.node[node]['tags'] = tags

            prefixes = dict( (prefix, self.prefix_lists[prefix]) for prefix in data['prefixes'])
            # store updated tags
            self.network.g_session.node[node]['prefixes'] = prefixes

    def rewrite_bgp_query_local_tags(self, query, function_name):
# rewrites any tags not defined  as globals
#TODO: make cleaner - ie not regex - pass parameter to parser/query and do rewrite as user defined function??
        query_processed = query

# default to empty set if no globals defined
        function_globals = self.user_defined_functions[function_name].get('global_tags') or set()
        captures = ["(tag = (\w+\.*\_*)*)", "(addTag (\w+\.*\_*)*)", "(tags contain (\w+\.*\_*)*)"]
        for capture in captures:
            results = re.findall(capture, query)
            for result in results:
                search_string = result[0]
                tag = result[1]
                if tag not in function_globals:
                    new_tag = "fn_%s_%s" % (function_name, tag)
                    replace_string = search_string.replace(tag, new_tag)
                    LOG.debug("Replacing non-global tag %s with %s in %s" % (tag, new_tag, function_name))
# Now replace in query  
                    query_processed = query_processed.replace(search_string, replace_string)
                else:
                    LOG.debug("Keeping global tag %s in %s" % (tag, function_name))

        return query_processed 

    def parse_user_def_functions(self, library_file):
        """Note you need a blank newline after a function definition"""
        try:
            with open( library_file, 'r') as f_lib:
                library_data = f_lib.read()

#TODO: use named tuple for functions, and for library entries
            """TODO: make the function definition single grammar, use
            http://pyparsing.wikispaces.com/file/view/indentedGrammarExample.py"""
            current_function_def = None
            for line in library_data.splitlines():
                if line.startswith("#"):
                    LOG.debug("Skipping commented line %s", line)
                    continue

                if current_function_def:
                    if line.strip() == "":
                        current_function_def = None
# blank line
                        continue
                    if (line.startswith("\t") or line.startswith("  ")):
# function has been started, and indented so try as a library entry
                        try:
                            results = self.library_entry.parseString(line)
                            if results.global_tags:
                                global_tags = [tag for tag in results.global_tags.tags]
                                self.user_defined_functions[current_function_def]['global_tags'] = global_tags
                                continue
                            else:
#TODO: for efficiency, could save the already parsed query here
#TODO: remove this dodgy hack! - as want to be overlay, so don't parse here???
                                bgp_query = line.split(":")[1]
                                bgp_query = self.rewrite_bgp_query_local_tags(bgp_query, current_function_def)
                                library_entry = {
                                        'query_a': results.query_a, 
                                        'edge_type': results.edgeType,
                                        'query_b': results.query_b,
                                        'bgp_query': bgp_query,
                                }
                                self.user_defined_functions[current_function_def]['entries'].append(library_entry)
# finished with this line
                            continue
                        except pyparsing.ParseFatalException:
                            print "unable to parse indented line:", line
                            current_function_def = None
                else:
                    try:
                        results = self.library_def.parseString(line)
                        current_function_def = results.def_name
                        self.user_defined_functions[current_function_def] = {
                                'params': [a for a in results.def_params],
                                'entries': [],
                                }
                        continue
                    except pyparsing.ParseFatalException:
                        pass

            for function_name, function_data in self.user_defined_functions.items():
                params = function_data['params']
# Store indices so can lookup when applying functions
                param_indices = dict( (p, params.index(p)) for p in params)
                self.user_defined_functions[function_name]['param_indices'] = param_indices
            # and remap tags

        except IOError:
            LOG.warn("Unable to open library file: %s" % library_file)

    def apply_user_library_calls(self):
            f_library_debug = open( os.path.join(config.log_dir, "library_dump.txt"), "w")
            for name, params in self.user_library_calls:
# Format params nicely for printing - need to handle nested lists as {}
                param_string = (", ".join(p if isinstance(p, basestring) else
                    "{%s}" % ", ".join(p_elem for p_elem in p)
                    for p in params))
                f_library_debug.write("---\n%s (%s)\n" % (name, param_string))
                LOG.info("Applying function %s(%s)" % (name, param_string))
                try:
                    fn_def = self.user_defined_functions[name]
                except KeyError:
                    LOG.info('No function definition found for "%s"' % name)
                    continue

# check param length
                param_indices = fn_def['param_indices']
                if len(params) != len(param_indices):
                    LOG.info("Incorrect parameter count for function %s(%s)" % (name, ", ".join(params)))
                    continue

                for function_line in fn_def['entries']:
                    query_a = function_line['query_a']
                    query_b = function_line['query_b']
                    edge_type = function_line['edge_type']
                    bgp_query = function_line['bgp_query'].strip()
                    try:
                        query_a_index = param_indices[query_a]
                    except KeyError:
                        LOG.warn("Parameter %s not found in function definition for %s" % (query_a, name))
                        continue
                    try:
                        query_b_index = param_indices[query_b]
                    except KeyError:
                        LOG.warn("Parameter %s not found in function definition for %s" % (query_b, name))
                        continue
# find the parameters that map to these
                    q_a_map = params[query_a_index]
                    q_b_map = params[query_b_index]
                    try:
                        q_a_vals = sorted(self.user_defined_sets[q_a_map])
                    except TypeError:
# user defined list
                        q_a_vals = q_a_map
                    try:
                        q_b_vals = sorted(self.user_defined_sets[q_b_map])
                    except TypeError:
                        q_b_vals = q_b_map

                    LOG.debug("Definition param %s maps to user parameter %s with values %s" % (query_a, 
                        q_a_map, q_a_vals))
                    LOG.debug("Definition param %s maps to user parameter %s with values %s" % (query_b, 
                        q_b_map, q_b_vals))
                    for (val_a, val_b) in itertools.product(q_a_vals, q_b_vals):
                        LOG.debug("Applying %s %s %s" % (val_a, edge_type, val_b))

                        # Test if "AS1"
                        attribute_a = "Network"
                        if val_a.startswith("AS"):
                            attribute_a = "asn"
                            val_a = int(val_a[2:])
                        attribute_b = "Network"
                        if val_b.startswith("AS"):
                            attribute_b = "asn"
                            val_b = int(val_b[2:])

                        policy_line = "(%s = %s) %s (%s = %s): %s" % (attribute_a, val_a, edge_type, attribute_b, val_b, bgp_query)
                        LOG.debug("Policy: %s" % policy_line)
                        f_library_debug.write(policy_line + "\n")
                        self.apply_bgp_policy(policy_line)
            f_library_debug.close()

    def load_include_file(self, include_file):
        retval = []
        try:
            with open( include_file, 'r') as f_include:
                for line in f_include.readlines():
                    retval.append(line.strip())
        except IOError:
            LOG.warn("Unable to load include file: %s" % include_file)
        return retval

    def apply_policy_file(self, policy_in_file):
        """Applies a BGP policy file to the network"""
        LOG.debug("Applying policy file %s" % policy_in_file)
        policy_lines = []
        import_library = "importLibrary"
        include = "includePolicy"
        pol_path = os.path.split(policy_in_file)[0]
        with open( policy_in_file, 'r') as f_pol:
            for line in f_pol.readlines():
                line = line.strip()
                if line.startswith("#"):
                    LOG.debug("Skipping commented line %s", line)
                    continue
                if line == "":
                    continue
                if line.startswith(import_library):
                    library_file = line.replace(import_library, "").strip()
                    library_file = os.path.join(pol_path, library_file) # relative import
                    self.parse_user_def_functions(library_file)
                elif line.startswith(include):
                    include_file = line.replace(include, "").strip()
                    include_file = os.path.join(pol_path, include_file) # relative import
                    file_contents = self.load_include_file(include_file)
                    policy_lines += file_contents
                else:
                    policy_lines.append(line)

#Now parse the combined files

        for line in policy_lines:
            line = line.strip()
            if line.startswith("#"):
                LOG.debug("Skipping commented line %s", line)
                continue
            if line == "":
                continue
            try:
                self.apply_bgp_policy(line)
            except pyparsing.ParseFatalException as e:
                LOG.warn("Unable to parse query line %s" % line)

        self.apply_user_library_calls()
        self.cl_and_pl_per_node()
        self.allocate_tags()
        self.store_tags_per_router()

