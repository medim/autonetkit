graph
[
	hierarchic	1
	label	""
	directed	1
	node
	[
		id	0
		label	"AAA" 
		ibgp_level	2  
		root True
	 ]
	node
	[
		id	1
		label	"2"  
		root True
	]
	node
	[
		id	2
		label	"3"
	]
	edge
	[
		source	0
		target	1
	]
	edge
	[
		source	1
		target	2
	]
	edge
	[
		source	2
		target	0
	]
]
