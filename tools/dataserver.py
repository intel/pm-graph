#!/usr/bin/python

import os
import sys
import time
from subprocess import call, Popen, PIPE
from datetime import date, datetime, timedelta
try:
	from tools.parallel import AsyncProcess
except:
	pass

class DataServer:
	ip = 'otcpl-perf-data.jf.intel.com'
	def __init__(self, user, disk=0):
		if disk == 0:
			disk = (datetime.now().second % 8) + 1
		self.user = user
		self.rpath = '/media/disk%d/pm-graph-test' % disk
	def sshcopyid(self):
		res = call('ssh-copy-id %s@%s' % (self.user, self.ip), shell=True)
		return res == 0
	def sshkeyworks(self):
		cmd = 'ssh -q -o BatchMode=yes -o ConnectTimeout=5 %s@%s echo -n' % \
			(self.user, self.ip)
		res = call(cmd, shell=True)
		return res == 0
	def setup(self):
		if self.sshkeyworks():
			return True
		print('You must have an account on %s and an authorized ssh key\nto use this tool. '\
			'I will try to add your id_rsa.pub using ssh-copy-id...' %\
			(self.ip))
		if not self.sshcopyid():
			return False
		if not self.sshkeyworks():
			print('ERROR: failed to setup ssh key access.')
			return False
		print('SUCCESS: you now have password-less access.\n')
		return True
	def setupordie(self):
		if not self.setup():
			sys.exit(1)
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
		self.sshcmd('nohup tar -C %s -xvzf %s/%s.tar.gz > /dev/null 2>&1 && rm %s/%s.tar.gz &' % \
			(self.rpath, self.rpath, tdir, self.rpath, tdir), 1800)
		os.remove(tarball)
		self.sshcmd('ln -sf %s/%s /home/tebrandt/pm-graph-test/' % (self.rpath, tdir))
		print('upload complete')
	def die(self):
		sys.exit(1)

# ----------------- MAIN --------------------
# exec start (skipped if script is loaded as library)
if __name__ == '__main__':
	import argparse
	from parallel import AsyncProcess

	user = '' if 'USER' not in os.environ else os.environ['USER']

	parser = argparse.ArgumentParser()
	parser.add_argument('-u', '-user', metavar='name', default=user,
		help='username for data server')
	parser.add_argument('-upload', metavar='folder',
		help='upload a sleepgraph multitest folder to otcpl-perf-data')
	args = parser.parse_args()

	if not args.u:
		print('ERROR: a username is required, please set $USER or use -user')
		sys.exit(1)

	ds = DataServer(args.u)
	ds.setupordie()

	if args.upload:
		ds.uploadfolder(args.upload)
	else:
		print(ds.sshcmd('df /media/disk*'))
