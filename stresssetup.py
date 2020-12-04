#!/usr/bin/env python3
#
# Sleepgraph Stress Test Setup
#

import os
import sys
import warnings
import re
import shutil
import time
import pickle
import fcntl
from distutils.dir_util import copy_tree
from tempfile import NamedTemporaryFile, mkdtemp
from subprocess import call, Popen, PIPE
from datetime import datetime
import argparse
import os.path as op
from tools.parallel import MultiProcess, permission_to_run

mystarttime = time.time()
def pprint(msg, withtime=True):
	if withtime:
		print('[%05d] %s' % (time.time()-mystarttime, msg))
	else:
		print(msg)
	sys.stdout.flush()

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
	if not op.exists(args.ksrc) or not op.isdir(args.ksrc):
		doError('%s is not an existing folder' % args.ksrc, False)

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
	if args.name:
		runcmd('make -C %s -j %d %s-pkg LOCALVERSION=-%s' % \
			(args.ksrc, numcpu, args.pkg, args.name), True)
	else:
		runcmd('make -C %s -j %d %s-pkg' % \
			(args.ksrc, numcpu, args.pkg), True)

	# find the output files
	miscfiles, packages, out = [], [], []
	outdir = os.path.realpath(os.path.join(args.ksrc, '..'))
	for file in os.listdir(outdir):
		if kver not in file:
			continue
		created = os.path.getctime(op.join(outdir, file))
		if created < mystarttime:
			continue
		if file.endswith(args.pkg):
			packages.append(file)
		else:
			miscfiles.append(file)

	# move the output files to the output folder
	if args.pkgout:
		if not op.exists(args.pkgout):
			os.mkdir(args.pkgout)
		for file in miscfiles + packages:
			shutil.move(os.path.join(outdir, file), args.pkgout)
		outdir = args.pkgout

	pprint('Packages in %s' % outdir)
	for file in sorted(packages):
		out.append(op.join(outdir, file))
		pprint('   %s' % file)
	pprint('Other output files in %s' % outdir)
	for file in sorted(miscfiles):
		pprint('   %s' % file)

	return out

if __name__ == '__main__':

	parser = argparse.ArgumentParser()
	parser.add_argument('-config', metavar='file', default='')
	parser.add_argument('-name', metavar='string', default='')
	parser.add_argument('-arch', metavar='string',
		choices=['amd64', 'i386'], default='amd64')
	parser.add_argument('-pkg', metavar='type',
		choices=['deb', 'rpm'], default='deb')
	parser.add_argument('-pkgout', metavar='folder', default='')
	parser.add_argument('-kcfg', metavar='folder', default='')
	parser.add_argument('-ktag', metavar='gittag', default='')
	parser.add_argument('-ksrc', metavar='gitdir', default='')
	args = parser.parse_args()

	if args.ksrc:
		kernelBuild(args)
