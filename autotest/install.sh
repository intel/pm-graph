#!/bin/sh

TESTPATH='/usr/share/chromiumos/src/third_party/autotest/files/client/site_tests'

for file in `ls -1` ;
do
	if [ ! -d $file ]; then continue; fi
	cp -rfL $file $TESTPATH
done
