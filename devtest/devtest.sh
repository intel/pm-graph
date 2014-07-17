#!/bin/bash

#
# Copyright 2014 Todd Brandt <todd.e.brandt@intel.com>
#
# This program is free software; you may redistribute it and/or modify it
# under the same terms as Perl itself.
#    trancearoundtheworld mp3 archive sync utility
#    Copyright (C) 2012 Todd Brandt <tebrandt@frontier.com>
#
#    This program is free software; you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation; either version 2 of the License, or
#    (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License along
#    with this program; if not, write to the Free Software Foundation, Inc.,
#    51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.
#

listTests() {
	DIRS=`ls -1`
	for d in $DIRS; do
		if [ -e "$d/run.sh" ]; then
			echo ""
			echo "$d:"
			cat $d/run.sh | head -2 | sed "s/# //"
		fi
	done
	echo ""
}

diffTests() {
	TYPE=$1
	ROOT=$PWD
	DIRS=`ls -1`
	for d in $DIRS; do
		if [ ! -d $ROOT/$d ]; then continue; fi
		if [ ! -e "$ROOT/$d/run.sh" ]; then continue; fi
		cd $ROOT/$d
		PARAMS=`cat run.sh | grep "# params = " | tail -1 | sed "s/.*params.*= //"`
		OUT=`cat run.sh | grep "# output file = " | tail -1 | sed "s/.*output.*file.*= //"`
		if [ -z "$OUT" ]; then onError "invalid format for $d/run.sh"; fi
		echo "-----------------------------------------"
		echo "$d/$OUT ($PARAMS)"
		echo ""
		if [ ! -e "control.html" ]; then
			printBad "FAIL - missing control.html"
			continue
		fi
		if [ ! -e "$OUT" ]; then
			printBad "FAIL - missing $OUT"
			continue
		fi
		CHECK=`diff -q control.html $OUT`
		if [ -z "$CHECK" ]; then
			printGood "PASS"
		else
			printBad "WARNING - Files differ"
			if [ $TYPE = "full" ]; then
				DIFF=`diff control.html $OUT`
				printDiff "$DIFF"
			fi
		fi
	done
	echo "-----------------------------------------"
	cd $ROOT
}

runTests() {
	TYPE=$1
	ROOT=$PWD
	DIRS=`ls -1`
	for d in $DIRS; do
		if [ ! -d $ROOT/$d ]; then continue; fi
		if [ ! -e "$ROOT/$d/run.sh" ]; then continue; fi
		cd $ROOT/$d
		echo "-----------------------------------------"
		echo "$d:"
		cat run.sh | head -2 | sed "s/# //"
		OUT=`cat run.sh | grep "# output file = " | tail -1 | sed "s/.*output.*file.*= //"`
		if [ -z "$OUT" ]; then onError "invalid format for $d/run.sh"; fi
		case "$TYPE" in
			control)
				rm -f $OUT control.html output.txt
				echo -n "Creating control output... "
				run.sh > output.txt
				if [ ! -e $OUT ]; then onError "test failed, see $d/output.txt"; fi
				cp -f $OUT control.html
				echo "DONE"
			;;
			*)
				rm -f $OUT output.txt
				echo -n "Running the test... "
				run.sh > output.txt
				if [ ! -e $OUT ]; then onError "test failed, see $d/output.txt"; fi
				CHECK=`diff -q control.html $OUT`
				if [ -z "$CHECK" ]; then
					printGood "PASS"
				else
					printBad "WARNING - Files differ"
					if [ $TYPE = "full" ]; then
						diff control.html $OUT
					fi
				fi
			;;
		esac
	done
	cd $ROOT
}

printHelp() {
	echo ""
	echo "USAGE: devtest.sh command <args>"
	echo "  Commands:"
	echo "     list"
	echo "        desc : list all the tests currently available"
	echo "        args : none"
	echo "     run"
	echo "        desc : execute the tests"
	echo "        args : control, quick, full"
	echo "         control - run all tests and make the outputs the new controls"
	echo "           quick - run all tests and check for differences (default)"
	echo "            full - run all tests and print any differences"
	echo "     diff"
	echo "        desc : compare all current outputs to the controls"
	echo "        args : quick, full"
	echo "           quick - run all tests and check for differences (default)"
	echo "            full - run all tests and print any differences"
	echo ""
}

printDiff() {
	echo -e "\e[33m$1\e[39m"
}

printGood() {
	echo -e "\e[32m$1\e[39m"
}

printBad() {
	echo -e "\e[31m$1\e[39m"
}

onError() {
	if [ $2 ]; then
		printHelp
	else
		echo ""
	fi
	printBad "ERROR: $1"
	echo ""
	exit
}

# -- parse commands and arguments --

if [ $# -lt 1 ]; then printHelp; exit; fi

COMMAND=$1
shift
case "$COMMAND" in
	list)
		listTests
	;;
	diff)
		TYPE="quick"
		if [ $# -gt 0 ]; then
			TYPE="$1"
		fi
		case "$TYPE" in
			quick);;
			full);;
			*)
				onError "Invalid diff type ($TYPE)" true
			;;
		esac
		diffTests $TYPE
	;;
	run)
		TYPE="quick"
		if [ $# -gt 0 ]; then
			TYPE="$1"
		fi
		case "$TYPE" in
			control)
				echo "CREATING NEW CONTROLS"
				runTests $TYPE
			;;
			quick)
				echo "QUICK TEST"
				runTests $TYPE
			;;
			full)
				echo "FULL TEST"
				runTests $TYPE
			;;
			*)
				onError "Invalid test type ($TYPE)" true
			;;
		esac
	;;
	*)
		onError "Invalid command ($COMMAND)" true
	;;
esac
