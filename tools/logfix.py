#!/usr/bin/env python3

import os
import os.path as op
import sys
import re
import time
import tempfile
import shutil
from datetime import datetime
from subprocess import call, Popen, PIPE

def sysinfoline(args, line):
	v = dict()
	for f in line.strip().split('|'):
		if '#' in f:
			continue
		tmp = f.strip().split(':', 1)
		key, val = tmp[0], tmp[1]
		v[key] = val
	if args.man:
		v['man'] = args.man
	if args.plat:
		v['plat'] = args.plat
	if args.cpu:
		v['cpu'] = args.cpu
	if args.bios:
		v['bios'] = args.bios
	if args.biosdate:
		v['biosdate'] = args.biosdate
	out = '# sysinfo | man:%s | plat:%s | cpu:%s | bios:%s | biosdate:%s | numcpu:%s | memsz:%s | memfr:%s\n' % \
		(v['man'], v['plat'], v['cpu'], v['bios'], v['biosdate'],
			v['numcpu'], v['memsz'], v['memfr'])
	return out

def logfix(args, file):
	fd, tmpfile = tempfile.mkstemp(prefix='sleepgraph-', text=True)
	fp, op = open(file, 'r'), open(tmpfile, 'w')
	for line in fp:
		if line.startswith('# sysinfo |'):
			line = sysinfoline(args, line)
		op.write(line)
	fp.close(), op.close()
	shutil.copyfile(tmpfile, file)
	os.remove(tmpfile)

def logfixall(args):
	for dirname, dirnames, filenames in os.walk(args.folder):
		for file in filenames:
			if not (file.endswith('_dmesg.txt') or
				file.endswith('_ftrace.txt') or
				file.endswith('_dmesg.txt.gz') or
				file.endswith('_ftrace.txt.gz')):
				continue
			filepath = op.join(dirname, file)
			print(filepath)
			gzip = True if file.endswith('.gz') else False
			if gzip:
				call('gunzip %s' % filepath, shell=True)
				filepath = filepath[:-3]
			logfix(args, filepath)
			if gzip:
				call('gzip %s' % filepath, shell=True)

def doError(msg):
	print('ERROR: %s\n' % msg)
	sys.exit(1)

if __name__ == '__main__':
	import argparse

	parser = argparse.ArgumentParser()
	parser.add_argument('-man', metavar='value', default='',
		help='Manufacturer Name')
	parser.add_argument('-plat', metavar='value', default='',
		help='Platform/Model Name')
	parser.add_argument('-cpu', metavar='value', default='',
		help='CPU Name/Version')
	parser.add_argument('-bios', metavar='value', default='',
		help='BIOS Version')
	parser.add_argument('-biosdate', metavar='value', default='',
		help='BIOS Date')
	parser.add_argument('folder')
	args = parser.parse_args()

	if args.folder == 'help':
		parser.print_help()
		sys.exit(0)

	if not op.exists(args.folder) or not op.isdir(args.folder):
		doError('%s is not a valid folder' % args.folder)

	logfixall(args)
