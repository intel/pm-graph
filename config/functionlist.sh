#!/bin/sh

if [ $# -eq 0 ]; then
    echo "USAGE: <kernel subdir1> <kernel subdir2> ..."
    exit
fi

RPATH=$PWD
while [ $# -gt 0 ]
do
    cd $RPATH
    if [ -d $1 ]; then
        cd $1
        egrep -srh "EXPORT_SYMBOL" * | sed -e "s/.*EXPORT_SYMBOL.*(//;s/).*//"
    fi
    shift
done
