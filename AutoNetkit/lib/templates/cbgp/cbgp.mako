% for asn, topology in sorted(physical_topology.items()):
# "physical" topology for AS${asn}
	% for n in sorted(topology['nodes']):
	   net add node ${n}
	% endfor      
	% for (s,t) in sorted(topology['links']):
	   net add link ${s} ${t}
	% endfor                                                     
	
% endfor                       

# Interdomain links
% for (s,t) in sorted(interdomain_links):
   net add link ${s} ${t}
% endfor                    
                       
% for asn, topology in sorted(igp_topology.items()):
# IGP configuration for AS${asn}
net add domain ${asn} igp         
% for n in sorted(topology['nodes']):
   net node ${n} domain ${asn}
% endfor      
% for (s,t, weight) in sorted(topology['links']):
   net link ${s} ${t} igp-weight ${weight}
% endfor                 
net domain ${asn} compute                
                
% endfor          
                 
# BGP Routers
% for asn, routers in sorted(bgp_routers.items()):
% for n in sorted(routers):
   bgp add router ${asn} ${n}
% endfor
% endfor             

% for asn, topology in sorted(ibgp_topology.items()):   
% if len(topology['routers']):
# Full mesh of iBGP sessions in AS${asn}          
bgp domain ${asn} full-mesh
% endif

%endfor        

# eBGP static routes
% for router, peers in sorted(ebgp_topology.items()):              
% for peer_asn, peer in peers:       
net node ${router} route add --oif=${peer} ${peer}/32 1
% endfor
% endfor

# Setup eBGP sessions
% for router, peers in sorted(ebgp_topology.items()):              
bgp router ${router}
% for peer_asn, peer in peers:
	add peer ${peer_asn} ${peer}      	
	peer ${peer} next-hop-self
	peer ${peer} up
% endfor
	exit       
% endfor              
	
# Originate own prefixes
% for router, prefix in sorted(ebgp_prefixes.items()):     
	bgp router ${router} add network ${prefix}
% endfor     

% for router, policy_data in sorted(bgp_policy.items()):    
bgp router ${router} 
	% for peer, peer_policy in sorted(policy_data.items()):
	peer ${peer}
		% for direction, route_maps in peer_policy.items(): 
		% if len(route_maps): 
			% if direction == 'ingress':
		filter in
			% elif direction == 'egress':
		filter out
			% endif    
			% for route_map in route_maps:   
				add-rule
				% for match_tuple in route_map.match_tuples:  
			    %if len(match_tuple.match_clauses):        
			    %for match_clause in match_tuple.match_clauses:
			        % if match_clause.type == "prefix_list":
					match "prefix in prefix-list ${prefixes[match_clause.value]}"
			        % elif match_clause.type == "tag":   
					match "community is ${tags[match_clause.value]}"
			        % endif      
			    %endfor       
				% else:
				match "any"
			    % endif             
			    %if len(match_tuple.action_clauses) or match_tuple.reject:   
				action "\
			    %for action_clause in match_tuple.action_clauses:
			        % if action_clause.action == "addTag":
community add ${tags[action_clause.value]}, \
			        % elif action_clause.action == "setLP":
local-pref ${action_clause.value}, \
			        % elif action_clause.action == "setMED":
metric ${action_clause.value}, \  
			        % elif action_clause.action == "setNextHop":
next-hop ${action_clause.value}, \ 
			        % elif action_clause.action == "removeTag":
community delete ${action_clause.value}, \
			        % endif     
			    %endfor   
			    % if match_tuple.reject:
deny \
			    % else: 
accept \
			   % endif
			    % endif  
"
				% endfor
				% endfor                
			% endif
			% endfor        
	% endfor
% endfor

sim run               

bgp assert peerings-ok                  
bgp assert reachability-ok