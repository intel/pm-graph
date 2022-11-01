#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
#
# RemoteMachine library
# Copyright (c) 2020, Intel Corporation.
#
# This program is free software; you can redistribute it and/or modify it
# under the terms and conditions of the GNU General Public License,
# version 2, as published by the Free Software Foundation.
#
# This program is distributed in the hope it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or
# FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License for
# more details.
#
# Authors:
#    Todd Brandt <todd.e.brandt@linux.intel.com>
#
# Description:
#	functions for manipulating kernel source and git repos

import os
import os.path as op
import sys
import re
import shutil
import time
from tempfile import mkdtemp
from subprocess import call, Popen, PIPE
from lib.common import mystarttime, pprint, printlines, ascii, runcmd

def isgit(src):
	return op.exists(op.join(src, '.git/config'))

def clone():
	repo = 'http://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git'
	src = mkdtemp(prefix='linux')
	pprint('Cloning new kernel source tree ...')
	call('git clone %s %s' % (repo, src), shell=True)
	return src

def configure(src, cfg, isgit):
	kconfig = ''
	if not op.exists(cfg) or not op.isdir(cfg):
		doError('%s is not an existing folder' % cfg)
	patches = []
	for file in sorted(os.listdir(cfg)):
		if file.endswith('.patch'):
			patches.append(op.join(cfg, file))
		elif file.endswith('.config'):
			kconfig = op.join(cfg, file)
	if len(patches) > 0:
		if isgit:
			runcmd('git -C %s checkout .' % src, True)
		for patch in sorted(patches):
			runcmd('patch -d %s -i %s -p1' % (src, patch), True)
	if not kconfig:
		doError('Missing kernel config file')
	runcmd('cp %s %s' % (kconfig, op.join(src, '.config')), True)
	return kconfig

def getconfig(cfg):
	if not op.exists(cfg) or not op.isdir(cfg):
		doError('%s is not an existing folder' % cfg)
	for file in sorted(os.listdir(cfg)):
		if file.endswith('.config'):
			return op.join(cfg, file)
	return ''

def turbostatbuild(src, latest=False):
	if not op.exists(src) or not op.isdir(src):
		doError('%s is not an existing folder' % src)
	isgit = op.exists(op.join(src, '.git/config'))
	if isgit and latest:
		runcmd('git -C %s checkout .' % src, True)
		runcmd('git -C %s checkout master' % src, True)
		runcmd('git -C %s pull' % src, True)
	tdir = op.join(src, 'tools/power/x86/turbostat')
	if op.isdir(tdir):
		call('make -C %s clean' % tdir, shell=True)
		call('make -C %s turbostat' % tdir, shell=True)
		call('%s/turbostat -v' % tdir, shell=True)

def clean(src, kconfig, latest=False):
	if latest and isgit(src):
		runcmd('git -C %s checkout .' % src, True)
		runcmd('git -C %s checkout master' % src, True)
		runcmd('git -C %s pull' % src, True)
	runcmd('make -C %s distclean' % src, True)
	runcmd('cp %s %s' % (kconfig, op.join(src, '.config')), True)

def build(src, pkgfmt, name):
	try:
		numcpu = int(runcmd('getconf _NPROCESSORS_ONLN', False, False)[0])
	except:
		numcpu = 2
	runcmd('make -C %s olddefconfig' % src, True)
	if name:
		kver = '%s-%s' % (runcmd('make -s -C %s kernelversion' % src)[0], name)
		runcmd('make -C %s -j %d bin%s-pkg LOCALVERSION=-%s' % \
			(src, numcpu, pkgfmt, name), True)
	else:
		kver = runcmd('make -s -C %s kernelrelease' % src)[0]
		runcmd('make -C %s -j %d bin%s-pkg' % \
			(src, numcpu, pkgfmt), True)
	turbostatbuild(src)
	miscfiles, packages = [], []
	outdir = os.path.realpath(os.path.join(src, '..'))
	for file in os.listdir(outdir):
		if kver not in file:
			continue
		created = os.path.getctime(op.join(outdir, file))
		if created < mystarttime:
			continue
		if file.endswith(pkgfmt):
			packages.append(file)
		else:
			miscfiles.append(file)
	for file in miscfiles:
		os.remove(os.path.join(outdir, file))
	return (outdir, kver, packages)

def move_packages(src, dst, packages):
	if not op.exists(dst):
		os.makedirs(dst)
	if src == os.path.realpath(dst):
		return
	for file in packages:
		tgt = os.path.join(dst, file)
		if op.exists(tgt):
			pprint('Overwriting %s' % file)
			os.remove(tgt)
		shutil.move(os.path.join(src, file), dst)

def kvermatch(kmatch, pkgfmt, pkgname):
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

def bisect_step_info(out):
	for line in out:
		m = re.match('\[(?P<commit>[a-z,0-9]*)\] .*', line)
		if m:
			commit = m.group('commit')
			return(commit, False)
		m = re.match('(?P<commit>[a-z,0-9]*) is the first bad commit', line)
		if m:
			commit = m.group('commit')
			return(commit, True)
	return ('', True)

def bisect_start(src, kgood, kbad):
	runcmd('git -C %s bisect reset' % src, False)
	runcmd('git -C %s bisect start' % src, True)
	runcmd('git -C %s bisect good %s' % (src, kgood), True)
	out = runcmd('git -C %s bisect bad %s' % (src, kbad), True)
	return bisect_step_info(out)

def bisect_step(src, state):
	if state not in ['good', 'bad']:
		doError('invalid bisect state, need good or bad: %s' % state)
	out = runcmd('git -C %s bisect %s' % (src, state), True)
	return bisect_step_info(out)
