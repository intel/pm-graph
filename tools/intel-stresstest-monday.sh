#!/bin/sh

KFILELAST="/home/sleepgraph/workspace/stressconfig/kernel-last.txt"
KFILE="/home/sleepgraph/workspace/stressconfig/kernel.txt"

CHECK=`diff -q $KFILELAST $KFILE`
if [ -n "$CHECK" ]; then
	LOG=`date "+/home/sleepgraph/stresslogs/%y%m%d-%H%M%S-stressreport.txt"`
	intel-stresstest reportlast > $LOG 2>&1
fi
LOG=`date "+/home/sleepgraph/stresslogs/%y%m%d-%H%M%S-stressreport.txt"`
intel-stresstest report > $LOG 2>&1
