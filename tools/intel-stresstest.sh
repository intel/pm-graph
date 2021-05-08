#!/bin/sh

STCFG="/home/sleepgraph/workspace/pm-graph/config/stresstest-intel.cfg"
STCMD="/home/sleepgraph/workspace/pm-graph/stresstest.py -config $STCFG"
STDIR="/home/sleepgraph/workspace/stressconfig"
STMAC="$STDIR/machine.txt"
STOUT="/home/sleepgraph/pm-graph-test"

printUsage() {
	echo "USAGE: stresstest.sh command <args>"
	echo "COMMANDS:"
	echo "   reset - remove the current log and update the machines file"
	echo "   online <restart> - check which machines are online"
	echo "       restart: attempt a restart of offline machines"
	echo "   install - install the kernel and tools on online machines"
	echo "   ready - verify installs worked and machines are ready for test"
	echo "   run - start stress testing on all ready machines"
	echo "   status - show the test logs for each machine"
	echo "   report - process the data from a completed run and publish it"
	exit
}

getKernel() {
	KFILE="/home/sleepgraph/workspace/stressconfig/kernel.txt"
	if [ ! -e $KFILE ]; then
		echo "ERROR: missing the kernel version in kernel.txt"
		echo "- $KFILE"
		exit
	fi
	KERNEL=`cat $KFILE`
	if [ -z "$KERNEL" ]; then
		echo "ERROR: kernel is blank in kernel.txt"
		echo "- $KFILE"
		exit
	fi
}

getOutput() {
	if [ -e $STOUT/$KERNEL ]; then
		TARGET=`readlink -f $STOUT/$KERNEL`
		OUTDIR=`dirname $TARGET`
	else
		if [ -L $STOUT/$KERNEL ]; then
			rm -f $STOUT/$KERNEL
		fi
		DISK=`df --output=pcent,target | grep /media/disk | sed "s/ /0/g" | sort | head -1 | sed "s/.*0\//\//"`
		if [ -z "$DISK" ]; then
			DISK="/media/disk1"
		fi
		OUTDIR=$DISK/pm-graph-test
		if [ ! -e $OUTDIR/$KERNEL ]; then
			mkdir -p $OUTDIR/$KERNEL
		fi
		ln -s $OUTDIR/$KERNEL $STOUT/$KERNEL
	fi
}

if [ $# -gt 2 -o $# -lt 1 ]; then printUsage; fi

getKernel
if [ $1 = "help" ]; then
	printUsage
elif [ $1 = "reset" ]; then
	rm -f $STDIR/machine-$KERNEL.txt
	labmachine qlist > $STMAC
	cat $STMAC
elif [ $1 = "online" ]; then
	if [ $# -eq 1 ]; then
		$STCMD -resetcmd blank -kernel $KERNEL -userinput online
	elif [ $# -eq 2 -a "$2" = "restart" ]; then
		$STCMD -kernel $KERNEL -userinput online
	else
		echo "ERROR: invalid argument for online - $2"
		printUsage
	fi
elif [ $1 = "install" ]; then
	$STCMD -kernel $KERNEL install
elif [ $1 = "ready" ]; then
	$STCMD -kernel $KERNEL ready
elif [ $1 = "run" ]; then
	getOutput
	$STCMD -kernel $KERNEL -testout $OUTDIR -mode all -duration 1440 run
elif [ $1 = "status" ]; then
	getOutput
	$STCMD -kernel $KERNEL -testout $OUTDIR status
elif [ $1 = "report" ]; then
	URL="http://otcpl-perf-data.jf.intel.com/pm-graph-test"
	WEBDIR="/home/sleepgraph/pm-graph-test"
	SORTDIR="/home/sleepgraph/pm-graph-sort"
	MS="/home/sleepgraph/.machswap"
	GS="python3 /home/sleepgraph/workspace/pm-graph/stressreport.py"
	ARGS="-bugzilla -webdir $WEBDIR -sortdir $SORTDIR -machswap $MS -parallel 8"
	cd $WEBDIR
	$GS $ARGS -urlprefix $URL/$KERNEL -stype sheet -genhtml -create both $KERNEL
else
	echo "\nUNKNOWN COMMAND: $1\n"
	printUsage
fi
