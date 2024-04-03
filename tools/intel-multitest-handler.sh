#!/bin/sh

validTarball() {
	ext=`echo $1 | sed "s/.tar.gz$//"`
	if [ $1 != "$ext" ]; then
		return
	fi
	ext=`echo $1 | sed "s/.tgz$//"`
	if [ $1 != "$ext" ]; then
		return
	fi
	if [ ! -e $1 ]; then
		echo "ERROR: $1 does not exist"
		exit
	elif [ -d $1 ]; then
		echo "ERROR: $1 is a directory, not a tarball"
		exit
	fi
}

if [ $# -lt 1 ]; then
	echo "stressreport multisheet processer"
	echo "USAGE: multitest <tarball>"
	exit
fi

INSIZE=0
INFILES=""
while [ "$1" ] ; do
	validTarball "$1"
	SZ=`stat -c %s $1`
	INSIZE=$(($SZ + $INSIZE))
	if [ -z "$INFILES" ]; then
		INFILES="$1"
	else
		INFILES="$INFILES $1"
	fi
	shift
done

export https_proxy="http://proxy-dmz.intel.com:912/"
export http_proxy="http://proxy-dmz.intel.com:911/"
export no_proxy="intel.com,.intel.com,localhost,127.0.0.1"
export socks_proxy="socks://proxy-dmz.intel.com:1080/"
export ftp_proxy="ftp://proxy-dmz.intel.com:911/"

GS="python3 $HOME/pm-graph/stressreport.py"
URL="http://otcpl-stress.ostc.intel.com/pm-graph-test"
WEBDIR="$HOME/pm-graph-test"
SORTDIR="$HOME/pm-graph-sort"
DATADIR="/srv/pm-graph-test"
MS="$HOME/.machswap"

XARGS=""
if [ $INSIZE -gt 30000000000 ]; then
	XARGS="-tempdisk /srv/tmp"
fi

if [ -e "/tmp/bugzilla.bin" ]; then
	$GS $XARGS -webdir "$WEBDIR" -datadir "$DATADIR" -sortdir "$SORTDIR" -urlprefix "$URL" -machswap "$MS" -stype sheet -create both -bugfile /tmp/bugzilla.bin -maxproc 4 -parallel 16 -genhtml -cache -rmtar "$INFILES"
else
	$GS $XARGS -webdir "$WEBDIR" -datadir "$DATADIR" -sortdir "$SORTDIR" -urlprefix "$URL" -machswap "$MS" -stype sheet -create both -bugzilla -maxproc 4 -parallel 16 -genhtml -cache -rmtar "$INFILES"
fi
