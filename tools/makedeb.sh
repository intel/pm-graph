#!/bin/sh

# sudo apt-get install devscripts cdbs debhelper
cd /tmp
if [ -d pm-graph ]; then
	rm -rf pm-graph
fi
git clone -b master https://github.com/intel/pm-graph.git
cd pm-graph
debuild -i -us -uc -b
if [ $? -eq 0 ];then
	echo "SUCCESS: the package files are here"
	ls -al /tmp/pm-graph_*.*
fi
