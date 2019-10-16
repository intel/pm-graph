#!/usr/bin/python

import os
import sys
from datetime import datetime
from subprocess import call, Popen, PIPE
try:
	# run as program
	from parallel import AsyncProcess
except:
	# run as library
	from tools.parallel import AsyncProcess

class DataServer:
	def __init__(self, user, host):
		self.host = host
		self.user = user
	def sshcopyid(self):
		res = call('ssh-copy-id %s@%s' % (self.user, self.host), shell=True)
		return res == 0
	def sshkeyworks(self):
		cmd = 'ssh -q -o BatchMode=yes -o ConnectTimeout=5 %s@%s echo -n' % \
			(self.user, self.host)
		res = call(cmd, shell=True)
		return res == 0
	def setup(self):
		if self.sshkeyworks():
			return True
		print('You must have an account on %s and an authorized ssh key\nto use this tool. '\
			'I will try to add your id_rsa.pub using ssh-copy-id...' %\
			(self.host))
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
		return AsyncProcess(('ssh %s@%s "{0}"' % (self.user, self.host)).format(cmd), timeout, self.host)
	def sshcmd(self, cmd, timeout=60):
		ap = self.sshproc(cmd, timeout)
		out = ap.runcmd()
		if ap.terminated:
			print('SSH TIMEOUT: %s' % cmd)
			self.die()
		return out
	def scpfile(self, file, dir):
		res = call('scp %s %s@%s:%s/' % (file, self.user, self.host, dir), shell=True)
		return res == 0
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
		logfile = 'multitest-%s-%s.log' % (datetime.now().strftime('%y%m%d-%H%M%S'), tdir)
		print('Taring up %s for transport...' % folder)
		res = call('cd %s; tar cvzf %s %s > /dev/null' % (pdir, tarball, tdir), shell=True)
		if res != 0:
			print('ERROR: failed to create the tarball')
			self.die()
		print('Sending tarball to server...')
		if not self.scpfile(tarball, '/tmp'):
			print('ERROR: could not upload the tarball')
			os.remove(tarball)
			self.die()
		print('Notifying server of new data...')
		res = call('ssh -n -f %s@%s "multitest %s > %s 2>&1 &"' % \
			(self.user, self.host, tarball, logfile), shell=True)
		if res != 0:
			print('ERROR: failed to notify the server of new data')
			os.remove(tarball)
			self.die()
		os.remove(tarball)
		print('Logging at %s' % logfile)
		print('Upload Complete')
	def openshell(self):
		call('ssh -X %s@%s' % (self.user, self.host), shell=True)
	def by_my_lonesome(self):
		out = self.sshcmd('ps aux')
		for line in out.split('\n'):
			if 'googlesheet' in line and '-webdir' in line:
				return False
		return True
	def die(self):
		sys.exit(1)

# ----------------- MAIN --------------------
# exec start (skipped if script is loaded as library)
if __name__ == '__main__':
	import argparse

	parser = argparse.ArgumentParser()
	parser.add_argument('-sshkeysetup', action='store_true',
		 help='setup password-less access by copying ssh keys')
	parser.add_argument('folder',
		help='multitest folder, or "shell" to open an ssh shell')
	args = parser.parse_args()

	if args.folder != 'shell' and \
		(not os.path.exists(args.folder) or not os.path.isdir(args.folder)):
		print('ERROR: %s is not a valid folder' % args.folder)
		sys.exit(1)

	ds = DataServer('sleepgraph', 'otcpl-perf-data.jf.intel.com')

	if args.sshkeysetup:
		ds.setupordie()

	if not ds.by_my_lonesome():
		print('Server is currently processing other data, please try again later.')
		print('Exitting...')
		sys.exit(1)

	if args.folder == 'shell':
		ds.openshell()
	else:
		ds.uploadfolder(args.folder)
