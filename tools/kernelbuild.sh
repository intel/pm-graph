#!/bin/sh

# args
OUTPATH="$HOME/workspace"
SRCPATH="$HOME/workspace/linux"
REBOOT="no"
NAME=""

# build info
ARCH="amd64"
KVER=""
BVER=""
PKGS=""
KREL=""
PKG="deb"

printUsage() {
    echo "USAGE: kernelbuild.sh command <args>"
    echo "COMMANDS:"
    echo "  build - build a new kernel and optionally install it"
    echo "    args: name <rpm/deb> <machine> <reboot>"
    echo "  install - install packages from current build"
    echo "    args: machine <reboot>"
    echo "  info - print out what's currently built"
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
    KVER=`cd $SRCPATH; make kernelrelease 2>/dev/null`
    BVER=`cat $SRCPATH/.version 2>/dev/null`
    KREL=`cat $SRCPATH/include/config/kernel.release 2>/dev/null`
	if [ -z "$NAME" ]; then
		PKGS="linux-headers-${KVER}_${KVER}-${BVER}_${ARCH}.$PKG \
			linux-image-${KVER}_${KVER}-${BVER}_${ARCH}.$PKG \
			linux-libc-dev_${KVER}-${BVER}_${ARCH}.$PKG"
	else
		PKGS="linux-headers-${KVER}-${NAME}_${KVER}-${NAME}-${BVER}_${ARCH}.$PKG \
			linux-image-${KVER}-${NAME}_${KVER}-${NAME}-${BVER}_${ARCH}.$PKG \
			linux-libc-dev_${KVER}-${NAME}-${BVER}_${ARCH}.$PKG"
	fi
}

getExpectedPackages() {
    getArch
    KVER=`cd $SRCPATH; make kernelrelease 2>/dev/null`
    BVER=`cat $SRCPATH/.version 2>/dev/null`
	if [ -z "$NAME" ]; then
		PKGS="linux-headers-${KVER}_${KVER}-${BVER}_${ARCH}.$PKG \
			linux-image-${KVER}_${KVER}-${BVER}_${ARCH}.$PKG \
			linux-libc-dev_${KVER}-${BVER}_${ARCH}.$PKG"
	else
		PKGS="linux-headers-${KVER}-${NAME}_${KVER}-${NAME}-${BVER}_${ARCH}.$PKG \
			linux-image-${KVER}-${NAME}_${KVER}-${NAME}-${BVER}_${ARCH}.$PKG \
			linux-libc-dev_${KVER}-${NAME}-${BVER}_${ARCH}.$PKG"
	fi
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
        CHECK=`ping -q -w 10 $SERVER | grep ", 0% packet loss,"`
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
	if [ -z "$NAME" ]; then
	    make -j `getconf _NPROCESSORS_ONLN` $PKG-pkg
	else
	    make -j `getconf _NPROCESSORS_ONLN` $PKG-pkg LOCALVERSION=-$NAME
	fi
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
        if [ $# -gt 5 -o $# -lt 1 ]; then
            printUsage
        fi
        if [ $# -ge 2 ]; then
	        if [ $2 = "none" -o $2 = "NONE" ]; then
				NAME=""
			else
		        NAME=$2
			fi
        fi
        if [ $# -ge 3 ]; then
	        if [ $3 != "deb" -a $3 != "rpm" ]; then
		        echo "\nUUNKNOW package type: $3 [use deb or rpm]\n"
			fi
	        PKG="$3"
        fi
        if [ $# -ge 4 ]; then
            if [ $# -ge 5 ]; then
                checkReboot $5
            fi
            SERVER=$4
            testServer
        fi
        buildKernel
        if [ $# -ge 4 ]; then
            installKernel
        fi
    else
        echo "\nUNKNOWN COMMAND: $1\n"
        printUsage
    fi
fi
