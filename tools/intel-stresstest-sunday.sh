#!/bin/sh

KFILELAST="/home/sleepgraph/workspace/stressconfig/kernel-last.txt"
KFILE="/home/sleepgraph/workspace/stressconfig/kernel.txt"

CHECK=`diff -q $KFILELAST $KFILE`
if [ -z "$CHECK" ]; then
	exit
fi

CHECK=`ps aux | grep -v grep | grep run | grep /home/sleepgraph/pm-graph/stresstest.py`

if [ -n "$CHECK" ]; then
	echo "stress testing appears to be running already"
	exit
fi

LOG=`date "+/home/sleepgraph/stresslogs/%y%m%d-%H%M%S-stresstest.txt"`

labmachine killjobs > $LOG 2>&1
intel-stresstest resetwired >> $LOG 2>&1
intel-stresstest turbostat >> $LOG 2>&1
intel-stresstest online restart >> $LOG 2>&1
intel-stresstest install >> $LOG 2>&1
sleep 180
intel-stresstest reset >> $LOG 2>&1
intel-stresstest online restart >> $LOG 2>&1
intel-stresstest ready >> $LOG 2>&1
intel-stresstest runquick >> $LOG 2>&1
