#!/usr/bin/python

import os
import sys
import time
from subprocess import call, Popen, PIPE
from datetime import date, datetime, timedelta
import asyncprocess as ap

class DataServer:
	ip = 'otcpl-perf-data.jf.intel.com'
	def __init__(self, user, disk):
		self.user = user
		self.rpath = '/media/disk%d/pm-graph-test' % disk
	def sshproc(self, cmd, timeout=60):
		return ap.AsyncProcess(('ssh %s@%s "{0}"' % (self.user, self.ip)).format(cmd), timeout, self.ip)
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
			print('ERROR: %s does not exist' % folder)
			self.die()
		if not os.path.isdir(folder):
			print('%s is not a folder' % folder)
			self.die()
		pdir, tdir = os.path.dirname(folder), os.path.basename(folder)
		pdir = pdir if pdir else '.'
		tarball = '/tmp/%s.tar.gz' % tdir
		print(datetime.now())
		print('Taring up %s for transport...' % folder)
		call('cd %s; tar cvzf %s %s > /dev/null' % (pdir, tarball, tdir), shell=True)
		print(datetime.now())
		print('Sending tarball to server %s...' % self.rpath)
		self.scpfile(tarball, self.rpath)
		print(datetime.now())
		print('UnTaring file on server...')
		self.sshcmd('nohup tar -C %s -xvzf %s/%s.tar.gz > /dev/null 2>&1 &' % \
			(self.rpath, self.rpath, tdir), 1800)
		os.remove(tarball)
		self.sshcmd('rm -f %s/%s.tar.gz' % (self.rpath, tdir))
		self.sshcmd('ln -s %s/%s /home/tebrandt/pm-graph-test/' % (self.rpath, tdir))
		print('upload complete')
	def die(self):
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
		print('ERROR: disk number can only be between 1 and 8')
		sys.exit(1)

	if not args.u:
		print('ERROR: -u or -upload is required')
		sys.exit(1)

	ds = DataServer(user, args.d)
	ds.uploadfolder(args.u)
