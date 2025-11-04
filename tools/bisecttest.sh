#!/bin/sh

# Bisect Arguments
# -kgood		newest good commit/tag
# -kbad			oldest bad commit/tag
# -ktest		the script to run on DUT to detect error
# -ksrc			linux kernel source folder to bisect/build in
# -kcfg			folder with latest.config and any *.patch files
# -user			username to use on DUT ssh
# -host			hostname of DUT
# -addr			ip address of DUR
# -pkgout		Folder to place the bisect kernel package files
# -pkgfmt		package format: deb or rpm.
# -userinput	allow user input incase something goes awry
# -resetcmd		command that restarts a hung DUT, takes {host} as arg

time ./stresstest.py \
	-kgood v6.16 \
	-kbad v6.17-rc1 \
	-ktest bisect-test.sh \
	-ksrc ~/workspace/linux \
	-kcfg ~/workspace/stressconfig \
	-user labuser \
	-host otcpl-jsl-p \
	-addr 10.54.97.135 \
	-pkgout ~/workspace/bisecttest \
	-pkgfmt deb \
	-userinput \
	-resetcmd "labmachine -m {host} restart" \
	bisect
