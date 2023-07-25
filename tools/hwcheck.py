#!/usr/bin/env python3

import os
import os.path as op
import sys
import re
import platform
import time
import glob
import tempfile
import shutil
from datetime import datetime
from subprocess import call, Popen, PIPE

class LogFile:
	datalist = {
		'bios': {
			'cmd': 'sleepgraph -sysinfo | grep -v mem'
		},
		'usb': {
			'cmd': 'lsusb -tv'
		},
		'pci': {
			'cmd': 'lspci -tv'
		}
	}
	varlog = '/var/log/hwchange'
	hostname = 'localhost'

	def __init__(self):
		try:
			out = platform.node()
			if out.strip():
				self.hostname = out
		except:
			pass
		if op.exists(self.varlog) and (not op.isdir(self.varlog) or \
			not os.access(self.varlog, os.W_OK)):
			self.varlog = '/tmp'
		elif not op.exists(self.varlog):
			try:
				os.mkdir(self.varlog)
			except:
				self.varlog = '/tmp'
	def logName(self, title):
		stamp = datetime.today().strftime('%y%m%d-%H%M%S')
		file = '%s-%s-%s.log' % (stamp, self.hostname, title)
		return op.join(self.varlog, file)

	def runCheckSection(self, title, lastlog):
		cmd = self.datalist[title]['cmd']
		fd, tmpfile = tempfile.mkstemp(suffix=title, prefix='hwcheck', text=True)
		call('%s > %s 2>/dev/null' % (cmd, tmpfile), shell=True)
		if lastlog:
			ret = call('diff -q %s %s > /dev/null 2>&1' % (lastlog, tmpfile), shell=True)
			if ret == 0:
				os.remove(tmpfile)
				return
		outfile = self.logName(title)
		shutil.copyfile(tmpfile, outfile)
		os.remove(tmpfile)

	def runCheck(self, title):
		for t in sorted(self.datalist):
			if title != 'all' and t != title:
				continue
			logs = glob.glob('%s/*-%s.log' % (self.varlog, t))
			latest = sorted(logs)[-1] if len(logs) > 0 else ''
			self.runCheckSection(t, latest)

	@staticmethod
	def getExec(cmd):
		try:
			fp = Popen(['which', cmd], stdout=PIPE, stderr=PIPE).stdout
			out = fp.read().decode('ascii', 'ignore').strip()
			fp.close()
		except:
			out = ''
		if out:
			return out
		for path in ['/sbin', '/bin', '/usr/sbin', '/usr/bin',
			'/usr/local/sbin', '/usr/local/bin']:
			cmdfull = os.path.join(path, cmd)
			if os.path.exists(cmdfull):
				return cmdfull
		return out

	@staticmethod
	def rootCheck(fatal=True):
		if(os.access('/sys/power/state', os.W_OK)):
			return True
		if fatal:
			doError('Root access required, please run with sudo')
		return False

def doError(msg):
	print('ERROR: %s' % msg)
	sys.exit(1)

if __name__ == '__main__':
	import argparse

	parser = argparse.ArgumentParser()
	parser.add_argument('command', choices=['all', 'bios',
		'pci', 'usb', 'help'])
	args = parser.parse_args()

	if args.command == 'help':
		parser.print_help()
		sys.exit(0)

	LogFile.rootCheck()
	log = LogFile()
	log.runCheck(args.command)
