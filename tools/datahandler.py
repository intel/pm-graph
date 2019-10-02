#!/usr/bin/python

import os
import sys
import time
import re
from subprocess import call, Popen, PIPE
from datetime import date, datetime, timedelta

webroot = '/home/tebrandt/pm-graph-test/'

def doError(msg):
	print('ERROR: %s\n' % msg)
	sys.exit(1)

if __name__ == '__main__':
	import argparse
	parser = argparse.ArgumentParser()
	parser.add_argument('tarball')
	args = parser.parse_args()

	# get the folder name in the tarball
	m = re.match('/tmp/(?P<name>.*)\.tar\.gz', args.tarball)
	if not m:
		doError('input tarball does not match /tmp/<name>.tar.gz')
	folder =  m.group('name')
	# get the disk with the most available space
	fp = Popen('df', stdout=PIPE, stderr=PIPE).stdout
	disks = dict()
	for line in fp:
		m = re.match('.* (?P<used>[0-9]*)\% (?P<disk>/media/disk[0-9]*)$', line)
		if not m:
			continue
		disks[m.group('disk')] = int(m.group('used'))
	fp.close()
	if len(disks.keys()) < 1:
		doError('no disks found')
	dir = os.path.join(sorted(disks, key=lambda k:disks[k])[0], 'pm-graph-test')
	# get the pm-graph-test folder on the target disk
	if not os.path.exists(dir):
		os.mkdir(dir)
		if not os.path.exists(dir):
			doError('Could not create %s' % dir)
	# create the link and extract the data
	call('ln -sf %s/%s %s' % (dir, folder, webroot), shell=True)
	call('tar -C %s -xvzf %s' % (dir, args.tarball), shell=True)
	os.remove(args.tarball)
