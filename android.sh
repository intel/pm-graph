#!/bin/sh
#
# Tool for running a suspend/resume on android
# Copyright (c) 2014, Intel Corporation.
#
# This program is free software; you can redistribute it and/or modify it
# under the terms and conditions of the GNU General Public License,
# version 2, as published by the Free Software Foundation.
#
# This program is distributed in the hope it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or
# FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License for
# more details.
#
# You should have received a copy of the GNU General Public License along with
# this program; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin St - Fifth Floor, Boston, MA 02110-1301 USA.
#
# Authors:
#    Todd Brandt <todd.e.brandt@linux.intel.com>
#

KVERSION=""
MODES=""
MODE="mem"
RTCPATH=""
TPATH="/sys/kernel/debug/tracing"
EPATH="/sys/kernel/debug/tracing/events/power"
FTRACECHECK="yes"
TRACEEVENTS="yes"
HEADER=""
FTRACE="ftrace.txt"
DMESG="dmesg.txt"
LOGFILE="log.txt"
WAKETIME=""

setAlarm() {
	if [ -z "$WAKETIME" ]; then
		return
	fi
	NOW=`cat $RTCPATH/since_epoch`
	FUTURE=$(($NOW+$WAKETIME))
	echo $FUTURE > $RTCPATH/wakealarm
}

suspend() {
	date "+script start: %T" > $LOGFILE
	echo "------------------------------------"
	echo "Suspend/Resume timing test initiated"
	echo "------------------------------------"
	echo "hostname   : $HOSTNAME"
	echo "kernel     : $KVERSION"
	echo "mode       : $MODE"
	echo "ftrace out : $PWD/$FTRACE"
	echo "dmesg out  : $PWD/$DMESG"
	echo "log file   : $PWD/$LOGFILE"
	echo "------------------------------------"
	echo -n "INITIALIZING FTRACE"
	echo 0 > $TPATH/tracing_on
	echo -n "."
	echo global > $TPATH/trace_clock
	echo -n "."
	echo nop > $TPATH/current_tracer
	echo -n "."
	echo 1000 > $TPATH/buffer_size_kb
	echo -n "."
	echo 1 > $EPATH/suspend_resume/enable
	echo -n "."
	echo 1 > $EPATH/device_pm_callback_end/enable
	echo -n "."
	echo 1 > $EPATH/device_pm_callback_start/enable
	echo -n "."
	echo "" > $TPATH/trace
	echo -n "."
	dmesg -c > /dev/null
	echo "DONE"
	echo "STARTING FTRACE"
	echo 1 > $TPATH/tracing_on
	NOW=`date "+%T"`
	if [ -z "$WAKETIME" ]; then
		echo "SUSPEND START @ $NOW (press a key to resume)"
	else
		echo "SUSPEND START @ $NOW (rtcwake in $WAKETIME seconds)"
		setAlarm
	fi
	echo "<adb connection will now terminate>"
	echo "SUSPEND START" > $TPATH/trace_marker
	# execution will pause here
	date "+suspend start: %T" >> $LOGFILE
	echo $MODE > /sys/power/state
	date "+resume end: %T" >> $LOGFILE
	echo "RESUME COMPLETE" > $TPATH/trace_marker
	echo 0 > $TPATH/tracing_on
	echo $HEADER > $FTRACE
	cat $TPATH/trace >> $FTRACE
	echo "" > $TPATH/trace
	echo $HEADER >> $DMESG
	dmesg -c > $DMESG
	date "+script end: %T" >> $LOGFILE
}

checkStatus() {
	CHECK="no"
	for m in $MODES; do
		if [ $m = "$MODE" ]; then
			CHECK="yes"
		fi
	done
	if [ $CHECK != "yes" ]; then
		onError "mode ($MODE) is not supported"
	fi
	if [ $FTRACECHECK != "yes" ]; then
		echo " ERROR: ftrace is unsupported {"
		echo "     Please rebuild the kernel with these config options:"
		echo "         CONFIG_FTRACE=y"
		echo "         CONFIG_FUNCTION_TRACER=y"
		echo "         CONFIG_FUNCTION_GRAPH_TRACER=y"
		echo " }"
		exit
	fi
	if [ $TRACEEVENTS != "yes" ]; then
		echo " ERROR: trace events missing {"
		echo "    Please rebuild the kernel with the proper config patches"
		echo "    https://github.com/01org/suspendresume/tree/master/config"
		echo " }"
		exit
	fi
	if [ -n "$WAKETIME" -a -z "$RTCPATH" ]; then
		onError "rtcwake isn't available"
	fi
	if [ ! -w $PWD ]; then
		onError "read-only permissions for this folder"
	fi
}

init() {
	if [ $USER != "root" ]; then
		onError "Please run this script as root"
	fi
	if [ -z "$HOSTNAME" ]; then
		HOSTNAME=`hostname 2>/dev/null`
	fi
	check "/proc/version"
	# sometimes awk and sed are missing
	for i in `cat /proc/version`; do
		if [ $i != "Linux" -a $i != "version" ]; then
			KVERSION=$i
			break
		fi
	done
	check "/sys/power/state"
	MODES=`cat /sys/power/state`
	RTCPATH="/sys/class/rtc/rtc0"
	if [ -e "$RTCPATH" ]; then
		if [ ! -e "$RTCPATH" -o ! -e "$RTCPATH/since_epoch" -o \
			 ! -e "$RTCPATH/wakealarm" ]; then
			RTCPATH=""
		fi
	fi
	if [ -n "$RTCPATH" ]; then
		echo 0 > $RTCPATH/wakealarm
	fi
	files="buffer_size_kb current_tracer trace trace_clock trace_marker \
			trace_options tracing_on available_filter_functions \
			set_ftrace_filter set_graph_function"
	for f in $files; do
		if [ ! -e "$TPATH/$f" ]; then
			FTRACECHECK="no"
		fi
	done
	files="suspend_resume device_pm_callback_end device_pm_callback_start"
	for f in $files; do
		if [ ! -e "$EPATH/$f" ]; then
			TRACEEVENTS="no"
		fi
	done
	STAMP=`date "+suspend-%m%d%y-%H%M%S"`
	HEADER="# $STAMP $HOSTNAME $MODE $KVERSION"
}

printStatus() {
	echo "host    : $HOSTNAME"
	echo "kernel  : $KVERSION"
	echo "modes   : $MODES"
	if [ -n "$RTCPATH" ]; then
		echo "rtcwake : supported"
	else
		echo "rtcwake : unsupported (no rtc wakealarm found)"
	fi
	if [ $FTRACECHECK != "yes" ]; then
		echo " ftrace: unsupported (this is bad) {"
		echo "     Please rebuild the kernel with these config options:"
		echo "         CONFIG_FTRACE=y"
		echo "         CONFIG_FUNCTION_TRACER=y"
		echo "         CONFIG_FUNCTION_GRAPH_TRACER=y"
		echo " }"
	else
		echo "ftrace  : supported"
		echo "trace events {"
		files="suspend_resume device_pm_callback_end device_pm_callback_start"
		for f in $files; do
			if [ -e "$EPATH/$f" ]; then
				echo "    $f: found"
			else
				echo "    $f: missing"
			fi
		done
		if [ $TRACEEVENTS != "yes" ]; then
			echo ""
			echo "    one or more trace events missing!"
			echo "    Please rebuild the kernel with the proper config patches"
			echo "    https://github.com/01org/suspendresume/tree/master/config"
		fi
		echo "}"
	fi
	if [ $FTRACECHECK = "yes" -a $TRACEEVENTS = "yes" ]; then
		echo "status  : GOOD (you can test suspend/resume)"
	else
		echo "status  : BAD (system needs to be reconfigured for suspend/resume)"
	fi
}

printHelp() {
	echo "USAGE: android.sh command <args>"
	echo "COMMANDS:"
	echo "  help"
	echo "      print this help text"
	echo "  status"
	echo "      check that the system is configured properly"
	echo "  suspend <mem|freeze|standby|disk> [-rtcwake <sec>]"
	echo "      initiate a suspend/resume and gather ftrace/dmesg data"
	echo "      arg1 (required): suspend mode"
	echo "      arg2 (optional): use rtcwake"
	echo "      arg3 (optional): rtcwake time in seconds"
}

check() {
	if [ ! -e $1 ]; then
		onError "$1 not found"
	fi
}

onError() {
	echo "ERROR: $1"
	exit
}

if [ $# -lt 1 ]; then
	printHelp
	exit
fi

COMMAND=$1
shift
case "$COMMAND" in
	help)
		printHelp
	;;
	status)
		init
		printStatus
	;;
	suspend)
		if [ $# -lt 1 ]; then
			printHelp
			echo ""
			onError "suspend requires a mode (i.e. mem)"
		fi
		MODE=$1
		shift
		while [ "$1" ] ; do
			case "$1" in
				-rtcwake)
					shift
					if [ $# -lt 1 ]; then
						printHelp
						echo ""
						onError "-rtcwake needs an argument"
					fi
					WAKETIME=$1
					CHECK=$((0+$WAKETIME))
					if [ $CHECK -le 0 ]; then
						onError "$WAKETIME is not a valid positive integer"
					fi
				;;
				*)
					printHelp
					echo ""
					onError "Invalid suspend arg ($1)"
				;;
			esac
			shift
		done
		init
		checkStatus
		suspend
	;;
	*)
		printHelp
		echo ""
		onError "Invalid command ($COMMAND)"
	;;
esac
