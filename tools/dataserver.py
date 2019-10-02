#!/usr/bin/python

import os
import sys
from subprocess import call, Popen, PIPE
try:
	from tools.parallel import AsyncProcess
except:
	from parallel import AsyncProcess

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
		call('scp %s %s@%s:%s/' % (file, self.user, self.host, dir), shell=True)
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
		print('Taring up %s for transport...' % folder)
		call('cd %s; tar cvzf %s %s > /dev/null' % (pdir, tarball, tdir), shell=True)
		print('Sending tarball to server...')
		self.scpfile(tarball, '/tmp')
		print('Notifying server of new data...')
		call('ssh -n -f %s@%s "nohup datahandler %s > /dev/null 2>&1 &"' % \
			(self.user, self.host, tarball), shell=True)
		os.remove(tarball)
		print('Upload Complete')
	def die(self):
		sys.exit(1)

# ----------------- MAIN --------------------
# exec start (skipped if script is loaded as library)
if __name__ == '__main__':
	import argparse

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

	ds = DataServer(args.u, 'otcpl-perf-data.jf.intel.com')
	ds.setupordie()

	if args.upload:
		ds.uploadfolder(args.upload)
	else:
		print(ds.sshcmd('df /media/disk*'))
