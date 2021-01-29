#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
#
# Parallel library
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
#    interface for running and managing parallel commands and
#    asynchronous processes.

import os
import sys
import re
import time
import os.path as op
from subprocess import call, Popen, PIPE
from datetime import date, datetime, timedelta
from threading import Thread
import psutil
import signal
import fcntl

def ascii(text):
	return text.decode('ascii', 'ignore')

def permission_to_run(name, count, wait, pfunc=None):
	fps, i, success = [], 0, False
	for idx in range(count):
		file = '/tmp/%s%d.lock' % (name, idx)
		fps.append(open(file, 'w'))
		try:
			os.chmod(file, 0o666)
		except:
			pass
	while i < wait and not success:
		for fp in fps:
			try:
				fcntl.flock(fp, fcntl.LOCK_NB | fcntl.LOCK_EX)
				success = fp
				break
			except:
				pass
		if success:
			break
		if i == 0:
			msg = 'waiting to execute, only %d processes allowed at a time' % count
			if pfunc:
				pfunc(msg)
			else:
				print(msg)
		time.sleep(1)
		i += 1
	if not success:
		msg = 'timed out waiting for a slot to execute %s' % name
		if pfunc:
			pfunc(msg)
		else:
			print(msg)
		sys.exit(1)
	return success

def findProcess(name, args=[]):
	for proc in psutil.process_iter():
		try:
			pname = proc.name()
			pargs = proc.cmdline()
		except:
			continue
		if len(pargs) < 1:
			continue
		if pname.startswith('python') and len(pargs) > 1:
			pname, pargs = op.basename(pargs[1]), pargs[2:]
		else:
			pname, pargs = op.basename(pname), pargs[1:]
		if pname != name or len(args) > len(pargs):
			continue
		match = True
		for i in range(0, len(args)):
			if args[i] != pargs[i]:
				match = False
				break
		if match:
			return True
	return False

class AsyncProcess:
	saveout = False
	output = ''
	complete = False
	terminated = False
	cmd = ''
	timeout = 1800
	machine = ''
	def __init__(self, cmdstr, timeout, machine=''):
		self.cmd = cmdstr
		self.timeout = timeout
		self.machine = machine
	def ping(self, count):
		if not self.machine:
			return True
		val = os.system('ping -q -c %d %s > /dev/null 2>&1' % (count, self.machine))
		if val != 0:
			return False
		return True
	def psutilCheckv2(self):
		try:
			test = psutil.Process.children
			return True
		except:
			return False
	def killProcessTree(self, tgtpid):
		if tgtpid == 0:
			return 0
		pidlist = [tgtpid]
		try:
			ps = psutil.Process(tgtpid)
		except:
			return 0
		if self.psutilCheckv2():
			for child in ps.children(recursive=True):
				pidlist.append(child.pid)
		else:
			for child in ps.get_children(recursive=True):
				pidlist.append(child.pid)
		for pid in sorted(pidlist, reverse=True):
			os.kill(pid, signal.SIGKILL)
		return len(pidlist)
	def terminate(self):
		self.killProcessTree(self.process.pid)
		self.terminated = True
	def processMonitor(self, tid):
		t = 0
		while self.process.poll() == None:
			if t > self.timeout or not self.ping(3):
				self.terminate()
				break
			time.sleep(1)
			t += 1
		if self.saveout:
			self.output = ascii(self.process.stdout.read())
		self.complete = True
	def runcmd(self):
		out = ''
		self.complete = self.terminated = False
		# create system monitor thread and process
		self.thread = Thread(target=self.processMonitor, args=(0,))
		self.process = Popen([self.cmd+' 2>&1'], shell=True, stdout=PIPE)
		# start the process & monitor
		self.thread.start()
		for line in self.process.stdout:
			out += ascii(line)
		result = self.process.wait()
		self.complete = True
		return out
	def runcmdasync(self, saveoutput=False):
		self.saveout = saveoutput
		self.complete = self.terminated = False
		# create system monitor thread and process
		self.thread = Thread(target=self.processMonitor, args=(0,))
		if self.saveout:
			self.process = Popen([self.cmd+' 2>&1'], shell=True, stdout=PIPE)
		else:
			self.process = Popen([self.cmd+' 2>&1'], shell=True)
		# start the process & monitor
		self.thread.start()

class MultiProcess:
	pending = []
	active = []
	complete = []
	rmq = []
	cpus = 0
	def __init__(self, cmdlist, timeout, verbose=False):
		self.verbose = verbose
		self.cpus = self.cpucount()
		for cmd in cmdlist:
			self.pending.append(AsyncProcess(cmd, timeout))
	def cpucount(self):
		cpus = 0
		fp = open('/proc/cpuinfo', 'r')
		for line in fp:
			if re.match('^processor[ \t]*:[ \t]*[0-9]*', line):
				cpus += 1
		fp.close()
		return cpus
	def emptytrash(self, tgt):
		for item in self.rmq:
			tgt.remove(item)
		self.rmq = []
	def run(self, count=0, saveout=False):
		fails = []
		count = self.cpus if count < 1 else count
		while len(self.pending) > 0 or len(self.active) > 0:
			# remove completed cmds from active queue (active -> completed)
			for cmd in self.active:
				if cmd.complete:
					self.rmq.append(cmd)
					self.complete.append(cmd)
					if cmd.terminated:
						fails.append(cmd.cmd)
					if self.verbose:
						if cmd.terminated:
							print('TERMINATED: %s' % cmd.cmd)
						else:
							print('COMPLETE: %s' % cmd.cmd)
			self.emptytrash(self.active)
			# fill active queue with pending cmds (pending -> active)
			for cmd in self.pending:
				if len(self.active) >= count:
					break
				self.rmq.append(cmd)
				self.active.append(cmd)
				if self.verbose:
					print('START: %s' % cmd.cmd)
				cmd.runcmdasync(saveout)
			self.emptytrash(self.pending)
			time.sleep(1)
		return fails

class AsyncCall:
	func = 0
	args = 0
	result = 0
	complete = False
	def __init__(self, myfunc, myargs):
		self.func = myfunc
		self.args = myargs
	def wrapper(self, tid):
		self.result = self.func(*self.args)
		self.complete = True
	def run(self):
		self.thread = Thread(target=self.wrapper, args=(0,))
		self.thread.start()

class MultiCall:
	pending = []
	active = []
	complete = []
	rmq = []
	def __init__(self, func, arglist):
		for args in arglist:
			self.pending.append(AsyncCall(func, args))
	def emptytrash(self, tgt):
		for item in self.rmq:
			tgt.remove(item)
		self.rmq = []
	def run(self, count=10):
		while len(self.pending) > 0 or len(self.active) > 0:
			# remove completed cmds from active queue (active -> completed)
			for cmd in self.active:
				if cmd.complete:
					self.rmq.append(cmd)
					self.complete.append(cmd)
			self.emptytrash(self.active)
			# fill active queue with pending cmds (pending -> active)
			for cmd in self.pending:
				if len(self.active) >= count:
					break
				self.rmq.append(cmd)
				self.active.append(cmd)
				cmd.run()
			self.emptytrash(self.pending)
			time.sleep(1)
		return
	def results(self):
		out = []
		for cmd in self.complete:
			out.append(cmd.result)
		return out

# ----------------- MAIN --------------------
# exec start (skipped if script is loaded as library)
if __name__ == '__main__':
	import argparse

	parser = argparse.ArgumentParser()
	parser.add_argument('-timeout', metavar='number', type=int, default=1800,
		help='Timeout in seconds for each process')
	parser.add_argument('-multi', metavar='number', type=int, default=0,
		help='Maximum concurrent processes to be run')
	parser.add_argument('commands', nargs='+')
	args = parser.parse_args()

	mp = MultiProcess(args.commands, args.timeout, True)
	mp.run(args.multi)
