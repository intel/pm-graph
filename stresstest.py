#!/usr/bin/env python3
#
# Sleepgraph Stress Tester
#

import os
import sys
import re
import shutil
import time
from subprocess import call, Popen, PIPE
from datetime import date, datetime, timedelta
import argparse
import os.path as op
from lib.parallel import AsyncProcess, MultiProcess, findProcess
from lib.argconfig import args_from_config, arg_to_path
from lib.remotemachine import RemoteMachine
from lib import kernel
from lib.common import mystarttime, pprint, printlines, ascii, runcmd, userprompt, userprompt_yesno

blacklist = {
	'mem': [
	],
	'disk': [
	]
}

validmodes = [
	'standby',
	'freeze',
	'mem',
	'disk',
	'mem-s2idle',
	'disk-platform',
	'disk-shutdown',
	'disk-reboot',
	'disk-suspend',
	'disk-test_resume'
]

def baseMode(mode):
	return 'freeze' if 's2idle' in mode else mode.split('-')[0]

def doError(msg, machine=None, fatal=True):
	pprint('ERROR: %s\n' % msg)
	if not fatal:
		return
	if machine:
		machine.release_machine()
	sys.exit(1)

def turbostatBuild(args):
	if args.ksrc:
		kernel.turbostatbuild(args.ksrc, True)

def kernelBuild(args):
	if not args.pkgfmt or not args.kcfg:
		doError('kernel build is missing arguments')

	# clone the kernel if no source is given
	cloned = False
	if not args.ksrc:
		args.ksrc = kernel.clone()
		cloned = True

	# set the repo to the right tag
	isgit = kernel.isgit(args.ksrc)
	if args.ktag:
		if not isgit:
			doError('%s is not a git folder, tag can\'t be set' % args.ksrc)
		runcmd('git -C %s checkout .' % args.ksrc, True)
		if args.ktag == 'latestrc':
			runcmd('git -C %s checkout master' % args.ksrc, True)
			runcmd('git -C %s pull' % args.ksrc, True)
			args.ktag = runcmd('git -C %s describe --abbrev=0 --tags' % args.ksrc)[0]
			pprint('Latest RC is %s' % args.ktag)
		elif args.ktag != 'master':
			tags = runcmd('git -C %s tag' % args.ksrc)
			if args.ktag not in tags:
				doError('%s is not a valid tag' % args.ktag)
		runcmd('git -C %s checkout %s' % (args.ksrc, args.ktag), True)

	# apply kernel patches
	kconfig = kernel.configure(args.ksrc, args.kcfg, isgit)

	# clean the source
	kernel.clean(args.ksrc, kconfig, False)

	# build the kernel
	outdir, kver, packages = kernel.build(args.ksrc, args.pkgfmt, args.kname)
	if cloned:
		shutil.rmtree(args.ksrc)
		args.ksrc = ''

	# move the output files to the output folder
	if args.pkgout:
		kernel.move_packages(outdir, args.pkgout, packages)
		outdir = args.pkgout
	else:
		args.pkgout = outdir

	pprint('DONE')
	pprint('Kernel is %s\nPackages in %s' % (kver, outdir))
	out = []
	for file in sorted(packages):
		out.append(op.join(outdir, file))
		print('%s' % file)
	return out

def installtools(args, m):
	if not (args.user and args.host and args.addr):
		doError('install tools is missing arguments', m)

	# connect to the right machine
	pprint('check host is online and the correct one')
	res = m.checkhost(args.userinput)
	if res:
		doError('%s: %s' % (m.host, res), m)

	# install tools
	pprint('install ethtool')
	m.sshcmd('sudo apt-get update', 120)
	out = m.sshcmd('sudo apt-get -y install ethtool iw', 120)
	printlines(out)
	pprint('install mcelog')
	out = m.install_mcelog(args.proxy)
	printlines(out)
	pprint('install sleepgraph')
	out = m.install_sleepgraph(args.proxy)
	printlines(out)
	out = m.sshcmd('grep submitOptions /usr/lib/pm-graph/sleepgraph.py', 10).strip()
	if out:
		doError('%s: sleepgraph installed with "submit" branch' % m.host, m)
	if args.ksrc:
		pprint('install turbostat')
		tfile = op.join(args.ksrc, 'tools/power/x86/turbostat/turbostat')
		if op.exists(tfile):
			m.scpfile(tfile, '/tmp')
			printlines(m.sshcmd('sudo cp /tmp/turbostat /usr/bin/', 10))
		else:
			pprint('WARNING: turbostat did not build')

	# system status
	pprint('sleepgraph modes')
	printlines(m.sshcmd('sleepgraph -modes', 10))
	pprint('disk space available')
	printlines(m.sshcmd('df /', 10))

def kernelInstall(args, m, fatal=True, default=False):
	if not (args.pkgout and args.user and \
		args.host and args.addr and args.kernel):
		doError('kernel install is missing arguments', m)

	# get the kernel packages for our version
	pprint('os check')
	os = m.oscheck()
	pprint('%s is running %s' % (m.host, os))
	if os in ['ubuntu']:
		packages = kernel.get_packages_deb(args.pkgout, args.kernel)
	elif os in ['fedora', 'centos']:
		packages = kernel.get_packages_rpm(args.pkgout, args.kernel)
	else:
		doError('Unrecognized operating system: %s' % os, m, fatal)
		return False
	if len(packages) < 1:
		doError('no kernel packages found for "%s"' % args.kernel, m, fatal)
		return False

	# connect to the right machine
	pprint('check host is online and the correct one')
	res = m.checkhost(args.userinput)
	if res:
		doError('%s: %s' % (m.host, res), m, fatal)
		return False

	# configure the system
	pprint('boot setup')
	m.bootsetup()
	pprint('wifi setup')
	out = m.wifisetup(True)
	if out:
		pprint('WIFI DEVICE NAME: %s' % m.wdev)
		pprint('WIFI MAC ADDRESS: %s' % m.wmac)
		pprint('WIFI ESSID      : %s' % m.wap)
		pprint('WIFI IP ADDRESS : %s' % m.wip)
		printlines(out)
	if os == 'ubuntu':
		pprint('configure grub')
		out = m.configure_grub()
		printlines(out)

	# remove unneeeded space
	pprint('remove previous test data')
	printlines(m.sshcmd('rm -rf pm-graph-test ; mkdir pm-graph-test', 10))
	if args.rmkernel:
		pprint('remove old kernels')
		kernelUninstall(args, m)

	# install tools
	pprint('install ethtool')
	m.sshcmd('sudo apt-get update', 120)
	out = m.sshcmd('sudo apt-get -y install ethtool iw', 120)
	printlines(out)
	pprint('install mcelog')
	out = m.install_mcelog(args.proxy)
	printlines(out)
	pprint('install sleepgraph')
	out = m.install_sleepgraph(args.proxy)
	printlines(out)
	out = m.sshcmd('grep submitOptions /usr/lib/pm-graph/sleepgraph.py', 10).strip()
	if out:
		doError('%s: sleepgraph installed with "submit" branch' % m.host, m, fatal)
		return False
	if args.ksrc:
		pprint('install turbostat')
		tfile = op.join(args.ksrc, 'tools/power/x86/turbostat/turbostat')
		if op.exists(tfile):
			m.scpfile(tfile, '/tmp')
			printlines(m.sshcmd('sudo cp /tmp/turbostat /usr/bin/', 10))
		else:
			pprint('WARNING: turbostat did not build')

	# install the kernel
	pprint('checking kernel versions')
	if not m.list_kernels(os):
		doError('%s: could not list installed kernel versions' % m.host, m, fatal)
		return False
	pprint('uploading kernel packages')
	pkglist = []
	for pkg in packages:
		pkglist.append(op.join('/tmp', pkg))
		m.scpfile(op.join(args.pkgout, pkg), '/tmp')
	pprint('installing the kernel')
	out, res = m.install_kernel(os, args.kernel, pkglist, default)
	printlines(out)
	if not res:
		doError('%s: %s failed to install' % (m.host, args.kernel), m, fatal)
		return False
	pprint('kernel install completed')

	# system status
	pprint('sleepgraph modes')
	printlines(m.sshcmd('sleepgraph -modes', 10))
	pprint('disk space available')
	printlines(m.sshcmd('df /', 10))
	return True

def kernelUninstall(args, m):
	if not (args.user and args.host and args.addr and args.rmkernel):
		doError('kernel uninstall is missing arguments', m)
	try:
		re.match(args.rmkernel, '')
	except:
		doError('kernel regex caused an exception: "%s"' % args.rmkernel, m)
	pprint('os check')
	os = m.oscheck()
	pprint('%s is running %s' % (m.host, os))
	packages = m.list_kernel_packages(os)
	for pkg in packages:
		if kernel.kvermatch(args.rmkernel, os, pkg):
			pprint('removing %s ...' % pkg)
			out = m.uninstall_package(os, pkg)
			printlines(out)

def kernelBisect(args, m):
	if not (args.kgood and args.kbad and args.user and args.host \
		and args.addr and args.ksrc and args.kcfg and args.pkgfmt):
		doError('kernel bisect is missing arguments', m)
	if not args.ktest and not args.userinput:
		doError('you must provide a ktest or allow userinput to bisect')
	if not kernel.isgit(args.ksrc):
		doError('kernel source folder is not a git tree')

	# clean up the source and ready it for build
	kconfig = kernel.getconfig(args.kcfg)
	if not kconfig:
		doError('bisect requires a kconfig in the kcfg folder')
	kernel.clean(args.ksrc, kconfig, True)
	commit, done = kernel.bisect_start(args.ksrc, args.kgood, args.kbad)
	if done:
		print('\nBAD COMMIT: %s' % commit)
		return
	kernel.configure(args.ksrc, args.kcfg, True)

	# perform the bisect
	for i in range(1, 100):
		resets, state, name = 0, '', 'bisect%d' % i

		# build the latest commit package
		while True:
			pprint('BUILD %s from commit %s' % (name, commit))
			outdir, kver, packages = kernel.build(args.ksrc, args.pkgfmt, name)
			if len(packages) > 0:
				args.kernel = kver
				break
			pprint('BUILD ERROR (%s): %s' % (name, commit))
			if args.userinput:
				out = userprompt('Would you like to try again? (yes/no) or skip the commit (skip)?',
					['yes', 'no', 'skip'])
				if out == 'yes':
					continue
				elif out == 'skip':
					runcmd('git -C %s checkout .' % args.ksrc, True)
					commit, done = kernel.bisect_step(args.ksrc, 'skip')
					if done:
						print('\nBAD COMMIT: %s' % commit)
						return
					kernel.configure(args.ksrc, args.kcfg, True)
					continue
			if args.userinput and userprompt_yesno('Would you like to try again?'):
				continue
			doError('Bisect failed due to build issue')

		# move the packages
		if args.pkgout:
			kernel.move_packages(outdir, args.pkgout, packages)
			outdir = args.pkgout
		else:
			args.pkgout = outdir

		# test if the system is online, else restart or ask for help
		while True:
			pprint('WAIT for %s to come online' % args.host)
			error = m.wait_for_boot('', 120)
			if not error:
				break
			pprint('CONNECTION ERROR (%s): %s' % (args.host, error))
			if m.resetcmd and resets < 2:
				pprint('Restarting %s' % args.host)
				m.reset_machine()
				resets += 1
				time.sleep(10)
				continue
			elif args.userinput and userprompt_yesno('Would you like to reset manually?'):
				continue
			doError('Bisect failed, target machine failed to come online')

		# install the kernel
		while True:
			pprint('INSTALL %s on %s' % (args.kernel, args.host))
			if kernelInstall(args, machine, False, False):
				break
			pprint('INSTALL ERROR (%s): %s' % (args.host, args.kernel))
			if args.userinput and userprompt_yesno('Would you like to try again?'):
				continue
			doError('Bisect failed due to installation issue')
		pprint('REBOOT %s' % args.host)
		m.sshcmd('sudo reboot', 30)

		# wait for the system to boot the kernel
		while True:
			pprint('WAIT for %s to boot %s' % (args.host, args.kernel))
			error = m.wait_for_boot(args.kernel, 180)
			if not error:
				break
			elif args.bisecthangbad:
				state = 'bad'
				break
			pprint('BOOT ERROR (%s): %s' % (args.host, error))
			if m.resetcmd and resets < 2:
				pprint('Restarting %s' % args.host)
				m.reset_machine()
				resets += 1
				time.sleep(10)
				continue
			elif args.userinput:
				out = userprompt('Keep checking (yes/no) or grade the test (good/bad)?',
					['yes', 'no', 'good', 'bad'])
				if out == 'yes':
					continue
				elif out in ['good', 'bad']:
					state = out
					break
			doError('Bisect failed, target machine failed to boot the kernel')

		# if state is decided without a boot, move on
		if state:
			pprint('STATE is %s for %s' % (state.upper(), commit))
			runcmd('git -C %s checkout .' % args.ksrc, True)
			commit, done = kernel.bisect_step(args.ksrc, state)
			if done:
				print('\nBAD COMMIT: %s' % commit)
				return
			kernel.configure(args.ksrc, args.kcfg, True)
			continue

		# perform the ktest
		if args.ktest:
			while True:
				out, error, ktest = "", 'SCP FAILED', op.basename(args.ktest)
				if m.scpfile(args.ktest, '/tmp'):
					m.sshcmd('chmod 755 /tmp/%s' % ktest, 30)
					out = m.sshcmd('/tmp/%s' % ktest, 300, False, False, False)
					error = out.strip().split('\n')[-1]
				if error in ['GOOD', 'BAD']:
					state = error.lower()
					break
				elif 'SSH TIMEOUT' in error:
					state = 'bad'
					break
				pprint('KTEST ERROR (%s): %s' % (ktest, error))
				if args.userinput:
					state = userprompt('Is this kernel good or bad?', ['good', 'bad', 'retry'])
					if state == 'retry':
						continue
					break
				doError('Bisect failed, ktest failed to run on the target machine')
		elif args.userinput:
			state = userprompt('Is this kernel good or bad?', ['good', 'bad'])

		# state is decided, move on
		pprint('STATE is %s for %s' % (state.upper(), commit))
		runcmd('git -C %s checkout .' % args.ksrc, True)
		commit, done = kernel.bisect_step(args.ksrc, state)
		if done:
			print('\nBAD COMMIT: %s' % commit)
			return
		kernel.configure(args.ksrc, args.kcfg, True)

def pm_graph_multi_download(args, m, dotar=False, doscp=False):
	if not (args.user and args.host and args.addr and args.kernel):
		doError('getmulti is missing arguments (kernel)')
	hostout = args.testout if args.testout else '/tmp'
	if args.mode:
		tarball = '%s-%s-%s.tar.gz' % (args.host, args.kernel, args.mode)
	else:
		tarball = '%s-%s.tar.gz' % (args.host, args.kernel)
	if not dotar and not doscp:
		if not op.exists(op.join(hostout, tarball)):
			return -1
		return 1
	if not m.ping(3):
		pprint('ERROR: machine is down')
		return -1
	host = m.sshcmd('hostname', 20).strip()
	if args.host != host:
		pprint('ERROR: wrong host (expected %s, got %s)' % (args.host, host))
		return -1
	check = m.sshcmd('ps aux | grep sleepgraph | grep -v grep', 30).strip()
	if check:
		pprint('ERROR: sleepgraph is currently running')
		return 0
	if dotar:
		pprint('Taring the data to %s' % tarball)
		mask = 'pm-graph-test/suspend-[a-z]*-[0-9]*-[0-9]*-*'
		sshout = m.sshcmd('ls -1dt %s | head -1' % mask, 5).strip()
		if not sshout.startswith('pm-graph-test/suspend'):
			pprint('ERROR: %s' % sshout)
			return -1
		folder = op.basename(sshout)
		out = m.sshcmd('cd pm-graph-test; tar czf /tmp/%s %s' % (tarball, folder), 300)
		pprint(out.strip())
	if doscp:
		pprint('scping the data: %s' % tarball)
		out = m.scpfileget('/tmp/%s' % tarball, hostout)
		if not out:
			pprint('ERROR: SCP FAILED')
		m.sshcmd('rm /tmp/%s' % tarball, 60)
		file = op.join(hostout, tarball)
		if not op.exists(file):
			pprint('ERROR: file failed to download')
			return -1
	pprint('Syncing trace data...')
	m.data_stop_collection(op.join('/tmp', 'serial-data-'+args.host+'.txt'))
	return 1

def pm_graph_multi(args):
	if not (args.user and args.host and args.addr and args.kernel and \
		args.mode) or (not args.count > 0 and not args.duration > 0):
		doError('runmulti is missing arguments (kernel, mode, count or duration')

	# verify host, kernel, and mode
	m = RemoteMachine(args.user, args.host, args.addr,
			args.resetcmd, args.oncmd, args.offcmd,
			args.dstartcmd, args.dstopcmd,
			args.reservecmd, args.releasecmd)
	if not m.ping(3):
		return 0
	check = m.sshcmd('ps aux | grep sleepgraph | grep -v grep', 30).strip()
	if check:
		return 0
	host = m.sshcmd('hostname', 20).strip()
	if args.host != host:
		pprint('ERROR: wrong host (expected %s, got %s)' % (args.host, host))
		return -1
	kver = m.kernel_version()
	if args.kernel != kver:
		pprint('ERROR: wrong kernel (tgt=%s, actual=%s)' % (args.kernel, kver))
		return -1
	out = m.sshcmd('sleepgraph -modes', 20)
	modes = re.sub('[' + re.escape(''.join(',[]\'')) + ']', '', out).split()
	if args.mode not in modes:
		pprint('ERROR: %s does not support mode "%s"' % (host, args.mode))
		pprint('boot clean')
		m.bootclean()
		return -1

	# prepare the system for testing
	pprint('start data collection')
	m.data_start_collection()
	m.sshcmd('sudo ntpdate ntp.ubuntu.com', 60)
	basemode = baseMode(args.mode)
	testfolder = datetime.now().strftime('suspend-'+basemode+'-%y%m%d-%H%M%S')
	if args.count > 0:
		info = '%d' % args.count
		basedir = '%s-x%s' % (testfolder, args.count)
	else:
		info = '%dm' % args.duration
		basedir = '%s-%s' % (testfolder, info)
	sshout = 'pm-graph-test/%s' % basedir
	m.sshcmd('mkdir -p %s' % sshout, 5)
	m.sshcmd('dmesg > %s/dmesg-start.log' % sshout, 5)
	m.sshcmd('sudo hwcheck.py -show all > %s/hwcheck.log' % sshout, 10)
	m.sshcmd('sudo acpidump > %s/acpidump.out' % sshout, 5)
	m.sshcmd('cd %s ; acpixtract acpidump.out' % sshout, 10)
	m.sshcmd('cd %s ; iasl -d *.dat' % sshout, 10)
	pprint('boot setup')
	m.bootsetup()
	m.wifisetup(False)
	rtcwake = '30' if basemode == 'disk' else '15'
	override = '/sys/module/rtc_cmos/parameters/rtc_wake_override_sec'
	out, ro = m.sshcmd('cat %s' % override, 5), rtcwake
	if re.match('^[0-9]+$', out.strip()):
		out = m.sshcmd('echo %s | sudo tee %s' % (ro, override), 5)
		if out.strip() == ro:
			pprint('Setting rtc_wake_override_sec to %s seconds' % ro)
		else:
			pprint('ERROR rtc_wake_override_sec: "%s" (should be %s)' % \
				(out.strip(), ro))
	else:
		pprint('rtc_wake_override_sec not found, using rtcwake')

	cmd = 'sudo sleepgraph -dev -sync -wifi -netfix -display on -gzip '
	cmd += '-rtcwake %s -m %s -multi %s 0 -o %s' % (rtcwake, args.mode, info, sshout)
	mycmd = 'ssh -n -f %s@%s "%s > %s/pm-graph.log 2>&1 &"' % \
		(args.user, args.addr, cmd, sshout)
	call(mycmd, shell=True)
	return 1

def pm_graph(args, m, badmodeok=False):
	if not (args.user and args.host and args.addr and args.kernel and \
		args.mode) or (args.count < 1 and args.duration < 1):
		doError('run is missing arguments (kernel, mode, count or duration', m)

	# testing end conditions
	timecap = args.duration if args.duration > 0 else 43200
	finish = datetime.now() + timedelta(minutes=timecap)
	count = args.count if args.count > 0 else 1000000

	# verify host, kernel, and mode
	if not m.ping(3):
		m.restart_or_die()
	time.sleep(10)
	pprint('Verifying kernel %s is running...' % args.kernel)
	host = m.sshcmd('hostname', 20).strip()
	if args.host != host:
		pprint('ERROR: wrong host (expected %s, got %s)' % (args.host, host))
		m.die()
	kver = m.kernel_version()
	if args.kernel != kver:
		pprint('ERROR: wrong kernel (tgt=%s, actual=%s)' % (args.kernel, kver))
		m.die()
	pprint('Verifying sleepgraph support...')
	out = m.sshcmd('sleepgraph -modes', 20)
	modes = re.sub('[' + re.escape(''.join(',[]\'')) + ']', '', out).split()
	if args.mode not in modes:
		pprint('ERROR: %s does not support mode "%s"' % (host, args.mode))
		if badmodeok:
			return True
		return False
	# initialize path info
	basemode = baseMode(args.mode)
	testfolder = datetime.now().strftime('suspend-'+basemode+'-%y%m%d-%H%M%S')
	if args.count > 0:
		info = '%d' % args.count
	else:
		info = '%dm' % args.duration
	basedir = '%s-%s' % (testfolder, info)
	hostout = op.join(kver, host)
	if args.testout:
		hostout = op.join(args.testout, hostout)
	localout = op.join(hostout, basedir)
	if not op.exists(localout):
		os.makedirs(localout)
	pprint('Output folder: %s' % localout)

	# prepare the system for testing
	pprint('start data collection')
	m.data_start_collection()
	pprint('Preparing %s for testing...' % host)
	sshout = 'pm-graph-test/%s' % basedir
	m.sshcmd('mkdir -p %s' % sshout, 30)
	m.sshcmd('dmesg > %s/dmesg-start.log' % sshout, 5)
	m.sshcmd('sudo hwcheck.py -show all > %s/hwcheck.log' % sshout, 10)
	m.sshcmd('sudo acpidump > %s/acpidump.out' % sshout, 5)
	m.scpfileget('%s/dmesg-start.log' % sshout, localout)
	m.scpfileget('%s/hwcheck.log' % sshout, localout)
	m.scpfileget('%s/acpidump.out' % sshout, localout)
	call('cd %s ; acpixtract acpidump.out' % localout, shell=True)
	call('cd %s ; iasl -d *.dat' % localout, shell=True)
#	out = m.sshcmd('sudo netfix -select wired woloff', 30)
#	pprint(out)

	pprint('boot setup')
	m.bootsetup()
	m.wifisetup(True)
	# kcompactd
	pprint('Forcing kcompactd...')
	m.sshcmd('echo 1 | sudo tee /proc/sys/vm/compact_memory', 10)
	pprint('Done with kcompactd')
	if basemode != 'disk':
		override = '/sys/module/rtc_cmos/parameters/rtc_wake_override_sec'
		out = m.sshcmd('cat %s 2>/dev/null' % override, 30)
		if re.match('^[0-9]+$', out.strip()):
			pprint('rtc_wake_override_sec found, using instead of rtcwake')
		else:
			pprint('rtc_wake_override_sec not found, using rtcwake')
			override = ''
	else:
		override = ''

	# start testing
	pprint('Beginning test: %s' % sshout)
	testfiles = {
		'html'	: '%s/{0}/%s_%s.html' % (localout, host, basemode),
		'dmesg'	: '%s/{0}/%s_%s_dmesg.txt.gz' % (localout, host, basemode),
		'ftrace': '%s/{0}/%s_%s_ftrace.txt.gz' % (localout, host, basemode),
		'result': '%s/{0}/result.txt' % (localout),
		'log'	: '%s/{0}/dmesg.log' % (localout),
	}

	outres = True
	failcount = i = 0
	while datetime.now() < finish and i < count:
		if args.failmax and failcount >= args.failmax:
			pprint('Testing aborted after %d fails' % failcount)
			break
		kver = m.kernel_version()
		testdir = datetime.now().strftime('suspend-%y%m%d-%H%M%S')
		if 'SSH TIMEOUT' in kver or 'reset' in kver or 'Connection' in kver:
			pprint('GET KERNEL FAIL: %s' % kver)
			m.restart_or_die()
			failcount += 1
			continue
		if args.kernel != kver:
			pprint('Testing aborted from wrong kernel (tgt=%s, actual=%s)' % \
				(args.kernel, kver))
			outres = False
			break
		testout = '%s/%s' % (localout, testdir)
		testout_ssh = '%s/%s' % (sshout, testdir)
		if not op.exists(testout):
			os.makedirs(testout)
		rtcwake = '30' if basemode == 'disk' else '15'
		if i < 10:
			cmdfmt = 'mkdir {0}; sudo sleepgraph -dev -sync -wifi -netfix -display on '\
				'-gzip -m {1} -rtcwake {2} -result {0}/result.txt -o {0} -info %s '\
				'-skipkprobe udelay -wifitrace > {0}/test.log 2>&1' % info
		else:
			cmdfmt = 'mkdir {0}; sudo sleepgraph -dev -sync -wifi -netfix -display on '\
				'-gzip -m {1} -rtcwake {2} -result {0}/result.txt -o {0} -info %s '\
				'-skipkprobe udelay > {0}/test.log 2>&1' % info
		cmd = cmdfmt.format(testout_ssh, args.mode, rtcwake)
		pprint(datetime.now())
		pprint('%s %s TEST: %d' % (host, basemode.upper(), i + 1))
		# run sleepgraph over ssh
		if override:
			out = m.sshcmd('echo 15 | sudo tee %s' % override, 30)
			if out.strip() != '15':
				pprint('ERROR on rtc_wake_override_sec: %s' % out)
			out = m.sshcmd('cat %s' % override, 30)
			pprint('rtc_wake_override_sec: %s' % out.strip())
		out = m.sshcmd(cmd, 600, False, False, False)
		with open('%s/sshtest.log' % testout, 'w') as fp:
			fp.write(out)
			fp.close()
		if 'SSH TIMEOUT' in out:
			pprint('SSH TIMEOUT: %s' % testdir)
			m.restart_or_die()
		elif ('Connection refused' in out) or ('closed by remote host' in out) or \
			('No route to host' in out) or ('not responding' in out):
			pprint('ENDED PREMATURELY: %s' % testdir)
			time.sleep(60)
			if not m.ping(5):
				m.restart_or_die()
		elif not m.ping(5):
			pprint('PING FAILED: %s' % testdir)
			m.restart_or_die()
		ap = AsyncProcess('scp -q -r %s@%s:%s %s' % \
			(m.user, m.addr, testout_ssh, localout), 300)
		ap.runcmd()
		if ap.terminated:
			pprint('SCP FAILED')
			m.restart_or_die()
			ap.runcmd()
			if ap.terminated:
				pprint('Testing aborted from SCP FAIL')
				outres = False
				break
		# check to see which files are available
		f = dict()
		found = []
		for t in testfiles:
			f[t] = testfiles[t].format(testdir)
			if os.path.exists(f[t]):
				found.append(t)
		# hang if all files are missing
		if all(v not in found for v in ['html', 'dmesg', 'ftrace', 'result']):
			pprint('HANG: %s' % testdir)
			failcount += 1
			i += 1
			continue
		# if html missing and gz files found, regen the html
		if 'html' not in found and 'dmesg' in found and 'ftrace' in found:
			pprint('REGEN HTML: %s' % testdir)
			cmdbase = 'sleepgraph -dmesg %s -ftrace %s' % (f['dmesg'], f['ftrace'])
			cmd = '%s -dev' % cmdbase
			if 'result' not in found:
				cmd += ' -result %s' % f['result']
			if os.path.getsize(f['ftrace']) > 100000:
				cmd += ' -addlogdmesg'
			else:
				cmd += ' -addlogs'
			ap = AsyncProcess(cmd, 360, False)
			ap.runcmd()
			if ap.terminated:
				if os.path.exists(testfiles['html']):
					os.remove(testfiles['html'])
				pprint('REGEN HTML PLAIN: %s' % testdir)
				ap = AsyncProcess(cmdbase, 360, False)
				ap.runcmd()
		# crash is one or more files is missing
		if any(v not in found for v in ['html', 'dmesg', 'ftrace', 'result']):
			pprint('MISSING OUTPUT FILES: %s' % testdir)
			m.sshcmd('dmesg > %s/dmesg-crash.log' % testout_ssh, 120)
			m.scpfileget('%s/dmesg-crash.log' % testout_ssh, testout)
			pprint('corrupt output!')
			failcount += 1
		else:
			with open('%s/%s/result.txt' % (localout, testdir), 'r') as fp:
				out = fp.read()
				if 'result: pass' in out:
					failcount = 0
				else:
					failcount += 1
				fp.close()
				printlines(out)
		i += 1

	# sync the files
	pprint('Syncing data...')
	m.data_stop_collection(op.join(localout, 'serial-data.txt'))
	ap = AsyncProcess('rsync -ur %s@%s:%s %s' % \
		(m.user, m.addr, sshout, hostout), 1800)
	ap.runcmd()
	if ap.terminated:
		pprint('RSYNC FAILED')
	return outres

def spawnStressTest(args):
	if not (args.user and args.host and args.addr and args.kernel and \
		args.mode) or (not args.count > 0 and not args.duration > 0):
		doError('run is missing arguments (kernel, mode, count or duration')

	cmd = '%s -host %s -user %s -addr %s -kernel %s -mode %s' % \
		(op.abspath(sys.argv[0]), args.host, args.user, args.addr,
		args.kernel, args.mode)
	hostout = op.join(args.kernel, args.host)
	if args.testout:
		cmd += ' -testout %s' % args.testout
		hostout = op.join(args.testout, hostout)
	if args.resetcmd:
		cmd += ' -resetcmd "%s"' % args.resetcmd
	if args.oncmd:
		cmd += ' -oncmd "%s"' % args.oncmd
	if args.offcmd:
		cmd += ' -offcmd "%s"' % args.offcmd
	if args.dstartcmd:
		cmd += ' -dstartcmd "%s"' % args.dstartcmd
	if args.dstopcmd:
		cmd += ' -dstopcmd "%s"' % args.dstopcmd
	if args.reservecmd:
		cmd += ' -reservecmd "%s"' % args.reservecmd
	if args.releasecmd:
		cmd += ' -releasecmd "%s"' % args.releasecmd
	if args.count:
		cmd += ' -count %d' % args.count
	if args.duration:
		cmd += ' -duration %d' % args.duration
	if not op.exists(hostout):
		os.makedirs(hostout)
	call('%s run >> %s/runstress.log 2>&1 &' % (cmd, hostout), shell=True)

def spawnMachineCmds(args, machlist, command):
	cmdfmt, cmds = '', []
	if command == 'tools':
		cmdfmt = '%s' % op.abspath(sys.argv[0])
		if args.ksrc:
			cmdfmt += ' -ksrc %s' % args.ksrc
		if args.proxy:
			cmdfmt += ' -proxy %s' % args.proxy
	elif command == 'install':
		if not (args.pkgout and args.kernel):
			doError('kernel install is missing arguments')
		cmdfmt = '%s -pkgout %s -kernel %s' % \
			(op.abspath(sys.argv[0]), args.pkgout, args.kernel)
		if args.rmkernel:
			cmdfmt += ' -rmkernel "%s"' % args.rmkernel
		if args.ksrc:
			cmdfmt += ' -ksrc %s' % args.ksrc
		if args.proxy:
			cmdfmt += ' -proxy %s' % args.proxy
	elif command == 'uninstall':
		if not args.rmkernel:
			doError('kernel uninstall is missing arguments')
		cmdfmt = '%s -rmkernel "%s"' % \
			(op.abspath(sys.argv[0]), args.rmkernel)
	elif command == 'getmulti':
		if not args.kernel:
			doError('getmulti is missing arguments')
		cmdfmt = '%s -kernel "%s" -testout "%s" -mode "%s"' % \
			(op.abspath(sys.argv[0]), args.kernel, args.testout, args.mode)
	elif command in ['reboot', 'bootsetup', 'bootclean']:
		if not args.kernel:
			doError('kernel install is missing arguments')
		cmdfmt = '%s -kernel %s' % \
			(op.abspath(sys.argv[0]), args.kernel)
	if args.dstartcmd:
		cmdfmt += ' -dstartcmd "%s"' % args.dstartcmd
	if args.dstopcmd:
		cmdfmt += ' -dstopcmd "%s"' % args.dstopcmd
	if args.reservecmd:
		cmdfmt += ' -reservecmd "%s"' % args.reservecmd
	if args.releasecmd:
		cmdfmt += ' -releasecmd "%s"' % args.releasecmd
	cmdsuffix = ' -host {0} -user {1} -addr {2} %s' % command

	for host in machlist:
		m = machlist[host]
		cmds.append(cmdfmt+cmdsuffix.format(m.host, m.user, m.addr))

	pprint('%sing on %d hosts ...' % (command, len(machlist)))
	mp = MultiProcess(cmds, 1800)
	mp.run(16, True)
	for acmd in mp.complete:
		m = re.match('.* -host (?P<h>\S*) .*', acmd.cmd)
		host = m.group('h')
		fp = open('/tmp/%s.log' % host, 'w')
		fp.write(acmd.output)
		fp.close()
		pprint('LOG AT: /tmp/%s.log' % host)
		if host not in machlist:
			continue
		m = machlist[host]
		o = acmd.output
		if acmd.terminated or 'FAILURE' in o or 'ERROR' in o:
			m.status = False
		elif command == 'tools' and \
			('Error' in o or 'fatal' in o or 'TIMEOUT' in o or 'OFFLINE' in o):
			m.status = False
		else:
			if command == 'install':
				m.sshcmd('sudo reboot', 30)
#				m.power_off_machine()
			m.status = True
#	if command == 'install':
#		time.sleep(5)
#		for acmd in mp.complete:
#			m.power_on_machine()

def resetMachineList(args):
	file, kfile = args.machines, ''
	if args.kernel:
		kfile = '%s/machine-%s.txt' % (op.dirname(args.machines), args.kernel)
		if op.exists(kfile):
			file = kfile
			kfile = ''
	fp = open(file, 'r')
	out = []
	for line in fp.read().split('\n'):
		if not line:
			continue
		f = line.split()
		if line.startswith('#') or len(f) != 4:
			out.append(line)
			continue
		out.append(line[len(f[0]):].strip())
	fp.close()
	fp = open(file, 'w')
	for line in out:
		fp.write(line+'\n')
	fp.close()
	if kfile:
		if op.exists(kfile):
			os.remove(kfile)
		shutil.copy(args.machines, kfile)
		pprint('LOG CREATED: %s' % kfile)

def runStressCmd(args, cmd, mlist=None):
	if args.kernel:
		file = '%s/machine-%s.txt' % (op.dirname(args.machines), args.kernel)
		if not op.exists(file):
			shutil.copy(args.machines, file)
			pprint('LOG CREATED: %s' % file)
	else:
		file = args.machines
	changed, machlist, out, fp = False, dict(), [], open(file)

	for line in fp.read().split('\n'):
		out.append(line)
		if line.startswith('#') or not line.strip():
			continue
		f = line.split()
		if len(f) < 3 or len(f) > 4:
			continue
		user, host, addr = f[-1], f[-3], f[-2]
		flag = f[-4] if len(f) == 4 else ''
		machine = RemoteMachine(user, host, addr,
			args.resetcmd, args.oncmd, args.offcmd,
			args.dstartcmd, args.dstopcmd,
			args.reservecmd, args.releasecmd)
		# FIND - get machines by flag(s)
		if cmd.startswith('find:'):
			filter = cmd[5:].split(',')
			if flag not in filter:
				continue
			machlist[host] = machine
		# ONLINE - look at prefix-less machines
		elif cmd == 'online':
			if flag:
				continue
			res = machine.checkhost(args.userinput)
			if res:
				pprint('%30s: %s' % (host, res))
				machlist[host] = machine
				continue
			else:
				pprint('%30s: online' % host)
				if not flag:
					out[-1] = 'O '+line
					changed = True
		# TOOLS - look at O,I,R machines
		elif cmd == 'tools':
			if flag not in ['O', 'I', 'R'] or not mlist:
				continue
			if mlist[host].status:
				pprint('%30s: tools success' % host)
			else:
				pprint('%30s: tools failed' % host)
				continue
		# INSTALL - look at O machines
		elif cmd == 'install':
			if flag != 'O' or not mlist:
				continue
			if mlist[host].status:
				pprint('%30s: install success' % host)
				out[-1] = 'I'+line[1:]
				changed = True
			else:
				pprint('%30s: install failed' % host)
				continue
		# READY - look at I machines
		elif cmd == 'ready':
			if flag != 'O' and flag != 'I':
				continue
			res = machine.checkhost(args.userinput)
			if res:
				pprint('%30s: %s' % (host, res))
				continue
			kver = machine.kernel_version()
			if args.kernel != kver:
				pprint('%30s: wrong kernel (actual=%s)' % (host, kver))
				continue
			pprint('%30s: ready' % host)
			out[-1] = 'R'+line[1:]
			changed = True
		# RUN - look at R machines
		elif cmd == 'run':
			if flag != 'R':
				continue
			args.user, args.host, args.addr = user, host, addr
			if not findProcess(op.basename(sys.argv[0]), ['-host', host]):
				pprint('%30s: STARTING' % host)
				spawnStressTest(args)
			else:
				pprint('%30s: ALREADY RUNNING' % host)
		# RUNNULT - look at R machines
		elif cmd == 'runmulti':
			if flag != 'R':
				continue
			args.user, args.host, args.addr = user, host, addr
			res = pm_graph_multi(args)
			if res == 1:
				pprint('%30s: STARTING' % args.host)
			elif res == 0:
				pprint('%30s: ALREADY RUNNING' % args.host)
			else:
				pprint('%30s: FAILED TO START' % args.host)
		# GETNULT - look at R machines
		elif cmd == 'getmulti':
			if flag != 'R' or not mlist:
				continue
			if mlist[host].status:
				args.user, args.host, args.addr = user, host, addr
				res = pm_graph_multi_download(args, machine, False, False)
				if res == 1:
					pprint('%30s: COMPLETE' % args.host)
				elif res == 0:
					pprint('%30s: SLEEPGRAPH RUNNING' % args.host)
				else:
					pprint('%30s: FAILED TO DOWNLOAD' % args.host)
			else:
				pprint('%30s: FAILED TO TAR' % host)
				continue
		# STATUS - look at R machines
		elif cmd == 'status':
			if flag != 'R':
				continue
			log = '%s/%s/runstress.log' % (args.kernel, host)
			if args.testout:
				log = op.join(args.testout, log)
			print('\n[%s]\n' % host)
			if op.exists(log):
				call('tail -20 %s' % log, shell=True)
		# REBOOT - look at O+ machines
		elif cmd == 'reboot':
			if flag != 'O' and flag != 'I' and flag != 'R':
				continue
			machine.reboot(args.kernel)
		# BOOTSETUP - look at O+ machines
		elif cmd == 'bootsetup':
			if flag != 'O' and flag != 'I' and flag != 'R':
				continue
			print('%s bootsetup' % host)
			machine.bootsetup()
		# BOOTCLEAN - look at O+ machines
		elif cmd == 'bootclean':
			if flag != 'O' and flag != 'I' and flag != 'R':
				continue
			print('%s bootclean' % host)
			machine.bootclean()
	fp.close()
	if changed:
		pprint('LOGGING AT: %s' % file)
		fp = open(file, 'w')
		for line in out[:-1]:
			fp.write(line.strip()+'\n')
		fp.close()
	return machlist

if __name__ == '__main__':

	parser = argparse.ArgumentParser()
	parser.add_argument('-config', metavar='file', default='',
		help='use config file to fill out the remaining args')
	# machine access
	g = parser.add_argument_group('remote machine')
	g.add_argument('-host', metavar='hostname', default='',
		help='hostname of remote machine')
	g.add_argument('-addr', metavar='ip', default='',
		help='ip address or hostname.domain of remote machine')
	g.add_argument('-user', metavar='username', default='',
		help='username to use to ssh to remote machine')
	g = parser.add_argument_group('multiple remote machines')
	g.add_argument('-machines', metavar='file', default='',
		help='input file with remote machine list for running on multiple '+\
		'systems simultaneously (includes host, addr, user on each line)')
	# kernel build
	g = parser.add_argument_group('kernel build (build)')
	g.add_argument('-pkgfmt', metavar='type',
		choices=['deb', 'rpm'], default='',
		help='kernel package format [rpm/deb]')
	g.add_argument('-pkgout', metavar='folder', default='',
		help='output folder for kernel packages (default: ksrc/..)')
	g.add_argument('-ksrc', metavar='folder', default='',
		help='kernel source folder '+\
		'(required to build kernel or install turbostat)')
	g.add_argument('-kname', metavar='string', default='',
		help='kernel name as "<version>-<name>" '+\
		'(default: blank, use version only)')
	g.add_argument('-kcfg', metavar='folder', default='',
		help='config & patches folder '+\
		'(default: use .config in ksrc and apply no patches)')
	g.add_argument('-ktag', metavar='tag', default='',
		help='kernel source git tag to build from or "latestrc" for most '+\
		'recent rc tag in git (default: current HEAD)')
	# machine install
	g = parser.add_argument_group('machine setup (online / install / uninstall)')
	g.add_argument('-userinput', action='store_true',
		help='allow user interaction when executing remote commands')
	g.add_argument('-kernel', metavar='name', default='',
		help='name of the kernel package to install and/or test')
	g.add_argument('-rmkernel', metavar='name(s)', default='',
		help='regex match of kernels to remove')
	g.add_argument('-proxy', metavar='url', default='',
		help='optional proxy to access git repos from remote machine')
	# machine testing
	g = parser.add_argument_group('stress testing (run)')
	g.add_argument('-testout', metavar='folder', default='',
		help='output folder for test data (default: .)')
	g.add_argument('-resetcmd', metavar='cmdstr', default='',
		help='optional command used to reset the remote machine '+\
		'(used on offline/hung machines with "online"/"run")')
	g.add_argument('-oncmd', metavar='cmdstr', default='',
		help='optional command used to power on the remote machine')
	g.add_argument('-offcmd', metavar='cmdstr', default='',
		help='optional command used to power down the remote machine')
	g.add_argument('-reservecmd', metavar='cmdstr', default='',
		help='optional command used to reserve the remote machine '+\
		'(used before "run")')
	g.add_argument('-releasecmd', metavar='cmdstr', default='',
		help='optional command used to release the remote machine '+\
		'(used after "run")')
	g.add_argument('-dstartcmd', metavar='cmdstr', default='',
		help='optional command used to start data tracing on remote machine')
	g.add_argument('-dstopcmd', metavar='cmdstr', default='',
		help='optional command used to download trace data on remote machine')
	g.add_argument('-mode', metavar='suspendmode', default='',
		help='suspend mode to test with sleepgraph on remote machine')
	g.add_argument('-count', metavar='count', type=int, default=0,
		help='maximum sleepgraph iterations to run')
	g.add_argument('-duration', metavar='minutes', type=int, default=0,
		help='maximum duration in minutes to iterate sleepgraph')
	g.add_argument('-failmax', metavar='count', type=int, default=0,
		help='maximum consecutive sleepgraph fails before testing stops')
	# kernel bisect
	g = parser.add_argument_group('kernel bisect (bisect)')
	g.add_argument('-kgood', metavar='tag', default='',
		help='The good kernel commit/tag')
	g.add_argument('-kbad', metavar='tag', default='',
		help='The bad kernel commit/tag')
	g.add_argument('-ktest', metavar='file', default='',
		help='The script which determines pass or fail on target')
	# command
	g = parser.add_argument_group('command')
	g.add_argument('command', choices=['init', 'build', 'turbostat',
		'online', 'install', 'uninstall', 'tools', 'ready', 'run',
		'runmulti', 'getmulti', 'status', 'reboot', 'bootsetup',
		'bootclean', 'bisect'])
	args = parser.parse_args()

	cmd = args.command
	if args.config:
		err = args_from_config(parser, args, args.config, 'setup')
		if err:
			doError(err)

	if args.failmax < 1:
		args.failmax = 20
	arg_to_path(args, ['ksrc', 'kcfg', 'pkgout', 'machines', 'testout'])

	# single machine commands
	if cmd == 'build':
		kernelBuild(args)
		sys.exit(0)
	elif cmd == 'turbostat':
		turbostatBuild(args)
		sys.exit(0)
	elif args.user or args.host or args.addr:
		if not (args.user and args.host and args.addr):
			doError('user, host, and addr are required for single machine commands')
		machine = RemoteMachine(args.user, args.host, args.addr,
			args.resetcmd, args.oncmd, args.offcmd, args.dstartcmd,
			args.dstopcmd, args.reservecmd, args.releasecmd)
		if cmd == 'online':
			res = machine.checkhost(args.userinput)
			if res:
				pprint('%s: %s' % (args.host, res))
			else:
				pprint('%s: online' % args.host)
		elif cmd == 'tools':
			installtools(args, machine)
		elif cmd == 'install':
			if not machine.reserve_machine(30):
				doError('unable to reserve %s' % machine.host)
			kernelInstall(args, machine, True, True)
			machine.release_machine()
		elif cmd == 'uninstall':
			if not machine.reserve_machine(30):
				doError('unable to reserve %s' % machine.host)
			kernelUninstall(args, machine)
			machine.release_machine()
		elif cmd == 'getmulti':
			if not machine.reserve_machine(30):
				doError('unable to reserve %s' % machine.host)
			pm_graph_multi_download(args, machine, True, True)
			machine.release_machine()
		elif cmd == 'ready':
			if not args.kernel:
				doError('%s command requires kernel' % args.command)
			res = machine.checkhost(args.userinput)
			if res:
				pprint('%s: %s' % (args.host, res))
			else:
				kver = machine.kernel_version()
				if args.kernel != kver:
					pprint('%s: wrong kernel (actual=%s)' % (args.host, kver))
				else:
					pprint('%s: ready' % args.host)
		elif cmd == 'run':
			if args.count < 1 and args.duration < 1:
				doError('run requires either count or duration')
			if ':' not in args.mode:
				basemode = baseMode(args.mode)
				if basemode in blacklist and args.host in blacklist[basemode]:
					doError('host %s is blacklisted from running %s' % \
						(args.host, args.mode))
			modelist = []
			d = args.duration if args.duration > 0 else (3 * args.count / 4)
			if ':' in args.mode:
				modelist = args.mode.split(':')
				mult = dt = 0
				for m in modelist:
					if m.startswith('disk'):
						dt += 240 if d > 240 else d
					else:
						mult += 1
				d = (d * mult) + dt + 60
			else:
				modelist.append(args.mode)
				if args.mode.startswith('disk'):
					d = d + 60
			for m in modelist:
				if m not in validmodes:
					doError('invalid mode: %s' % m)
			if not machine.reserve_machine(d):
				doError('unable to reserve %s' % machine.host)
			pprint('boot setup')
			machine.bootsetup()
			for mode in modelist:
				basemode = baseMode(mode)
				if basemode in blacklist and args.host in blacklist[basemode]:
					pprint('WARNING: %s is blacklisted from running %s, skipping...' % \
						(args.host, mode))
					continue
				args.mode = mode
				if basemode == 'disk':
					dur, cnt = args.duration, args.count
					if args.duration > 240:
						args.duration = 240
					if args.count > 120:
						args.count = 120
				if not pm_graph(args, machine, True):
					break
				if basemode == 'disk':
					args.duration, args.count = dur, cnt
				machine.reboot_or_die(args.kernel)
			# testing complete
			pprint('Testing complete')
			pprint('boot clean')
			machine.bootclean()
			machine.release_machine()
		elif cmd == 'bisect':
			if not (args.kgood and args.kbad and args.ksrc and args.kcfg):
				doError('bisect requires -kgood, -kbad, -ksrc, -kcfg')
			kernelBisect(args, machine)
		elif cmd == 'reboot':
			if not args.kernel:
				doError('%s command requires kernel' % args.command)
			machine.reboot(args.kernel)
			print('reboot success')
		elif cmd == 'bootsetup':
			if not args.kernel:
				doError('%s command requires kernel' % args.command)
			machine.bootsetup()
			print('boot setup success')
		elif cmd == 'bootclean':
			if not args.kernel:
				doError('%s command requires kernel' % args.command)
			machine.bootclean()
			print('boot clean success')
		sys.exit(0)

	if not args.machines:
		doError('%s command requires a machine list' % args.command)

	# multiple machine commands
	if cmd == 'init':
		resetMachineList(args)
	elif cmd == 'online':
		machlist = runStressCmd(args, 'online')
		if args.oncmd and args.offcmd and len(machlist) > 0:
			for h in machlist:
				machlist[h].power_off_machine()
			time.sleep(30)
			for h in machlist:
				machlist[h].power_on_machine()
			time.sleep(30)
			machlist = runStressCmd(args, 'online')
		elif args.resetcmd and len(machlist) > 0:
			for h in machlist:
				machlist[h].reset_machine()
			time.sleep(30)
			machlist = runStressCmd(args, 'online')
		if len(machlist) > 0:
			print('Bad Hosts:')
			for h in machlist:
				print(h)
	elif cmd in ['tools', 'install', 'uninstall', 'getmulti',
		'reboot', 'bootsetup', 'bootclean']:
		if cmd == 'install':
			filter = 'find:O'
		elif cmd == 'getmulti':
			filter = 'find:R'
		else:
			filter = 'find:O,I,R'
		machlist = runStressCmd(args, filter)
		spawnMachineCmds(args, machlist, cmd)
		if cmd in ['tools', 'install', 'getmulti']:
			runStressCmd(args, cmd, machlist)
	elif cmd == 'ready':
		if not args.kernel:
			doError('%s command requires kernel' % args.command)
		runStressCmd(args, 'ready')
	elif cmd == 'run':
		if not (args.kernel and args.mode) or (args.count < 1 and args.duration < 1):
			doError('run is missing arguments (kernel, mode, count or duration')
		runStressCmd(args, 'run')
	elif cmd == 'runmulti':
		if not (args.kernel and args.mode) or (args.count < 1 and args.duration < 1):
			doError('run is missing arguments (kernel, mode, count or duration')
		runStressCmd(args, 'runmulti')
	elif cmd == 'status':
		if not args.kernel:
			doError('%s command requires kernel' % args.command)
		runStressCmd(args, 'status')
