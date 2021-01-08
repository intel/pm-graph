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
from tools.parallel import MultiProcess
from tools.argconfig import args_from_config, arg_to_path
from tools.remotemachine import RemoteMachine

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
			print(line.strip())

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
	print('WIFI DEVICE NAME: %s' % m.wdev)
	print('WIFI MAC ADDRESS: %s' % m.wmac)
	print('WIFI ESSID      : %s' % m.wap)
	print('WIFI IP ADDRESS : %s' % m.wip)
	printlines(out)
	pprint('configure grub')
	out = m.configure_grub()
	printlines(out)

	# remove unneeeded space
	pprint('remove previous data')
	printlines(m.sshcmd('rm -r pm-graph-test ; mkdir pm-graph-test', 10))

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

def kernelInstallMulti(args, machlist):
	if not (args.pkgfmt and args.pkgout and args.kernel):
		doError('kernel install is missing arguments', False)

	cmds = []
	cmdfmt = '%s -pkgout %s -pkgfmt %s -kernel %s -user {0} -host {1} -addr {2} install' % \
		(op.abspath(sys.argv[0]), args.pkgout, args.pkgfmt, args.kernel)
	for host in machlist:
		m = machlist[host]
		cmds.append(cmdfmt.format(m.user, m.host, m.addr))

	pprint('Installing on %d hosts ...' % len(machlist))
	mp = MultiProcess(cmds, 1800)
	mp.run(8, True)
	for acmd in mp.complete:
		host = acmd.cmd.split()[10]
		fp = open('/tmp/%s.log' % host, 'w')
		fp.write(acmd.output)
		fp.close()
		if host not in machlist:
			continue
		m = machlist[host]
		if acmd.terminated or 'FAILURE' in acmd.output or 'ERROR' in acmd.output:
			m.status = False
		else:
			m.status = True
			m.sshcmd('sudo reboot', 30)

def runStressCmd(args, cmd, mlist=None):
	file = args.machines
	out, fp = [], open(file)
	machlist = dict()

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
		# ONLINE - look at prefix-less machines
		if cmd == 'online':
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
				line = 'O '+line
				pprint('%30s: online' % host)
		# INSTALL(able) - look at O machines
		elif cmd == 'installable':
			if flag != 'O':
				out.append(line)
				continue
			machlist[host] = machine
		# INSTALL - look at O machines
		elif cmd == 'install':
			if flag != 'O' or not mlist:
				out.append(line)
				continue
			if mlist[host].status:
				pprint('%30s: install success' % host)
				line = 'I'+line[1:]
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
			line = 'R'+line[1:]
			pprint('%30s: ready' % host)
		# RUN - look at R machines
		elif cmd == 'run':
			if flag != 'R':
				out.append(line)
				continue
			host = line[2:].split()[0]
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
			host = line[2:].split()[0]
			logdir = 'pm-graph-test/%s/%s' % (kernel, host)
			pprint('\n[%s]\n' % host)
			call('tail -20 %s/runstress.log' % logdir, shell=True)
			print('')
		out.append(line)
	fp.close()
	fp = open(file, 'w')
	for line in out[:-1]:
		fp.write(line.strip()+'\n')
	fp.close()
	return machlist

if __name__ == '__main__':

	parser = argparse.ArgumentParser()
	parser.add_argument('-config', metavar='file', default='',
		help='use config file to fill out the remaining args')
	# kernel build
	parser.add_argument('-pkgfmt', metavar='type',
		choices=['deb', 'rpm'], default='deb',
		help='kernel package format [rpm/deb] (default: deb)')
	parser.add_argument('-pkgout', metavar='folder', default='',
		help='output folder for kernel packages (default: ksrc/..)')
	parser.add_argument('-ksrc', metavar='folder', default='',
		help='kernel source folder (required to build)')
	parser.add_argument('-kname', metavar='string', default='',
		help='kernel name as "<version>-<name>" (default: <version>)')
	parser.add_argument('-kcfg', metavar='folder', default='',
		help='config & patches folder (default: use .config in ksrc)')
	parser.add_argument('-ktag', metavar='gittag', default='',
		help='kernel source git tag (default: no change)')
	# machine install
	parser.add_argument('-userinput', action='store_true',
		help='allow user interaction when executing remote commands')
	parser.add_argument('-machines', metavar='file', default='',
		help='input/output file with machine host/addr/user list')
	parser.add_argument('-kernel', metavar='string', default='',
		help='kernel version of package for install and test')
	parser.add_argument('-user', metavar='string', default='')
	parser.add_argument('-host', metavar='string', default='')
	parser.add_argument('-addr', metavar='string', default='')
	parser.add_argument('-proxy', metavar='string', default='')
	# command
	parser.add_argument('command', choices=['build', 'online', 'install', 'ready'],
		help='command to run')
	args = parser.parse_args()

	cmd = args.command
	if args.config:
		err = args_from_config(parser, args, args.config, 'setup')
		if err:
			doError(err)

	arg_to_path(args, ['ksrc', 'kcfg', 'pkgout', 'machines'])

	# single machine command
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
		sys.exit(0)

	# multiple machine commands
	if not args.machines:
		doError('%s command requires a machine list' % args.command)

	if cmd == 'online':
		machlist = runStressCmd(args, 'online')
		if len(machlist) > 0:
			print('Bad Hosts:')
			for h in machlist:
				print(h)
		sys.exit(0)
	elif cmd == 'install':
		machlist = runStressCmd(args, 'installable')
		kernelInstallMulti(args, machlist)
		runStressCmd(args, 'install', machlist)
		sys.exit(0)
	elif cmd == 'ready':
		if not args.kernel:
			doError('%s command requires kernel' % args.command)
		runStressCmd(args, 'ready')
		sys.exit(0)
	else:
		doError('command "%s" is not supported' % args.command)
