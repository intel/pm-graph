#!/bin/sh

#
# Copyright 2012 Todd Brandt <tebrandt@frontier.com>
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

OUTPATH="$HOME/workspace"
SRCPATH="$HOME/workspace/linux"
REBOOT="no"
NAME=""

# build info
ARCH=""
KVER=""
BVER=""
PKGS=""
KREL=""

printUsage() {
    echo "USAGE: kernelbuild.sh command <args>"
    echo "COMMANDS:"
    echo "  build - build a new kernel and optionally install it"
    echo "    args: name <machine> <reboot>"
    echo "install - install packages from current build"
    echo "    args: machine <reboot>"
    echo "   info - print out what's currently built"
    exit
}

getArch() {
    DEFCON=`grep -s "^CONFIG_ARCH_DEFCONFIG=\"arch/x86/configs/" $SRCPATH/.config`
    if [ -n "$DEFCON" ]; then
        KARCH=`echo $DEFCON | sed "s/.*configs\///;s/_defconfig.*//"`
        if [ "$KARCH" = "x86_64" ]; then
            ARCH="amd64"
        elif [ "$KARCH" = "i386" ]; then
            ARCH="i386"
        fi
    fi
}

getCurrentPackages() {
    getArch
    KVER=`cd $SRCPATH; make kernelversion 2>/dev/null`
    BVER=`cat $SRCPATH/.version 2>/dev/null`
    KREL=`cat $SRCPATH/include/config/kernel.release 2>/dev/null`
    PKGS="linux-firmware-image-${KREL}_${KREL}-${BVER}_${ARCH}.deb \
          linux-headers-${KREL}_${KREL}-${BVER}_${ARCH}.deb \
          linux-image-${KREL}_${KREL}-${BVER}_${ARCH}.deb \
          linux-libc-dev_${KREL}-${BVER}_${ARCH}.deb"
}

getExpectedPackages() {
    getArch
    KVER=`cd $SRCPATH; make kernelversion 2>/dev/null`
    BVER=`cat $SRCPATH/.version 2>/dev/null`
    PKGS="linux-firmware-image-${KVER}-${NAME}_${KVER}-${NAME}-${BVER}_${ARCH}.deb \
          linux-headers-${KVER}-${NAME}_${KVER}-${NAME}-${BVER}_${ARCH}.deb \
          linux-image-${KVER}-${NAME}_${KVER}-${NAME}-${BVER}_${ARCH}.deb \
          linux-libc-dev_${KVER}-${NAME}-${BVER}_${ARCH}.deb"
}

checkReboot() {
    REBOOT="no"
    if [ $1 = "reboot" ]; then
        REBOOT="yes"
    else
        printUsage
    fi
}

printVersion() {
    getCurrentPackages
    echo "\nKernel Info:"
    echo "  Version: $KVER"
    echo "  Release: $KREL"
    echo "    Build: $BVER"
    echo "     Arch: $ARCH"
    echo "Built Packages:"
    cd $OUTPATH
    for file in $PKGS
    do
        if [ -e $file ]; then
            echo "  FOUND: $file"
        else
            echo "  MISSING: $file"
        fi
    done
    echo ""
    exit
}

testServer() {
    if [ "$SERVER" != "local" ]; then
        CHECK=`ping -q -w 5 $SERVER | grep ", 0% packet loss,"`
        if [ -z "$CHECK" ]; then
            echo "Host $SERVER is unreachable"
            exit
        fi
        echo "$SERVER found"
    fi
}

buildKernel() {
    getExpectedPackages
    if [ -z "$ARCH" ]; then
        echo "ERROR: The .config file is either missing or set to a non-x86 architecture"
        exit
    fi
    echo "Bulding kernel ${KVER}-${NAME} for ${ARCH}"
    cd $SRCPATH
    make oldconfig
    make -j `getconf _NPROCESSORS_ONLN` deb-pkg LOCALVERSION=-$NAME
    getExpectedPackages
    cd $OUTPATH
    for file in $PKGS
    do
        if [ ! -e $file ]; then
            echo "ERROR: $file doesn't exist"
            exit
        fi
    done
    PKGS=`ls -1 $PKGS | tr '\n' ' '`
    echo $PKGS
    echo "BUILD COMPLETE"
    for file in $PKGS
    do
        ls -1 $OUTPATH/$file
    done
}

installKernel() {
    if [ -n "$SERVER" ]; then
        cd $OUTPATH
        if [ $SERVER = "local" ]; then
            echo "INSTALLING LOCALLY"
            sudo dpkg -i $PKGS
            if [ "$REBOOT" = "yes" ]; then
                sleep 4
                echo "REBOOTING $HOSTNAME"
                sudo reboot
            fi
        else
            echo "INSTALLING ON $SERVER"
            scp $PKGS ${SERVER}:/tmp/
            ssh -X root@$SERVER "cd /tmp; dpkg -i $PKGS"
            if [ "$REBOOT" = "yes" ]; then
                sleep 4
                echo "REBOOTING $SERVER"
                ssh -X root@$SERVER "reboot"
            fi
        fi
    fi
}

if [ $# -gt 5 -o $# -lt 1 ]; then
    printUsage
else
    if [ $1 = "info" ]; then
        printVersion
        exit
    elif [ $1 = "install" ]; then
        if [ $# -gt 3 -o $# -lt 2 ]; then
            printUsage
        fi
        SERVER=$2
        if [ $# -eq 3 ]; then
            checkReboot $3
        fi
        testServer
        getCurrentPackages
        installKernel
        exit
    elif [ $1 = "build" ]; then
        if [ $# -gt 4 -o $# -lt 2 ]; then
            printUsage
        fi
        NAME=$2
        if [ $# -ge 3 ]; then
            if [ $# -eq 4 ]; then
                checkReboot $4
            fi
            SERVER=$3
            testServer
        fi
        buildKernel
        if [ $# -ge 3 ]; then
            installKernel
        fi
    else
        echo "\nUNKNOWN COMMAND: $1\n"
        printUsage
    fi
fi
