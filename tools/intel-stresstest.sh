#!/bin/sh

export https_proxy="http://proxy-dmz.intel.com:912/"
export http_proxy="http://proxy-dmz.intel.com:911/"
export no_proxy="intel.com,.intel.com,localhost,127.0.0.1"
export socks_proxy="socks://proxy-dmz.intel.com:1080/"
export ftp_proxy="ftp://proxy-dmz.intel.com:911/"

STCFG="/home/sleepgraph/pm-graph/config/stresstest-intel.cfg"
STCMD="/home/sleepgraph/pm-graph/stresstest.py -config $STCFG"
STDIR="/home/sleepgraph/workspace/stressconfig"
STMAC="$STDIR/machine.txt"
STOUT="/home/sleepgraph/pm-graph-test"
STPKG="/home/sleepgraph/workspace/packages"

printUsage() {
	echo "USAGE: stresstest.sh command <args>"
	echo "COMMANDS:"
	echo "   info - show the current kernel version and package files"
	echo "   reset - remove the current log and update the machines file"
	echo "   online <restart> - check which machines are online"
	echo "       restart: attempt a restart of offline machines"
	echo "   install - install the kernel and tools on online machines"
	echo "   ready - verify installs worked and machines are ready for test"
	echo "   run - start stress testing on all ready machines"
	echo "   runmulti - start stress testing using sleepgraph -multi"
	echo "   getmulti - scp stress test output from runmulti run"
	echo "   status - show the test logs for each machine"
	echo "   report - process the data from a completed run and publish it"
	exit 0
}

getKernel() {
	if [ "$1" = "last" ]; then
		KFILE="/home/sleepgraph/workspace/stressconfig/kernel-last.txt"
	else
		KFILE="/home/sleepgraph/workspace/stressconfig/kernel.txt"
	fi
	if [ ! -e $KFILE ]; then
		echo "ERROR: missing the kernel version in kernel.txt"
		echo "- $KFILE"
		exit 1
	fi
	KERNEL=`cat $KFILE`
	if [ -z "$KERNEL" ]; then
		echo "ERROR: kernel is blank in kernel.txt"
		echo "- $KFILE"
		exit 1
	fi
}

getKernelAll() {
	getKernel
	IMAGE=`find $STPKG -name linux-image-*$KERNEL*.deb`
	HEADERS=`find $STPKG -name linux-headers-*$KERNEL*.deb`
	if [ -z "$IMAGE" -o -z "$HEADERS" ]; then
		echo "ERROR: $KERNEL kernel packages are missing"
		echo "- $STPKG"
		exit 1
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
		OUTDIR=/srv/pm-graph-test
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
elif [ $1 = "info" ]; then
	echo "The current linux kernel is $KERNEL"
	echo "These are the package files:"
	cd $STPKG
	ls -l *$KERNEL*.deb | cut -c 36-
	echo "These are the machines currently defined:"
	cat $STMAC
elif [ $1 = "resetwired" ]; then
	rm -f /home/sleepgraph/.ssh/known_hosts
	labmachine elist > $STMAC
	cp -f $STMAC $STDIR/machine-$KERNEL.txt
	cat $STMAC
elif [ $1 = "reset" ]; then
	rm -f /home/sleepgraph/.ssh/known_hosts
	labmachine qlist > $STMAC
	cp -f $STMAC $STDIR/machine-$KERNEL.txt
	cat $STMAC
elif [ $1 = "online" ]; then
	if [ $# -eq 1 ]; then
		$STCMD -resetcmd blank -kernel $KERNEL -userinput online
	elif [ $# -eq 2 -a "$2" = "restart" ]; then
		$STCMD -kernel $KERNEL online
	else
		echo "ERROR: invalid argument for online - $2"
		printUsage
	fi
elif [ $1 = "turbostat" ]; then
	$STCMD turbostat
elif [ $1 = "init" ]; then
	$STCMD -kernel $KERNEL init
elif [ $1 = "tools" ]; then
	$STCMD -kernel $KERNEL tools
elif [ $1 = "reboot" ]; then
	$STCMD -kernel $KERNEL reboot
elif [ $1 = "install" ]; then
	getKernelAll
	$STCMD -kernel $KERNEL install
elif [ $1 = "uninstall" ]; then
	getKernelAll
	$STCMD -kernel $KERNEL uninstall
elif [ $1 = "ready" ]; then
	$STCMD -kernel $KERNEL ready
elif [ $1 = "run" ]; then
	getOutput
	$STCMD -kernel $KERNEL -testout $OUTDIR -mode freeze:mem -duration 1440 run
elif [ $1 = "runfirst" ]; then
	getOutput
	$STCMD -kernel $KERNEL -testout $OUTDIR -mode freeze:mem:disk -duration 480 run
elif [ $1 = "runtodd" ]; then
	getOutput
	$STCMD -kernel $KERNEL -testout $OUTDIR -mode mem:disk -duration 480 run
elif [ $1 = "runfirstquick" ]; then
	getOutput
	$STCMD -kernel $KERNEL -testout $OUTDIR -mode freeze:mem:disk -duration 60 run
elif [ $1 = "runlast" ]; then
	getOutput
	$STCMD -kernel $KERNEL -testout $OUTDIR -mode freeze:mem -duration 480 run
elif [ $1 = "runmem" ]; then
	getOutput
	$STCMD -kernel $KERNEL -testout $OUTDIR -mode mem -duration 1440 run
elif [ $1 = "runfreeze" ]; then
	getOutput
	$STCMD -kernel $KERNEL -testout $OUTDIR -mode freeze -duration 480 run
elif [ $1 = "runquick" ]; then
	getOutput
	$STCMD -kernel $KERNEL -testout $OUTDIR -mode freeze:mem:disk -duration 60 run
elif [ $1 = "runquickfreeze" ]; then
	getOutput
	$STCMD -kernel $KERNEL -testout $OUTDIR -mode freeze -duration 60 run
elif [ $1 = "runquickdisk" ]; then
	getOutput
	$STCMD -kernel $KERNEL -testout $OUTDIR -mode disk -duration 60 run
elif [ $1 = "runsuperquickfreeze" ]; then
	getOutput
	$STCMD -kernel $KERNEL -testout $OUTDIR -mode freeze -duration 30 run
elif [ $1 = "runquickmem" ]; then
	getOutput
	$STCMD -kernel $KERNEL -testout $OUTDIR -mode mem -duration 60 run
elif [ $1 = "runfreeze10" ]; then
	getOutput
	$STCMD -kernel $KERNEL -testout $OUTDIR -mode freeze -count 10 run
elif [ $1 = "runfreeze10m" ]; then
	getOutput
	$STCMD -kernel $KERNEL -testout $OUTDIR -mode freeze -duration 10 run
elif [ $1 = "runmem10m" ]; then
	getOutput
	$STCMD -kernel $KERNEL -testout $OUTDIR -mode mem -duration 10 run
elif [ $1 = "rundisk" ]; then
	getOutput
	$STCMD -kernel $KERNEL -testout $OUTDIR -mode disk -duration 240 run
elif [ $1 = "rundisk10m" ]; then
	getOutput
	$STCMD -kernel $KERNEL -testout $OUTDIR -mode disk -duration 10 run
elif [ $1 = "rundisk60m" ]; then
	getOutput
	$STCMD -kernel $KERNEL -testout $OUTDIR -mode disk -duration 60 run
elif [ $1 = "rundiskshutdown30m" ]; then
	getOutput
	$STCMD -kernel $KERNEL -testout $OUTDIR -mode disk-shutdown -duration 30 run
elif [ $1 = "rundisksreboot30m" ]; then
	getOutput
	$STCMD -kernel $KERNEL -testout $OUTDIR -mode disk-reboot -duration 30 run
elif [ $1 = "runfreeze4h" ]; then
	getOutput
	$STCMD -kernel $KERNEL -testout $OUTDIR -mode freeze -duration 240 run
elif [ $1 = "runmulti" ]; then
	$STCMD -kernel $KERNEL -mode freeze -duration 1440 runmulti
elif [ $1 = "getmulti" ]; then
	$STCMD -kernel $KERNEL getmulti
elif [ $1 = "status" ]; then
	getOutput
	$STCMD -kernel $KERNEL -testout $OUTDIR status
elif [ $1 = "bootsetup" ]; then
	getOutput
	$STCMD -kernel $KERNEL bootsetup
elif [ $1 = "report" -o $1 = "reportlast" ]; then
	if [ $1 = "reportlast" ]; then
		getKernel last
	fi
	URL="http://otcpl-stress.ostc.intel.com/pm-graph-test"
	WEBDIR="/home/sleepgraph/pm-graph-test"
	SORTDIR="/home/sleepgraph/pm-graph-sort"
	MS="/home/sleepgraph/.machswap"
	GS="python3 /home/sleepgraph/pm-graph/stressreport.py"
	if [ -e "/tmp/bugzilla.bin" ]; then
		ARGS="-bugfile /tmp/bugzilla.bin -webdir $WEBDIR -sortdir $SORTDIR -machswap $MS -parallel 16"
	else
		ARGS="-bugzilla -webdir $WEBDIR -sortdir $SORTDIR -machswap $MS -parallel 16"
	fi
	cd $WEBDIR
	$GS $ARGS -urlprefix $URL/$KERNEL -stype sheet -genhtml -create both $KERNEL
else
	echo "\nUNKNOWN COMMAND: $1\n"
	printUsage
fi
