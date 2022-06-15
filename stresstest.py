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
from tempfile import mkdtemp
import argparse
import os.path as op
from lib.parallel import AsyncProcess, MultiProcess, findProcess
from lib.argconfig import args_from_config, arg_to_path
from lib.remotemachine import RemoteMachine

mystarttime = time.time()
def pprint(msg, withtime=True):
	if withtime:
		print('[%05d] %s' % (time.time()-mystarttime, msg))
	else:
		print(msg)
	sys.stdout.flush()

def printlines(out):
	if not out.strip():
		return
	for line in out.split('\n'):
		if line.strip():
			pprint(line.strip())

def ascii(text):
	return text.decode('ascii', 'ignore')

def doError(msg, machine=None):
	if machine:
		machine.release_machine()
	pprint('ERROR: %s\n' % msg)
	sys.exit(1)

def runcmd(cmd, output=False, fatal=True):
	out = []
	p = Popen(cmd.split(), stderr=PIPE, stdout=PIPE)
	for line in p.stdout:
		line = ascii(line).strip()
		if output:
			pprint(line)
		out.append(line)
	if fatal and p.poll():
		doError(cmd)
	return out

def kernelmatch(kmatch, pkgfmt, pkgname):
	# verify this is a kernel package and pull out the version
	if pkgname.startswith('linux-headers-'):
		kver = pkgname[14:]
	elif pkgname.startswith('linux-image-'):
		if pkgname.endswith('-dbg'):
			kver = pkgname[12:-4]
		else:
			kver = pkgname[12:]
	else:
		return False
	if kmatch == pkgname or kmatch == kver or re.match(kmatch, kver):
		return True
	return False

def turbostatBuild(args):
	if not args.ksrc:
		return;
	isgit = op.exists(op.join(args.ksrc, '.git/config'))
	if isgit:
		runcmd('git -C %s checkout .' % args.ksrc, True)
		runcmd('git -C %s checkout master' % args.ksrc, True)
		runcmd('git -C %s pull' % args.ksrc, True)
	tdir = op.join(args.ksrc, 'tools/power/x86/turbostat')
	if op.isdir(tdir):
		call('make -C %s clean' % tdir, shell=True)
		call('make -C %s turbostat' % tdir, shell=True)
		call('%s/turbostat -v' % tdir, shell=True)

def kernelBuild(args):
	if not args.pkgfmt:
		doError('kernel build is missing arguments')
	cloned = False
	if not args.ksrc:
		repo = 'http://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git'
		args.ksrc = mkdtemp(prefix='linux')
		pprint('Cloning new kernel source tree ...')
		call('git clone %s %s' % (repo, args.ksrc), shell=True)
		cloned = True
	# set the repo to the right tag
	isgit = op.exists(op.join(args.ksrc, '.git/config'))
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
	kconfig = ''
	if args.kcfg:
		if not op.exists(args.kcfg) or not op.isdir(args.kcfg):
			doError('%s is not an existing folder' % args.kcfg)
		patches = []
		for file in sorted(os.listdir(args.kcfg)):
			if file.endswith('.patch'):
				patches.append(op.join(args.kcfg, file))
			elif file.endswith('.config'):
				kconfig = op.join(args.kcfg, file)
		if len(patches) > 0:
			if isgit:
				runcmd('git -C %s checkout .' % args.ksrc, True)
			for patch in sorted(patches):
				runcmd('patch -d %s -i %s -p1' % (args.ksrc, patch), True)
	if not kconfig:
		doError('Missing kernel config file')

	# build the kernel
	runcmd('cp %s %s' % (kconfig, op.join(args.ksrc, '.config')), True)
	try:
		numcpu = int(runcmd('getconf _NPROCESSORS_ONLN', False, False)[0])
	except:
		numcpu = 1
	runcmd('make -C %s distclean' % args.ksrc, True)
	runcmd('cp %s %s' % (kconfig, op.join(args.ksrc, '.config')), True)
	runcmd('make -C %s olddefconfig' % args.ksrc, True)
	kver = runcmd('make -s -C %s kernelrelease' % args.ksrc)[0]
	if args.kname:
		runcmd('make -C %s -j %d %s-pkg LOCALVERSION=-%s' % \
			(args.ksrc, numcpu, args.pkgfmt, args.kname), True)
	else:
		runcmd('make -C %s -j %d %s-pkg' % \
			(args.ksrc, numcpu, args.pkgfmt), True)

	# build turbostat
	tdir = op.join(args.ksrc, 'tools/power/x86/turbostat')
	if op.isdir(tdir):
		call('make -C %s clean' % tdir, shell=True)
		call('make -C %s turbostat' % tdir, shell=True)

	# find the output files
	miscfiles, packages, out = [], [], []
	outdir = os.path.realpath(os.path.join(args.ksrc, '..'))
	for file in os.listdir(outdir):
		if kver not in file:
			continue
		created = os.path.getctime(op.join(outdir, file))
		if created < mystarttime:
			continue
		if file.endswith(args.pkgfmt):
			packages.append(file)
		else:
			miscfiles.append(file)
	for file in miscfiles:
		os.remove(os.path.join(outdir, file))
	if cloned:
		shutil.rmtree(args.ksrc)
		args.ksrc = ''

	# move the output files to the output folder
	if args.pkgout:
		if not op.exists(args.pkgout):
			os.makedirs(args.pkgout)
		if outdir != os.path.realpath(args.pkgout):
			for file in packages:
				tgt = os.path.join(args.pkgout, file)
				if op.exists(tgt):
					pprint('Overwriting %s' % file)
					os.remove(tgt)
				shutil.move(os.path.join(outdir, file), args.pkgout)
			outdir = args.pkgout
	else:
		args.pkgout = outdir

	pprint('DONE')
	print('Kernel is %s\nPackages in %s' % (kver, outdir))
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

def kernelInstall(args, m):
	if not (args.pkgfmt and args.pkgout and args.user and \
		args.host and args.addr and args.kernel):
		doError('kernel install is missing arguments', m)

	# get the kernel packages for our version
	packages = []
	for file in sorted(os.listdir(args.pkgout)):
		if not file.startswith('linux-') or not file.endswith('.deb'):
			continue
		if args.kernel in file:
			packages.append(file)
	if len(packages) < 1:
		doError('no kernel packages found for "%s"' % args.kernel, m)

	# connect to the right machine
	pprint('check host is online and the correct one')
	res = m.checkhost(args.userinput)
	if res:
		doError('%s: %s' % (m.host, res), m)
	pprint('os check')
	res = m.oscheck()
	if args.pkgfmt == 'deb' and res != 'ubuntu':
		doError('%s: needs ubuntu to use deb packages' % m.host, m)
	elif args.pkgfmt == 'rpm' and res != 'fedora':
		doError('%s: needs fedora to use rpm packages' % m.host, m)

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
	pprint('configure grub')
	out = m.configure_grub()
	printlines(out)

	# remove unneeeded space
	pprint('remove previous test data')
	printlines(m.sshcmd('rm -r pm-graph-test ; mkdir pm-graph-test', 10))
	if args.rmkernel:
		pprint('remove old kernels')
		kernelUninstall(args, m)

	# install tools
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

	# install the kernel
	pprint('checking kernel versions')
	if not m.list_kernels(True):
		doError('%s: could not list installed kernel versions' % m.host, m)
	pprint('uploading kernel packages')
	pkglist = ''
	for pkg in packages:
		rp = op.join('/tmp', pkg)
		if not pkglist:
			pkglist = rp
		else:
			pkglist += ' %s' % rp
		m.scpfile(op.join(args.pkgout, pkg), '/tmp')
	pprint('installing the kernel')
	out = m.sshcmd('sudo dpkg -i %s' % pkglist, 600)
	printlines(out)
	idx = m.kernel_index(args.kernel)
	if idx < 0:
		doError('%s: %s failed to install' % (m.host, args.kernel), m)
	pprint('kernel install completed')
	out = m.sshcmd('sudo grub-set-default \'1>%d\'' % idx, 30)
	printlines(out)

	# system status
	pprint('sleepgraph modes')
	printlines(m.sshcmd('sleepgraph -modes', 10))
	pprint('disk space available')
	printlines(m.sshcmd('df /', 10))

def kernelUninstall(args, m):
	if not (args.pkgfmt and args.user and args.host and \
		args.addr and args.rmkernel):
		doError('kernel uninstall is missing arguments', m)
	try:
		re.match(args.rmkernel, '')
	except:
		doError('kernel regex caused an exception: "%s"' % args.rmkernel, m)
	packages = []
	res = m.sshcmd('dpkg -l', 30)
	for line in res.split('\n'):
		v = line.split()
		if len(v) > 2 and kernelmatch(args.rmkernel, args.pkgfmt, v[1]):
			packages.append(v[1])
	for p in packages:
		pprint('removing %s ...' % p)
		out = m.sshcmd('sudo dpkg --purge %s' % p, 600)
		printlines(out)

def pm_graph_multi_download(args, m, dotar=False, doscp=False):
	if not (args.user and args.host and args.addr and args.kernel):
		doError('getmulti is missing arguments (kernel)')
	if not m.ping(3):
		return -1
	check = m.sshcmd('ps aux | grep sleepgraph | grep -v grep', 30).strip()
	if check:
		return 0
	host = m.sshcmd('hostname', 20).strip()
	if args.host != host:
		pprint('ERROR: wrong host (expected %s, got %s)' % (args.host, host))
		return -1
	tarball = '%s-%s.tar.gz' % (args.host, args.kernel)
	if dotar:
		mask = 'pm-graph-test/suspend-[a-z]*-[0-9]*-[0-9]*-*'
		sshout = m.sshcmd('ls -1d %s | head -1' % mask, 5).strip()
		if not sshout.startswith('pm-graph-test/suspend'):
			pprint('ERROR: %s' % sshout)
			return -1
		folder = op.basename(sshout)
		m.sshcmd('cd pm-graph-test; tar czf /tmp/%s %s' % (tarball, folder), 300)
	if doscp:
		hostout = args.testout if args.testout else '/tmp'
		m.scpfileget('/tmp/%s' % tarball, hostout)
		m.sshcmd('rm /tmp/%s' % tarball, 60)
		if not op.exists(op.join(hostout, tarball)):
			return -1
	return 1

def pm_graph_multi(args):
	if not (args.user and args.host and args.addr and args.kernel and \
		args.mode) or (not args.count > 0 and not args.duration > 0):
		doError('runmulti is missing arguments (kernel, mode, count or duration')

	# verify host, kernel, and mode
	m = RemoteMachine(args.user, args.host, args.addr)
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
		return -1

	# prepare the system for testing
	basemode = 'freeze' if 's2idle' in args.mode else args.mode.split('-')[0]
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
	m.sshcmd('sudo acpidump > %s/acpidump.out' % sshout, 5)
	m.sshcmd('cd %s ; acpixtract acpidump.out' % sshout, 10)
	m.sshcmd('cd %s ; iasl -d *.dat' % sshout, 10)
	m.bootsetup()
	m.wifisetup(True)
	override = '/sys/module/rtc_cmos/parameters/rtc_wake_override_sec'
	out = m.sshcmd('cat %s' % override, 5)
	if re.match('[0-9\.]*', out.strip()):
		out = m.sshcmd('echo 2 | sudo tee %s' % override, 5)
		if out.strip() != '2':
			pprint('ERROR on rtc_wake_override_sec: %s' % out)
	cmd = 'sudo sleepgraph -dev -sync -wifi -netfix -display on -gzip -rtcwake 15 '
	cmd += '-m %s -multi %s 0 -o %s' % (basemode, info, sshout)
	mycmd = 'ssh -n -f %s@%s "%s > %s/pm-graph.log 2>&1 &"' % \
		(args.user, args.addr, cmd, sshout)
	call(mycmd, shell=True)
	return 1

def pm_graph(args, m):
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
		return False
	# initialize path info
	basemode = 'freeze' if 's2idle' in args.mode else args.mode.split('-')[0]
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
	pprint('Preparing %s for testing...' % host)
	sshout = 'pm-graph-test/%s' % basedir
	m.sshcmd('mkdir -p %s' % sshout, 5)
	with open('%s/dmesg-start.log' % localout, 'w') as fp:
		fp.write(m.sshcmd('dmesg', 120))
		fp.close()
	with open('%s/acpidump.out' % localout, 'w') as fp:
		fp.write(m.sshcmd('sudo acpidump', 120))
		fp.close()
	m.bootsetup()
	m.wifisetup(True)
	override = '/sys/module/rtc_cmos/parameters/rtc_wake_override_sec'
	out = m.sshcmd('cat %s' % override, 5)
	if re.match('[0-9\.]*', out.strip()):
		pprint('rtc_wake_override_sec found, using instead of rtcwake')
	else:
		pprint('rtc_wake_override_sec not found, using rtcwake')
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
		if args.kernel != kver:
			pprint('Testing aborted from wrong kernel (tgt=%s, actual=%s)' % \
				(args.kernel, kver))
			outres = False
			break
		testdir = datetime.now().strftime('suspend-%y%m%d-%H%M%S')
		testout = '%s/%s' % (localout, testdir)
		testout_ssh = '%s/%s' % (sshout, testdir)
		if not op.exists(testout):
			os.makedirs(testout)
		rtcwake = '90' if basemode == 'disk' else '15'
		cmdfmt = 'mkdir {0}; sudo sleepgraph -dev -sync -wifi -netfix -display on '\
			'-gzip -m {1} -rtcwake {2} -result {0}/result.txt -o {0} -info %s '\
			'-skipkprobe udelay > {0}/test.log 2>&1' % info
		cmd = cmdfmt.format(testout_ssh, args.mode, rtcwake)
		pprint(datetime.now())
		pprint('%s %s TEST: %d' % (host, basemode.upper(), i + 1))
		# run sleepgraph over ssh
		if override:
			out = m.sshcmd('echo 2 | sudo tee %s' % override, 5)
			if out.strip() != '2':
				pprint('ERROR on rtc_wake_override_sec: %s' % out)
			out = m.sshcmd('cat %s' % override, 5)
			pprint('rtc_wake_override_sec: %s' % out.strip())
		out = m.sshcmd(cmd, 360, False, False, False)
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

	# sync the files just to be sure nothing is missing
	pprint('Syncing data...')
	ap = AsyncProcess('rsync -ur %s@%s:%s %s' % \
		(m.user, m.addr, sshout, hostout), 1800)
	ap.runcmd()
	if ap.terminated:
		pprint('RSYNC FAILED')
	# testing complete
	pprint('Testing complete, resetting grub...')
	m.grub_reset()
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
		if not (args.pkgfmt and args.pkgout and args.kernel):
			doError('kernel install is missing arguments')
		cmdfmt = '%s -pkgout %s -pkgfmt %s -kernel %s' % \
			(op.abspath(sys.argv[0]), args.pkgout, args.pkgfmt, args.kernel)
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
		cmdfmt = '%s -kernel "%s"' % \
			(op.abspath(sys.argv[0]), args.kernel)
	if args.reservecmd:
		cmdfmt += ' -reservecmd "%s"' % args.reservecmd
	if args.releasecmd:
		cmdfmt += ' -releasecmd "%s"' % args.releasecmd
	cmdsuffix = ' -user {0} -host {1} -addr {2} %s' % command

	for host in machlist:
		m = machlist[host]
		cmds.append(cmdfmt+cmdsuffix.format(m.user, m.host, m.addr))

	pprint('%sing on %d hosts ...' % (command, len(machlist)))
	mp = MultiProcess(cmds, 1800)
	mp.run(8, True)
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
			('Error' in o or 'fatal' in o or 'TIMEOUT' in o):
			m.status = False
		else:
			if command == 'install':
				m.sshcmd('sudo reboot', 30)
			m.status = True

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
			args.resetcmd, args.reservecmd, args.releasecmd)
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
				res = pm_graph_multi_download(args, machine, False, True)
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
		choices=['deb', 'rpm'], default='deb',
		help='kernel package format [rpm/deb] (default: deb)')
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
	g.add_argument('-reservecmd', metavar='cmdstr', default='',
		help='optional command used to reserve the remote machine '+\
		'(used before "run")')
	g.add_argument('-releasecmd', metavar='cmdstr', default='',
		help='optional command used to release the remote machine '+\
		'(used after "run")')
	g.add_argument('-mode', metavar='suspendmode', default='',
		help='suspend mode to test with sleepgraph on remote machine')
	g.add_argument('-count', metavar='count', type=int, default=0,
		help='maximum sleepgraph iterations to run')
	g.add_argument('-duration', metavar='minutes', type=int, default=0,
		help='maximum duration in minutes to iterate sleepgraph')
	g.add_argument('-failmax', metavar='count', type=int, default=100,
		help='maximum consecutive sleepgraph fails before testing stops')
	# command
	g = parser.add_argument_group('command')
	g.add_argument('command', choices=['build', 'turbostat', 'online',
		'install', 'uninstall', 'tools', 'ready', 'run', 'runmulti',
		'getmulti', 'status', 'reboot'])
	args = parser.parse_args()

	cmd = args.command
	if args.config:
		err = args_from_config(parser, args, args.config, 'setup')
		if err:
			doError(err)

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
			args.resetcmd, args.reservecmd, args.releasecmd)
		if cmd == 'online':
			res = machine.checkhost(args.userinput)
			if res:
				pprint('%s: %s' % (args.host, res))
			else:
				pprint('%s: online' % args.host)
		elif cmd == 'tools':
			if not machine.reserve_machine(30):
				doError('unable to reserve %s' % machine.host)
			installtools(args, machine)
			machine.release_machine()
		elif cmd == 'install':
			if not machine.reserve_machine(30):
				doError('unable to reserve %s' % machine.host)
			kernelInstall(args, machine)
			machine.release_machine()
		elif cmd == 'uninstall':
			if not machine.reserve_machine(30):
				doError('unable to reserve %s' % machine.host)
			kernelUninstall(args, machine)
			machine.release_machine()
		elif cmd == 'getmulti':
			if not machine.reserve_machine(30):
				doError('unable to reserve %s' % machine.host)
			pm_graph_multi_download(args, machine, True, False)
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
			d = args.duration if args.duration > 0 else (3 * args.count / 4)
			if args.mode == 'all':
				d = (d * 2) + 10
			if not machine.reserve_machine(d):
				doError('unable to reserve %s' % machine.host)
			if args.mode == 'all':
				args.mode = 'freeze'
				if pm_graph(args, machine):
					machine.reboot_or_die(args.kernel)
					args.mode = 'mem'
					pm_graph(args, machine)
			else:
				pm_graph(args, machine)
			machine.release_machine()
		sys.exit(0)

	if not args.machines:
		doError('%s command requires a machine list' % args.command)

	# multiple machine commands
	if cmd == 'online':
		machlist = runStressCmd(args, 'online')
		if args.resetcmd:
			for h in machlist:
				machlist[h].reset_machine()
			time.sleep(30)
			machlist = runStressCmd(args, 'online')
		if len(machlist) > 0:
			print('Bad Hosts:')
			for h in machlist:
				print(h)
	elif cmd in ['tools', 'install', 'uninstall', 'getmulti']:
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
	elif cmd == 'reboot':
		if not args.kernel:
			doError('%s command requires kernel' % args.command)
		runStressCmd(args, 'reboot')
