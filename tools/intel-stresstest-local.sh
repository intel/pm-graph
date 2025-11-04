#!/bin/sh

#export https_proxy="http://proxy-dmz.intel.com:912/"
#export http_proxy="http://proxy-dmz.intel.com:911/"
#export no_proxy="intel.com,.intel.com,localhost,127.0.0.1"
#export socks_proxy="socks://proxy-dmz.intel.com:1080/"
#export ftp_proxy="ftp://proxy-dmz.intel.com:911/"

STCFG="/home/tebrandt/workspace/pm-graph/config/stresstest-intel-local.cfg"
STCMD="/home/tebrandt/workspace/pm-graph/stresstest.py -config $STCFG"
STDIR="/home/tebrandt/workspace/stressconfig"
STMAC="$STDIR/machine.txt"
STOUT="/home/tebrandt/pm-graph-test"
STPKG="/home/tebrandt/workspace/packages/"

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
	KFILE="/home/tebrandt/workspace/stressconfig/kernel.txt"
	if [ ! -e $KFILE ]; then
		if [ "$1" != "quiet" ]; then
			echo "ERROR: missing the kernel version in kernel.txt"
			echo "- $KFILE"
			exit 1
		fi
		return 0
	fi
	KERNEL=`cat $KFILE`
	if [ -z "$KERNEL" ]; then
		if [ "$1" != "quiet" ]; then
			echo "ERROR: kernel is blank in kernel.txt"
			echo "- $KFILE"
			exit 1
		fi
		return 0
	fi
	IMAGE=`find $STPKG -name linux-image-*$KERNEL*.deb`
	HEADERS=`find $STPKG -name linux-headers-*$KERNEL*.deb`
	if [ -z "$IMAGE" -o -z "$HEADERS" ]; then
		if [ "$1" != "quiet" ]; then
			echo "ERROR: $KERNEL kernel packages are missing"
			echo "- $STPKG"
			exit 1
		fi
		return 0
	fi
	return 1
}

resetMachines() {
	TMP="/tmp/machine-file-temp.txt"
	FILE=$STDIR/machine-$KERNEL.txt
	if [ $1 = "mem" ]; then
		LIST="otcpl-dell-p3520 otcpl-asus-e300-apl otcpl-hp-x360-bsw"
	else
		LIST="otcpl-dell-p3520 otcpl-hp-spectre-tgl otcpl-lenovo-tix1-tgl otcpl-galaxy-book-10 otcpl-asus-e300-apl otcpl-hp-x360-bsw"
	fi
	CHECK=1
	nmap -sn 192.168.1.* --dns-servers 192.168.1.1 > /tmp/locals
	rm -f $TMP
	for m in $LIST;
	do
		IP=`grep $m /tmp/locals | head -1 | sed -e "s/.*(//" -e "s/)//g"`
		if [ -z "$IP" ]; then
			echo "$m not online"
			CHECK=0
		else
			echo "$m      $IP   labuser" >> $TMP
		fi
	done
	if [ $CHECK -eq 1 ]; then
		rm -f $FILE
		mv -f $TMP $FILE
	fi
	return $CHECK
}

resetMachinesReady() {
	READY="no"
	while [ -n "$READY" ] ; do
		RET=0
		while [ $RET -eq 0 ] ; do
			resetMachines $1
			RET=$?
			if [ $RET -eq 0 ]; then
				sleep 5
			fi
		done
		$STCMD -kernel $KERNEL -userinput online
		$STCMD -kernel $KERNEL ready
		READY=`grep -v "R o" $STDIR/machine-$KERNEL.txt`
		if [ -n "$READY" ]; then
			echo "MACHINES NOT READY"
			sleep 5
		fi
	done
}

resetMachinesOnline() {
	ONLINE="no"
	while [ -n "$ONLINE" ] ; do
		RET=0
		while [ $RET -eq 0 ] ; do
			resetMachines $1
			RET=$?
			if [ $RET -eq 0 ]; then
				sleep 5
			fi
		done
		$STCMD -kernel $KERNEL -userinput online
		ONLINE=`grep -v "O o" $STDIR/machine-$KERNEL.txt`
		if [ -n "$ONLINE" ]; then
			echo "MACHINES NOT ONLINE"
			sleep 5
		fi
	done
}

runMode() {
	resetMachinesReady $1
	echo "RUNNING $1 for $2 minutes"
	date
	$STCMD -kernel $KERNEL -mode $1 -duration $2 runmulti
	sleep $2m
	echo "CHECKING MACHINES"
	resetMachinesReady $1
	$STCMD -kernel $KERNEL reboot
	resetMachinesReady $1
	$STCMD -kernel $KERNEL -testout $OUTDIR -mode $1 getmulti
}

downloadPackages() {
	scp sleepgraph@otcpl-stress.ostc.intel.com:workspace/packages/*$1*.deb $STPKG
}

if [ $# -gt 2 -o $# -lt 1 ]; then printUsage; fi

OUTDIR="/media/zeus/pm-graph-test"
if [ $1 != "all" -a $1 != "help" ]; then
	getKernel
fi
if [ $1 = "help" ]; then
	printUsage
elif [ $1 = "info" ]; then
	echo "The current linux kernel is $KERNEL"
	echo "These are the package files:"
	cd $STPKG
	ls -l *$KERNEL*.deb | cut -c 36-
	echo "These are the machines currently defined:"
	cat $STMAC
elif [ $1 = "reset" ]; then
	resetMachinesReady "freeze"
elif [ $1 = "all" ]; then
	getKernel "quiet"
	if [ $? -eq 0 ]; then
		downloadPackages $KERNEL
		getKernel
	fi
	resetMachinesOnline "freeze"
	$STCMD -kernel $KERNEL tools
	$STCMD -kernel $KERNEL -kerneldefault install
	runMode "freeze" 60
	runMode "mem" 60
	runMode "disk" 60
	ssh -n -f sleepgraph@otcpl-stress.ostc.intel.com tmp-multitest.sh
elif [ $1 = "online" ]; then
	if [ $# -eq 1 ]; then
		$STCMD -kernel $KERNEL -userinput online
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
elif [ $1 = "reboot" ]; then
	$STCMD -kernel $KERNEL reboot
elif [ $1 = "tools" ]; then
	$STCMD -kernel $KERNEL tools
elif [ $1 = "install" ]; then
	$STCMD -kernel $KERNEL -kerneldefault install
elif [ $1 = "uninstall" ]; then
	$STCMD -kernel $KERNEL uninstall
elif [ $1 = "ready" ]; then
	$STCMD -kernel $KERNEL ready
elif [ $1 = "run" ]; then
	$STCMD -kernel $KERNEL -testout $OUTDIR -mode freeze -duration 1440 run
elif [ $1 = "runquick" ]; then
	$STCMD -kernel $KERNEL -testout $OUTDIR -mode freeze -duration 60 runmulti
elif [ $1 = "runmulti" ]; then
	$STCMD -kernel $KERNEL -mode freeze -duration 1440 runmulti
elif [ $1 = "runmultimem" ]; then
	$STCMD -kernel $KERNEL -mode mem -duration 60 runmulti
elif [ $1 = "runmultifreeze" ]; then
	$STCMD -kernel $KERNEL -mode freeze -duration 60 runmulti
elif [ $1 = "runmultidisk" ]; then
	$STCMD -kernel $KERNEL -mode disk -duration 60 runmulti
elif [ $1 = "runmultidiskshutdown" ]; then
	$STCMD -kernel $KERNEL -mode disk-shutdown -duration 30 runmulti
elif [ $1 = "runmultidiskreboot" ]; then
	$STCMD -kernel $KERNEL -mode disk-reboot -duration 30 runmulti
elif [ $1 = "getmulti" ]; then
	$STCMD -kernel $KERNEL -testout $OUTDIR getmulti
elif [ $1 = "getmultidisk" ]; then
	$STCMD -kernel $KERNEL -testout $OUTDIR -mode disk getmulti
elif [ $1 = "getmultidiskshutdown" ]; then
	$STCMD -kernel $KERNEL -testout $OUTDIR -mode disk-shutdown getmulti
elif [ $1 = "getmultidiskreboot" ]; then
	$STCMD -kernel $KERNEL -testout $OUTDIR -mode disk-reboot getmulti
elif [ $1 = "getmultifreeze" ]; then
	$STCMD -kernel $KERNEL -testout $OUTDIR -mode freeze getmulti
elif [ $1 = "getmultimem" ]; then
	$STCMD -kernel $KERNEL -testout $OUTDIR -mode mem getmulti
elif [ $1 = "status" ]; then
	$STCMD -kernel $KERNEL -testout $OUTDIR status
elif [ $1 = "report" ]; then
	URL="http://otcpl-stress.ostc.intel.com/pm-graph-test"
	WEBDIR="/home/tebrandt/pm-graph-test"
	SORTDIR="/home/tebrandt/pm-graph-sort"
	MS="/home/tebrandt/.machswap"
	GS="python3 /home/tebrandt/workspace/pm-graph/stressreport.py"
	ARGS="-bugzilla -webdir $WEBDIR -sortdir $SORTDIR -machswap $MS -parallel 8"
	cd $WEBDIR
	$GS $ARGS -urlprefix $URL/$KERNEL -stype sheet -genhtml -create both $KERNEL
else
	echo "\nUNKNOWN COMMAND: $1\n"
	printUsage
fi
