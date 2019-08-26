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
	def terminate(self):
		self.terminated = True
		killProcessTree(self.process.pid)
	def systemMonitor(self, tid):
		t = 0
		while self.process.poll() == None:
			if t > self.timeout and not self.ping(3):
				self.terminate()
				break
			time.sleep(1)
			t += 1
	def runcmd(self):
		global child_process
		out = ''
		self.terminated = False
		# create system monitor thread and process
		self.thread = Thread(target=self.systemMonitor, args=(0,))
		c = [self.cmd+' 2>&1']
		self.process = Popen(c, shell=True, stdout=PIPE)
		child_process = self.process.pid
		# start the system monitor
		self.thread.start()
		# start the process
		for line in self.process.stdout:
			out += ascii(line)
		result = self.process.wait()
		child_process = 0
		return out

def psutilCheckv2():
	try:
		test = psutil.Process.children
		return True
	except:
		return False

def killProcessTree(tgtpid):
	if tgtpid == 0:
		return 0
	pidlist = [tgtpid]
	try:
		ps = psutil.Process(tgtpid)
	except:
		return 0
	if psutilCheckv2():
		for child in ps.children(recursive=True):
			pidlist.append(child.pid)
	else:
		for child in ps.get_children(recursive=True):
			pidlist.append(child.pid)
	for pid in sorted(pidlist, reverse=True):
		os.kill(pid, signal.SIGKILL)
	return len(pidlist)

class DataServer:
	ip = 'otcpl-perf-data.jf.intel.com'
	def __init__(self, user, disk):
		self.user = user
		self.rpath = '/media/disk%d/pm-graph-test' % disk
	def sshproc(self, cmd, timeout=60):
		return AsyncProcess(('ssh %s@%s "{0}"' % (self.user, self.ip)).format(cmd), timeout, self.ip)
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
		print('Taring up %s for transport...' % folder)
		call('cd %s ; tar cvzf %s %s > /dev/null 2>&1' % (pdir, tarball, tdir), shell=True)
		print('Sending tarball to server %s...' % self.rpath)
		ds.scpfile(tarball, self.rpath)
		print('UnTaring file on server...')
		ds.sshcmd('cd %s ; tar xvzf %s.tar.gz' % (self.rpath, tdir), 1800)
		os.remove(tarball)
		ds.sshcmd('cd %s ; rm %s.tar.gz' % (self.rpath, tdir))
		ds.sshcmd('cd /home/tebrandt/pm-graph-test ; ln -s %s/%s' % (self.rpath, tdir))
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
