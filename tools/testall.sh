#!/bin/sh

CMD="../sleepgraph.py"
HOST=`hostname`
MODES=""
BATCH=0
CLEANUP=1
FREEZE=0
MEM=0

printhelp() {
	echo "USAGE: testall.sh [-h/-s/-f/-m]"
	echo "OPTIONS"
	echo "   -h: print help"
	echo "   -s: save output files after test"
	echo "   -f: test the freeze functionality"
	echo "   -m: test the mem functionality"
	echo "   -b: use minimal & easily parsable outputs for batch testing"
}

while [ "$1" ] ; do
	case "$1" in
		-h)
			shift
			printhelp
			exit
		;;
		-s)
			shift
			CLEANUP=0
		;;
		-b)
			shift
			BATCH=1
		;;
		-f)
			shift
			MODES="$MODES freeze"
		;;
		-m)
			shift
			MODES="$MODES mem"
		;;
		*)
			echo "Unknown option: $1"
			printhelp
			exit
		;;
	esac
done

if [ $CLEANUP -eq 1 ]; then
	OUTDIR=`mktemp -d`
else
	OUTDIR="$HOME/pm-graph-tool-testall"
	mkdir -p $OUTDIR
fi

finished() {
	if [ $CLEANUP -eq 0 ]; then
		printf "%-20s: %s\n" "OUTPUT" $OUTDIR
	else
		rm -r $OUTDIR
	fi
	exit
}

check() {
	OUTVAL=$?
	if [ $OUTVAL -ne 0 ]; then
		if [ $BATCH -eq 0 ]; then
			printf "%-20s: NON-ZERO EXIT %d\n" $1 $OUTVAL
			cat $2
		else
			INFO=`base64 -w 0 $2`
			printf "%-20s: FAIL\n" "RESULT"
			printf "%-20s: %s\n" "TEST" $1
			printf "%-20s: NON-ZERO EXIT %d\n" "ERROR" $OUTVAL
			printf "%-20s: %s\n" "LOG" $INFO
		fi
		finished
	fi
	TITLE=$1
	shift
	if [ -z "$1" ]; then
		if [ $BATCH -eq 0 ]; then
			printf "%-20s: PASS\n" $TITLE
		fi
	else
		FAIL=0
		while [ "$1" ] ; do
			if [ ! -e "$1" -o ! -s "$1" ]; then
				FAIL=1
				break
			fi
			shift
		done
		if [ $FAIL -eq 0 ]; then
			if [ $BATCH -eq 0 ]; then
				printf "%-20s: PASS\n" $TITLE
			fi
		else
			FILE=`basename $1`
			if [ $BATCH -eq 0 ]; then
				printf "%-20s: MISSING -> %s\n" $TITLE $FILE
			else
				printf "%-20s: FAIL\n" "RESULT"
				printf "%-20s: %s\n" "TEST" $TITLE
				printf "%-20s: MISSING FILE %s\n" "ERROR" $FILE
			fi
			finished
		fi
	fi
}

# one-off commands that require no suspend

$CMD -h > $OUTDIR/help.txt 2>&1
check "HELP" $OUTDIR/help.txt

$CMD -v > $OUTDIR/version.txt 2>&1
check "VERSION" $OUTDIR/version.txt

$CMD -modes > $OUTDIR/modes.txt 2>&1
check "MODES" $OUTDIR/modes.txt

$CMD -status > $OUTDIR/status.txt 2>&1
check "STATUS" $OUTDIR/status.txt

sudo $CMD -sysinfo > $OUTDIR/sysinfo.txt 2>&1
check "SYSINFO" $OUTDIR/sysinfo.txt

$CMD -devinfo > $OUTDIR/devinfo.txt 2>&1
check "DEVINFO" $OUTDIR/devinfo.txt

$CMD -cmdinfo > $OUTDIR/cmdinfo.txt 2>&1
check "CMDINFO" $OUTDIR/cmdinfo.txt

$CMD -wificheck > $OUTDIR/wifi.txt 2>&1
check "WIFICHECK" $OUTDIR/wifi.txt

sudo $CMD -flist > $OUTDIR/flist.txt 2>&1
check "FLIST" $OUTDIR/flist.txt

sudo $CMD -flistall > $OUTDIR/flistall.txt 2>&1
check "FLISTALL" $OUTDIR/flistall.txt

$CMD -xstat > $OUTDIR/display.txt 2>&1
check "DISPLAY" $OUTDIR/display.txt

# suspend dependent commands

AVAIL=`$CMD -modes | sed -e "s/[\',\[]//g" -e "s/\]//g"`
for m in $AVAIL; do
	if [ $m = "freeze" ]; then
		FREEZE=1
	elif [ $m = "mem" ]; then
		MEM=1
	fi
done

for m in $MODES; do
	if [ $m = "freeze" ]; then
		if [ $FREEZE -eq 0 ]; then continue; fi
		name="freeze"
	elif [ $m = "mem" ]; then
		if [ $MEM -eq 0 ]; then continue; fi
		name="mem   "
	else
		continue
	fi

	ARGS="-m $m -gzip -rtcwake 10 -verbose -addlogs -srgap -wifi -sync -rs off -display off -mindev 1"
	DMESG=${HOST}_${m}_dmesg.txt.gz
	FTRACE=${HOST}_${m}_ftrace.txt.gz
	HTML=${HOST}_${m}.html
	RESULT=result.txt

	OUT=$OUTDIR/suspend-${m}-simple
	sudo $CMD $ARGS -result $OUT/$RESULT -o $OUT > $OUT.txt 2>&1
	check "SIMPLE_$name" $OUT.txt $OUT/$DMESG $OUT/$FTRACE $OUT/$HTML $OUT/$RESULT

	OUT=$OUTDIR/suspend-${m}-dev
	sudo $CMD $ARGS -dev -result $OUT/$RESULT -o $OUT > $OUT.txt 2>&1
	check "DEV_$name" $OUT.txt $OUT/$DMESG $OUT/$FTRACE $OUT/$HTML $OUT/$RESULT

	OUT=$OUTDIR/suspend-${m}-proc
	sudo $CMD $ARGS -proc -result $OUT/$RESULT -o $OUT > $OUT.txt 2>&1
	check "PROC_$name" $OUT.txt $OUT/$DMESG $OUT/$FTRACE $OUT/$HTML $OUT/$RESULT

	OUT=$OUTDIR/suspend-${m}-devproc
	sudo $CMD $ARGS -dev -proc -result $OUT/$RESULT -o $OUT > $OUT.txt 2>&1
	check "DEVPROC_$name" $OUT.txt $OUT/$DMESG $OUT/$FTRACE $OUT/$HTML $OUT/$RESULT

	OUT=$OUTDIR/suspend-${m}-x2
	sudo $CMD $ARGS -x2 -x2delay 100 -predelay 100 -postdelay 100 -result $OUT/$RESULT -o $OUT > $OUT.txt 2>&1
	check "X2_$name" $OUT.txt $OUT/$DMESG $OUT/$FTRACE $OUT/$HTML $OUT/$RESULT

	OUT=$OUTDIR/suspend-${m}-cg
	sudo $CMD $ARGS -f -maxdepth 10 -result $OUT/$RESULT -o $OUT > $OUT.txt 2>&1
	check "CALLGRAPH_$name" $OUT.txt $OUT/$DMESG $OUT/$FTRACE $OUT/$HTML $OUT/$RESULT

	OUT=$OUTDIR/suspend-${m}-cgtop
	sudo $CMD $ARGS -ftop -maxdepth 10 -result $OUT/$RESULT -o $OUT > $OUT.txt 2>&1
	check "CALLGRAPHTOP_$name" $OUT.txt $OUT/$DMESG $OUT/$FTRACE $OUT/$HTML $OUT/$RESULT

	OUT=$OUTDIR/suspend-${m}-x3
	sudo $CMD $ARGS -multi 3 0 -maxfail 1 -result $OUT/$RESULT -o $OUT > $OUT.txt 2>&1
	check "MULTI_$name" $OUT.txt $OUT/$RESULT $OUT/summary.html $OUT/summary-devices.html $OUT/summary-issues.html

done

printf "%-20s: PASS\n" "RESULT"
finished
