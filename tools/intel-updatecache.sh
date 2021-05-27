#!/bin/sh

echo "Updating the multitest and multitestdata cache files"
URL="http://otcpl-perf-data.jf.intel.com/pm-graph-test"
WEBDIR="$HOME/pm-graph-test"
SORTDIR="$HOME/pm-graph-sort"
MS="$HOME/.machswap"
GS="python3 $HOME/pm-graph/stressreport.py"

cd $WEBDIR
$GS -webdir $WEBDIR -sortdir $SORTDIR -machswap $MS -urlprefix $URL -parallel 8 -sort test .
