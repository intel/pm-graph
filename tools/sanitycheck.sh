#!/bin/sh

if [ $# -ne 2 ]; then
	echo "Simple tester for comparaing outputs from two versions of"
	echo "sleepgraph. Runs on all timeline folders in the current path.\n"
	echo "  USAGE: sanitycheck.sh <sleepgraph-exec-1> <sleepgraph-exec-2>"
	exit
fi

SG1=$1
if [ ! -e $SG1 ]; then
	echo "NOT FOUND: $SG1"
	exit
fi
SG2=$2
if [ ! -e $SG2 ]; then
	echo "NOT FOUND: $SG2"
	exit
fi

for dir in `ls -1d suspend-*`
do
	echo "[$dir]"
	DMESG=`ls $dir/*_dmesg.txt 2>/dev/null`
	if [ -z "$DMESG" ]; then
		DMESG=`ls $dir/*_dmesg.txt.gz 2>/dev/null`
		if [ -z "$DMESG" ]; then
			echo "SKIPPING - dmesg not found"
			continue
		fi
	fi
	FTRACE=`ls $dir/*_ftrace.txt 2>/dev/null`
	if [ -z "$FTRACE" ]; then
		FTRACE=`ls $dir/*_ftrace.txt.gz 2>/dev/null`
		if [ -z "$FTRACE" ]; then
			echo "SKIPPING - ftrace not found"
			continue
		else
			CG=`gzip -cd $FTRACE | grep function_graph`
		fi
	else
		CG=`cat $FTRACE | grep function_graph`
	fi
	if [ -n "$CG" ]; then
		$SG1 -dmesg $DMESG -ftrace $FTRACE -f -cgskip off -o output.html > /dev/null
	else
		$SG1 -dmesg $DMESG -ftrace $FTRACE -dev -proc -o output.html > /dev/null
	fi
	if [ -e output.html ]; then
		SMSG1="--------------------------------------------------------"
		mv output.html $dir/output1.html
	else
		SMSG1="-----------------------MISSING--------------------------"
	fi
	if [ -n "$CG" ]; then
		$SG2 -dmesg $DMESG -ftrace $FTRACE -f -cgskip off -o output.html > /dev/null
	else
		$SG2 -dmesg $DMESG -ftrace $FTRACE -dev -proc -o output.html > /dev/null
	fi
	if [ -e output.html ]; then
		SMSG2="--------------------------------------------------------"
		mv output.html $dir/output2.html
	else
		SMSG2="-----------------------MISSING--------------------------"
	fi
	echo $SMSG1
	CHECK=""
	if [ -e $dir/output1.html -a -e $dir/output2.html ]; then
		CHECK=`diff $dir/output1.html $dir/output2.html`
	fi
	if [ -n "$CHECK" ]; then
		echo "$CHECK"
		echo "FAILURE - TIMELINES DIFFER!"
	fi
	echo $SMSG2
done
