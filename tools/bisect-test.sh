#!/bin/sh

cd /tmp
rm -rf bisecttest
rm -f result*.txt sleepgraph*.txt

sudo sleepgraph -m disk-reboot -rtcwake 30 -result result.txt -dev -o bisecttest > sleepgraph.txt
FAIL=`grep fail result.txt`
if [ -n "$FAIL" ]; then
	echo "ERROR"
	exit
fi
RES=`grep resume: result.txt | sed -e "s/r\S* //g"`
if [ -z "$RES" ]; then
	echo "ERROR"
	exit
fi
HTML=`ls -1 bisecttest/otcpl-*disk.html 2>/dev/null`
if [ -z "$HTML" ]; then
	echo "ERROR"
	exit
fi
CPU=`grep "CPU_ON\[1\]" $HTML | sed -e "s/.*(//g" -e "s/ ms).*//g"`
if [ -n "$CPU" ]; then
	VAL=`echo "$CPU > 5000" | bc`
	if [ $VAL -eq 1 ]; then
		echo "BAD"
		exit
	fi
fi
VAL=`echo "$RES > 8000" | bc`
if [ $VAL -eq 1 ]; then
	echo "BAD"
	exit
fi
echo "GOOD"
