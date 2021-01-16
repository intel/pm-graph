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
from datetime import datetime
import argparse
import os.path as op
from lib.parallel import MultiProcess
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

def doError(msg, args=None):
	if args:
		args.print_help()
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
		doError(cmd, False)
	return out

def resetmachine(args, m):
	if not args.resetcmd:
		return
	values = {'host': m.host, 'addr': m.addr, 'user': m.user}
	cmd = args.resetcmd.format(**values)
	pprint(cmd)
	call(cmd, shell=True)

def reservemachine(args, m, c):
	if not args.reservecmd:
		return
	values = {'host': m.host, 'addr': m.addr, 'user': m.user, 'minutes': c}
	cmd = args.reservecmd.format(**values)
	pprint(cmd)
	call(cmd, shell=True)

def releasemachine(args, m):
	if not args.releasecmd:
		return
	values = {'host': m.host, 'addr': m.addr, 'user': m.user}
	cmd = args.releasecmd.format(**values)
	pprint(cmd)
	call(cmd, shell=True)

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

def kernelBuild(args):
	if not (args.pkgfmt and args.ksrc):
		doError('kernel build is missing arguments', False)
	if not op.exists(args.ksrc) or not op.isdir(args.ksrc):
		doError('ksrc "%s" is not an existing folder' % args.ksrc, False)

	# set the repo to the right tag
	isgit = op.exists(op.join(args.ksrc, '.git/config'))
	if args.ktag:
		if not isgit:
			doError('%s is not a git folder, tag can\'t be set' % args.ksrc, False)
		runcmd('git -C %s checkout .' % args.ksrc, True)
		if args.ktag == 'latestrc':
			runcmd('git -C %s checkout master' % args.ksrc, True)
			runcmd('git -C %s pull' % args.ksrc, True)
			args.ktag = runcmd('git -C %s describe --abbrev=0 --tags' % args.ksrc)[0]
			pprint('Latest RC is %s' % args.ktag)
		elif args.ktag != 'master':
			tags = runcmd('git -C %s tag' % args.ksrc)
			if args.ktag not in tags:
				doError('%s is not a valid tag' % args.ktag, False)
		runcmd('git -C %s checkout %s' % (args.ksrc, args.ktag), True)

	# apply kernel patches
	kconfig = ''
	if args.kcfg:
		if not op.exists(args.kcfg) or not op.isdir(args.kcfg):
			doError('%s is not an existing folder' % args.kcfg, False)
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
	kver = runcmd('make -s -C %s kernelrelease' % args.ksrc)[0]
	try:
		numcpu = int(runcmd('getconf _NPROCESSORS_ONLN', False, False)[0])
	except:
		numcpu = 1
	runcmd('make -C %s distclean' % args.ksrc, True)
	runcmd('cp %s %s' % (kconfig, op.join(args.ksrc, '.config')), True)
	runcmd('make -C %s olddefconfig' % args.ksrc, True)
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

	# move the output files to the output folder
	if args.pkgout:
		if not op.exists(args.pkgout):
			os.mkdir(args.pkgout)
		if outdir != os.path.realpath(args.pkgout):
			for file in miscfiles + packages:
				shutil.move(os.path.join(outdir, file), args.pkgout)
			outdir = args.pkgout
	else:
		args.pkgout = outdir

	pprint('Packages in %s' % outdir)
	for file in sorted(packages):
		out.append(op.join(outdir, file))
		pprint('   %s' % file)
	pprint('Other output files in %s' % outdir)
	for file in sorted(miscfiles):
		pprint('   %s' % file)

	return out

def kernelInstall(args, m):
	if not (args.pkgfmt and args.pkgout and args.user and \
		args.host and args.addr and args.kernel):
		doError('kernel install is missing arguments', False)

	# get the kernel packages for our version
	packages = []
	for file in sorted(os.listdir(args.pkgout)):
		if not file.startswith('linux-') or not file.endswith('.deb'):
			continue
		if args.kernel in file:
			packages.append(file)
	if len(packages) < 1:
		doError('no kernel packages found for "%s"' % args.kernel)

	# connect to the right machine
	pprint('check host is online and the correct one')
	res = m.checkhost(args.userinput)
	if res:
		doError('%s: %s' % (m.host, res))
	pprint('os check')
	res = m.oscheck()
	if args.pkgfmt == 'deb' and res != 'ubuntu':
		doError('%s: needs ubuntu to use deb packages' % m.host)
	elif args.pkgfmt == 'rpm' and res != 'fedora':
		doError('%s: needs fedora to use rpm packages' % m.host)

	# configure the system
	pprint('boot setup')
	m.bootsetup()
	pprint('wifi setup')
	out = m.wifisetup(True)
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
		doError('%s: sleepgraph installed with "submit" branch' % m.host)
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
		doError('%s: could not list installed kernel versions' % m.host)
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
		doError('%s: %s failed to install' % (m.host, args.kernel))
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
		doError('kernel uninstall is missing arguments', False)
	try:
		re.match(args.rmkernel, '')
	except:
		doError('kernel regex caused an exception: "%s"' % args.rmkernel, False)
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

def pm_graph(m, args):
	doError('run not yet supported')
	#kernel, mode, count, failmax=100):
	user = m.user if 'USER' not in os.environ else os.environ['USER']
	kernel, mode, count, duration = args.kernel, args.mode, args.count, args.duration
	finish = datetime.now() + timedelta(minutes=count)
	# check if machine is already reserved
	ruser = otcpldb.is_machine_reserved(m.name)
	if ruser and user != ruser:
		pprint('ERROR: machine is currently reserved by %s' % ruser)
		return 1

	# reserve the system
	pprint('Reserving the machine...')
	m.reserve(user, count+5)

	# bring the system online
	pprint('Attaching to ilab...')
	ilab = None
	if not m.ping(3):
		m.restart_or_die(ilab)

	# initialize path info
	basemode = mode.split('-')[0]
	kver = kernel
	basedir = '%s-%dmin' % (datetime.now().strftime('suspend-'+basemode+'-%y%m%d-%H%M%S'), count)
	localout = 'pm-graph-test/%s/%s/%s' % (kver, m.name, basedir)
	urlprefix = 'http://wopr.jf.intel.com/static/html/%s' % localout
	call('mkdir -p %s' % localout, shell=True)
	if not kver:
		pprint('Kernel install failed, aborting test run...')
		return 1

	# verify the requested mode is supported and is running the right kernel
	pprint('Verifying kernel %s is running...' % kver)
	host = m.sshcmd('hostname', 20).strip()
	check_kernel_version(m, kver)
	check_sleepgraph(m, False, True)
	pprint('Verifying pm-graph support...')
#	m.sshcmd('cd /tmp ; rm -rf pm-graph ; http_proxy=http://proxy.jf.intel.com:911 git clone -b master http://github.com/intel/pm-graph.git ; cd pm-graph ; sudo make install', 180)
	out = m.sshcmd('sleepgraph -modes', 20)
	modes = re.sub('[' + re.escape(''.join(',[]\'')) + ']', '', out).split()
	if mode not in modes:
		pprint('ERROR: %s does not support mode "%s"' % (m.name, mode))
		m.release(user)
		return 1

	# prepare the system for testing
	pprint('Preparing %s for testing...' % host)
	sshout = 'pm-graph-test/%s' % basedir
	m.sshcmd('mkdir -p %s' % sshout, 5)
	with open('%s/dmesg-start.log' % localout, 'w') as fp:
		fp.write(m.sshcmd('dmesg', 120))
		fp.close()
	m.bootsetup()

	# start testing
	pprint('Beginning test\nOUTPUT: %s' % sshout)
	testfiles = {
		'html'	: '%s/{0}/%s_%s.html' % (localout, host, basemode),
		'dmesg'	: '%s/{0}/%s_%s_dmesg.txt.gz' % (localout, host, basemode),
		'ftrace': '%s/{0}/%s_%s_ftrace.txt.gz' % (localout, host, basemode),
		'result': '%s/{0}/result.txt' % (localout),
		'log'	: '%s/{0}/dmesg.log' % (localout),
	}
	failcount = i = 0
	while datetime.now() < finish:
		if failcount >= failmax:
			pprint('Testing aborted after %d fails' % failcount)
			break
		out = check_kernel_version(m, kver)
		if out == 'retry':
			continue
		check_sleepgraph(m)
		testdir = datetime.now().strftime('suspend-%y%m%d-%H%M%S')
		testout = '%s/%s' % (localout, testdir)
		testout_ssh = '%s/%s' % (sshout, testdir)
		call('mkdir -p %s' % testout, shell=True)
		rtcwake = '90' if basemode == 'disk' else '15'
		cmdfmt = 'mkdir {0}; sudo sleepgraph -dev -sync -wifi -display on '\
			'-gzip -m {1} -rtcwake {2} -result {0}/result.txt -o {0} -info %dm '\
			'-skipkprobe udelay > {0}/test.log 2>&1' % count
		cmd = cmdfmt.format(testout_ssh, mode, rtcwake)
		ap = m.sshproc(cmd, 360)
		pprint(datetime.now())
		pprint('%s %s TEST: %d' % (host, mode.upper(), i + 1))
		# run sleepgraph over ssh
		out = ap.runcmd()
		with open('%s/sshtest.log' % testout, 'w') as fp:
			fp.write(out)
			fp.close()
		if ap.terminated:
			pprint('SSH TIMEOUT: %s' % testdir)
			m.restart_or_die(ilab, testout)
		elif ': Connection refused' in out or ' closed by remote host.' in out or 'No route to host' in out or not m.ping(5):
			pprint('ENDED PREMATURELY: %s' % testdir)
			time.sleep(60)
		if not m.ping(5):
			pprint('PING FAILED: %s' % testdir)
			ap.terminated = True
			m.restart_or_die(ilab, testout)
		ap = AsyncProcess('scp -q -r labuser@%s:%s %s' % (m.ip, testout_ssh, localout), 300, False)
		ap.runcmd()
		if ap.terminated:
			pprint('SCP FAILED')
			m.restart_or_die(ilab, testout)
			ap.runcmd()
			if ap.terminated:
				i += 1
				continue
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
			if not ap.terminated:
				with open('%s/dmesg-crash.log' % testout, 'w') as fp:
					fp.write(m.sshcmd('dmesg', 120))
					fp.close()
			failcount += 1
		else:
			with open('%s/%s/result.txt' % (localout, testdir), 'r') as fp:
				out = fp.read()
				pprint(out.strip())
				if 'result: pass' in out:
					failcount = 0
				else:
					failcount += 1
				fp.close()
		i += 1

	# sync the files just to be sure nothing is missing
	pprint('Syncing data...')
	call('rsync -ur labuser@%s:%s pm-graph-test/%s/%s' % (m.ip, sshout, kver, m.name), shell=True)
	# testing complete
	pprint('Testing complete, resetting grub...')
	m.grub_reset()
	pprint('Generating a report')
	cmd = './stressreport.py -urlprefix %s -create test -bugzilla -htmlonly %s' % (urlprefix, localout)
	pprint(cmd)
	call(cmd, shell=True)
	return 0

def spawnMachineCmds(args, machlist, command):
	cmdfmt, cmds = '', []
	if command == 'install':
		if not (args.pkgfmt and args.pkgout and args.kernel):
			doError('kernel install is missing arguments', False)
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
			doError('kernel uninstall is missing arguments', False)
		cmdfmt = '%s -rmkernel "%s"' % \
			(op.abspath(sys.argv[0]), args.rmkernel)
	cmdfmt += ' -user {0} -host {1} -addr {2} %s' % command

	for host in machlist:
		m = machlist[host]
		cmds.append(cmdfmt.format(m.user, m.host, m.addr))

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
		if acmd.terminated or 'FAILURE' in acmd.output or 'ERROR' in acmd.output:
			m.status = False
		else:
			if command == 'install':
				m.sshcmd('sudo reboot', 30)
			m.status = True

def runStressCmd(args, cmd, mlist=None):
	if not args.kernel:
		doError('kernel is required for logging purposes', False)

	file = '%s/machine-%s.txt' % (op.dirname(args.machines), args.kernel)
	if not op.exists(file):
		shutil.copy(args.machines, file)
		pprint('LOG CREATED: %s' % file)
	out, fp = [], open(file)
	changed, machlist = False, dict()

	for line in fp.read().split('\n'):
		if line.startswith('#') or not line.strip():
			out.append(line)
			continue
		f = line.split()
		if len(f) < 3 or len(f) > 4:
			out.append(line)
			continue
		user, host, addr = f[-1], f[-3], f[-2]
		flag = f[-4] if len(f) == 4 else ''
		machine = RemoteMachine(user, host, addr)
		# FIND - get machines by flag(s)
		if cmd.startswith('find:'):
			filter = cmd[5:].split(',')
			if flag not in filter:
				out.append(line)
				continue
			machlist[host] = machine
		# ONLINE - look at prefix-less machines
		elif cmd == 'online':
			if flag:
				out.append(line)
				continue
			res = machine.checkhost(args.userinput)
			if res:
				pprint('%30s: %s' % (host, res))
				machlist[host] = machine
				out.append(line)
				continue
			else:
				pprint('%30s: online' % host)
				line = 'O '+line
				changed = True
		# INSTALL - look at O machines
		elif cmd == 'install':
			if flag != 'O' or not mlist:
				out.append(line)
				continue
			if mlist[host].status:
				pprint('%30s: install success' % host)
				line = 'I'+line[1:]
				changed = True
			else:
				pprint('%30s: install failed' % host)
				out.append(line)
				continue
		# READY - look at I machines
		elif cmd == 'ready':
			if flag != 'I':
				out.append(line)
				continue
			res = machine.checkhost(args.userinput)
			if res:
				pprint('%30s: %s' % (host, res))
				out.append(line)
				continue
			kver = machine.kernel_version()
			if args.kernel != kver:
				pprint('%30s: wrong kernel (actual=%s)' % (host, kver))
				out.append(line)
				continue
			pprint('%30s: ready' % host)
			line = 'R'+line[1:]
			changed = True
		# RUN - look at R machines
		elif cmd == 'run':
			if flag != 'R':
				out.append(line)
				continue
			logdir = 'pm-graph-test/%s/%s' % (kernel, host)
			call('mkdir -p %s' % logdir, shell=True)
			if not findProcess('runstress', [host]):
				pprint('%30s: STARTING' % host)
				call('runstress %s 1440 %s >> %s/runstress.log 2>&1 &' % \
					(kernel, host, logdir), shell=True)
			else:
				pprint('%30s: ALREADY RUNNING' % host)
		# STATUS - look at R machines
		elif cmd == 'status':
			if flag != 'R':
				out.append(line)
				continue
			logdir = 'pm-graph-test/%s/%s' % (kernel, host)
			pprint('\n[%s]\n' % host)
			call('tail -20 %s/runstress.log' % logdir, shell=True)
			print('')
		out.append(line)
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
	g.add_argument('command', choices=['build', 'online', 'install',
		'uninstall', 'ready', 'run', 'status'])
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
	elif args.user or args.host or args.addr:
		if not (args.user and args.host and args.addr):
			doError('user, host, and addr are required for single machine commands', False)
		machine = RemoteMachine(args.user, args.host, args.addr)
		if cmd == 'online':
			res = machine.checkhost(args.userinput)
			if res:
				pprint('%s: %s' % (args.host, res))
			else:
				pprint('%s: online' % args.host)
		elif cmd == 'install':
			kernelInstall(args, machine)
		elif cmd == 'uninstall':
			kernelUninstall(args, machine)
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
			res = pm_graph(args, machine)
		sys.exit(0)

	if not args.machines:
		doError('%s command requires a machine list' % args.command)

	# multiple machine commands
	if cmd == 'online':
		machlist = runStressCmd(args, 'online')
		if args.resetcmd:
			for h in machlist:
				resetmachine(args, machlist[h])
			time.sleep(30)
			machlist = runStressCmd(args, 'online')
		if len(machlist) > 0:
			print('Bad Hosts:')
			for h in machlist:
				print(h)
		sys.exit(0)
	elif cmd in ['install', 'uninstall']:
		filter = 'find:O' if cmd == 'install' else 'find:O,I,R'
		machlist = runStressCmd(args, filter)
		spawnMachineCmds(args, machlist, cmd)
		if cmd == 'install':
			runStressCmd(args, cmd, machlist)
		sys.exit(0)
	elif cmd == 'ready':
		if not args.kernel:
			doError('%s command requires kernel' % args.command)
		runStressCmd(args, 'ready')
		sys.exit(0)
	else:
		doError('command "%s" is not supported' % args.command)
