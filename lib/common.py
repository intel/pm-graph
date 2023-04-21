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
#	common functions

import os
import sys
import re
import time
from subprocess import call, Popen, PIPE

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

def doError(msg):
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

def userprompt(text, values):
	while True:
		res = input('\n'+text+' ')
		if res in values:
			return res
		print('Valid responese are %s' % values)
	return ''

def userprompt_yesno(text):
	out = userprompt(text, ['yes', 'y', 'no', 'n'])
	if out[0] == 'y':
		return True
	return False

def printRecursive(out, tab=''):
	if type(out) != type(dict()):
		print(out)
		return
	for i in sorted(out):
		if type(out[i]) == type(dict()):
			print('%s%s:' % (tab, i))
			printRecursive(out[i], tab+'    ')
			continue
		elif type(out[i]) == type([]):
			names = []
			for j in out[i]:
				names.append(j[0][:20])
			print('%s%s: %s' % (tab, i, ','.join(names)))
		else:
			print('%s%s: %s' % (tab, i, out[i]))
