#!/usr/bin/python

import os
import sys
import fcntl
import warnings
import re
import time
import json
from subprocess import call, Popen, PIPE
from datetime import date, datetime, timedelta
from threading import Thread
import psutil
import signal

def ascii(text):
	return text.decode('ascii', 'ignore')

class AsyncProcess:
	complete = False
	terminated = False
	timeout = 1800
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
	def runcmdasync(self):
		self.complete = self.terminated = False
		# create system monitor thread and process
		self.thread = Thread(target=self.processMonitor, args=(0,))
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
	def run(self, count=0):
		count = self.cpus if count < 1 else count
		while len(self.pending) > 0 or len(self.active) > 0:
			# remove completed cmds from active queue (active -> completed)
			for cmd in self.active:
				if cmd.complete:
					self.rmq.append(cmd)
					self.complete.append(cmd)
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
				cmd.runcmdasync()
			self.emptytrash(self.pending)
			time.sleep(1)
		return

class DataServer:
	ip = 'otcpl-perf-data.jf.intel.com'
	def __init__(self, user, disk):
		self.user = user
		self.rpath = '/media/disk%d/pm-graph-test' % disk
	def sshproc(self, cmd, timeout=60):
		return AsyncProcess(('ssh %s@%s "nohup {0}"' % (self.user, self.ip)).format(cmd), timeout, self.ip)
	def sshcmd(self, cmd, timeout=60):
		ap = self.sshproc(cmd, timeout)
		out = ap.runcmd()
		if ap.terminated:
			print('SSH TIMEOUT: %s' % cmd)
			self.die()
		return out
	def scpfile(self, file, dir):
		call('scp %s %s@%s:%s/' % (file, self.user, self.ip, dir), shell=True)
	def enablessh(self):
		call('ssh-keygen -q -f "$HOME/.ssh/known_hosts" -R "'+self.ip+'" > /dev/null', shell=True)
		call('scp -oStrictHostKeyChecking=no $HOME/.ssh/authorized_keys '+self.user+'@'+self.ip+':.ssh/ > /dev/null 2>&1', shell=True)
	def uploadfolder(self, folder):
		if not os.path.exists(folder):
			doError('%s does not exist' % folder)
		if not os.path.isdir(folder):
			doError('%s is not a folder' % folder)
		pdir, tdir = os.path.dirname(folder), os.path.basename(folder)
		pdir = pdir if pdir else '.'
		tarball = '/tmp/%s.tar.gz' % tdir
		print(datetime.now())
		print('Taring up %s for transport...' % folder)
		call('cd %s; tar cvzf %s %s > /dev/null' % (pdir, tarball, tdir), shell=True)
		print(datetime.now())
		print('Sending tarball to server %s...' % self.rpath)
		ds.scpfile(tarball, self.rpath)
		print(datetime.now())
		print('UnTaring file on server...')
		ds.sshcmd('nohup tar -C %s -xvzf %s/%s.tar.gz > /dev/null 2>&1 &' % \
			(self.rpath, self.rpath, tdir), 1800)
		os.remove(tarball)
		ds.sshcmd('rm -f %s/%s.tar.gz' % (self.rpath, tdir))
		ds.sshcmd('ln -s %s/%s /home/tebrandt/pm-graph-test/' % (self.rpath, tdir))
		print('upload complete')
	def die(self):
		sys.exit(1)

def doError(msg):
	print('ERROR: %s\n' % msg)
	sys.exit(1)

# ----------------- MAIN --------------------
# exec start (skipped if script is loaded as library)
if __name__ == '__main__':
	import argparse, os
	user = 'labuser' if 'USER' not in os.environ else os.environ['USER']

	parser = argparse.ArgumentParser()
	parser.add_argument('-r', '-run', metavar='cmdlist',
		help='run a series of commands in parallel')
	parser.add_argument('-timeout', metavar='number', type=int, default=1800,
		help='Timeout in seconds for each process')
	parser.add_argument('-multi', metavar='number', type=int, default=0,
		help='Maximum concurrent processes to be run')
	parser.add_argument('-u', '-upload', metavar='folder',
		help='upload a sleepgraph multitest folder to otcpl-perf-data')
	parser.add_argument('-d', '-disk', metavar='number', type=int, default=1,
		help='use disk N as the location, valid values are 1 - 8')
	args = parser.parse_args()

	if args.d < 1 or args.d > 8:
		doError('disk number can only be between 1 and 8')

	if args.u:
		ds = DataServer(user, args.d)
		ds.uploadfolder(args.u)
	elif args.r:
		cmds = []
		for cmd in args.r.split(';'):
			if cmd.strip():
				cmds.append(cmd.strip())
		mp = MultiProcess(cmds, args.timeout, True)
		mp.run(args.multi)
