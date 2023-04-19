#!/bin/sh

echo "Updating the multitest and multitestdata cache files"
URL="http://otcpl-stress.ostc.intel.com/pm-graph-test"
WEBDIR="$HOME/pm-graph-test"
SORTDIR="$HOME/pm-graph-sort"
MS="$HOME/.machswap"
GS="python3 $HOME/pm-graph/stressreport.py"
CACHE="$HOME/.multitests"
DATACACHE="$HOME/.multitestdata"

printUsage() {
	echo "USAGE: intel-updatecache command"
	echo "COMMANDS:"
	echo "   showmissing - show the multitests that have no data"
	echo "   all - update both the multitest and multitestdata caches"
	echo "   data - update only the multitestdata cache"
	exit 0
}

if [ $# -gt 2 -o $# -lt 1 ]; then printUsage; fi

if [ $1 = "help" ]; then
	printUsage
elif [ $1 = "showmissing" ]; then
	cat $DATACACHE | sed "s/|.*//g" | sort > /tmp/check2.txt
	cat $CACHE | sort > /tmp/check1.txt
	diff /tmp/check1.txt /tmp/check2.txt
	rm /tmp/check1.txt /tmp/check2.txt
elif [ $1 = "all" ]; then
	cd $WEBDIR
	$GS -webdir $WEBDIR -sortdir $SORTDIR -machswap $MS -urlprefix $URL -parallel 8 -sort test .
elif [ $1 = "data" ]; then
	cd $WEBDIR
	$GS -cache -webdir $WEBDIR -sortdir $SORTDIR -machswap $MS -urlprefix $URL -parallel 8 -sort test .
fi
