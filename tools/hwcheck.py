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
import struct
from datetime import datetime
from subprocess import call, Popen, PIPE

datalist = {
	'system': {},
	'usb': {
		'cmd': 'lsusb | sed -e "s/ Device [0-9]*//g" | sort'
	},
	'pci': {
		'cmd': 'lspci -tv'
	},
	'disk': {
		'cmd': 'lsblk -o "TYPE,NAME,VENDOR,MODEL,REV,SERIAL,TRAN" | grep -e disk -e part'
	},
	'dmidecode': {
		'cmd': 'dmidecode'
	},
}

def pprint(msg):
	print(msg)
	sys.stdout.flush()

def sysinfo(fatal=False):
	out = dict()

	# the list of values to retrieve, with hardcoded (type, idx)
	info = {
		'bios-vendor': (0, 4),
		'bios-version': (0, 5),
		'bios-release-date': (0, 8),
		'system-manufacturer': (1, 4),
		'system-product-name': (1, 5),
		'system-version': (1, 6),
		'system-serial-number': (1, 7),
		'baseboard-manufacturer': (2, 4),
		'baseboard-product-name': (2, 5),
		'baseboard-version': (2, 6),
		'baseboard-serial-number': (2, 7),
		'chassis-manufacturer': (3, 4),
		'chassis-type': (3, 5),
		'chassis-version': (3, 6),
		'chassis-serial-number': (3, 7),
		'processor-manufacturer': (4, 7),
		'processor-version': (4, 16),
	}

	if os.path.exists('/etc/os-release'):
		with open('/etc/os-release', 'r') as fp:
			for line in fp:
				if line.startswith('PRETTY_NAME='):
					out['os-version'] = line[12:].strip().replace('"', '')

	cpucount = 0
	if os.path.exists('/proc/cpuinfo'):
		with open('/proc/cpuinfo', 'r') as fp:
			for line in fp:
				if re.match('^processor[ \t]*:[ \t]*[0-9]*', line):
					cpucount += 1
		if cpucount > 0:
			out['cpu-count'] = cpucount

	if(not os.path.exists('/dev/mem')):
		if(fatal):
			doError('file does not exist: %s' % '/dev/mem')
		return out
	if(not os.access('/dev/mem', os.R_OK)):
		if(fatal):
			doError('file is not readable: %s' % '/dev/mem')
		return out

	# by default use legacy scan, but try to use EFI first
	memaddr = 0xf0000
	memsize = 0x10000
	for ep in ['/sys/firmware/efi/systab', '/proc/efi/systab']:
		if not os.path.exists(ep) or not os.access(ep, os.R_OK):
			continue
		fp = open(ep, 'r')
		buf = fp.read()
		fp.close()
		i = buf.find('SMBIOS=')
		if i >= 0:
			try:
				memaddr = int(buf[i+7:], 16)
				memsize = 0x20
			except:
				continue

	# read in the memory for scanning
	try:
		fp = open('/dev/mem', 'rb')
		fp.seek(memaddr)
		buf = fp.read(memsize)
	except:
		if(fatal):
			doError('DMI table is unreachable, sorry')
		else:
			return out
	fp.close()

	# search for either an SM table or DMI table
	i = base = length = num = 0
	while(i < memsize):
		if buf[i:i+4] == b'_SM_' and i < memsize - 16:
			length = struct.unpack('H', buf[i+22:i+24])[0]
			base, num = struct.unpack('IH', buf[i+24:i+30])
			break
		elif buf[i:i+5] == b'_DMI_':
			length = struct.unpack('H', buf[i+6:i+8])[0]
			base, num = struct.unpack('IH', buf[i+8:i+14])
			break
		i += 16
	if base == 0 and length == 0 and num == 0:
		if(fatal):
			doError('Neither SMBIOS nor DMI were found')
		else:
			return out

	# read in the SM or DMI table
	try:
		fp = open('/dev/mem', 'rb')
		fp.seek(base)
		buf = fp.read(length)
	except:
		if(fatal):
			doError('DMI table is unreachable, sorry')
		else:
			return out
	fp.close()

	# scan the table for the values we want
	count = i = 0
	while(count < num and i <= len(buf) - 4):
		type, size, handle = struct.unpack('BBH', buf[i:i+4])
		n = i + size
		while n < len(buf) - 1:
			if 0 == struct.unpack('H', buf[n:n+2])[0]:
				break
			n += 1
		data = buf[i+size:n+2].split(b'\0')
		for name in info:
			itype, idxadr = info[name]
			if itype == type:
				idx = struct.unpack('B', buf[i+idxadr:i+idxadr+1])[0]
				if idx > 0 and idx < len(data) - 1:
					s = data[idx-1].decode('utf-8')
					if s.strip() and s.strip().lower() != 'to be filled by o.e.m.':
						out[name] = s
		i = n + 2
		count += 1
	return out

def updateCron(enable=False):
	rootCheck()
	cmd = getExec('crontab')
	if not cmd or not os.path.isdir('/var/spool/cron/crontabs'):
		doError('crontab not found')

	cronline = '@reboot /usr/bin/hwcheck all'
	cronfile = '/var/spool/cron/crontabs/root'
	if not os.path.exists(cronfile):
		if not enable:
			return
		op = open(cronfile, 'w')
		op.write(cronline+'\n')
		op.close()
		return

	fd, tmpfile = tempfile.mkstemp(prefix='crontab', text=True)
	fp = open(cronfile, 'r')
	op = open(tmpfile, 'w')
	for line in fp:
		if '@reboot' in line and 'hwcheck' in line:
			continue
		op.write(line)
	fp.close()
	if enable:
		op.write(cronline+'\n')
	op.close()
	shutil.move(tmpfile, cronfile)

class LogFile:
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
		fd, tmpfile = tempfile.mkstemp(suffix=title, prefix='hwcheck', text=True)
		if title == 'system':
			fp = open(tmpfile, 'w')
			out = sysinfo()
			for name in sorted(out):
				fp.write('%-24s: %s\n' % (name, out[name]))
			fp.close()
		else:
			cmd = datalist[title]['cmd']
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
		for t in sorted(datalist):
			if title != 'all' and t != title:
				continue
			logs = glob.glob('%s/*-%s.log' % (self.varlog, t))
			latest = sorted(logs)[-1] if len(logs) > 0 else ''
			self.runCheckSection(t, latest)

	def logdiff(self, t, show):
		logs = glob.glob('%s/*-%s.log' % (self.varlog, t))
		if len(logs) < 1:
			self.runCheck(t)
			logs = glob.glob('%s/*-%s.log' % (self.varlog, t))
		pprint('--------------------%s--------------------' % t.upper())
		curr = sorted(logs)[-1] if len(logs) > 0 else ''
		last = sorted(logs)[-2] if len(logs) > 1 else ''
		if not curr:
			pprint('NO DATA FOUND')
			return False
		m = re.match('.*\/(?P<dt>[0-9\-]*).*', curr)
		if(m):
			dt = datetime.strptime(m.group('dt'), '%y%m%d-%H%M%S-')
		else:
			pprint('BAD LOG DATA')
			return False
		if show:
			call('cat %s' % curr, shell=True)
		try:
			fp = Popen(['diff', last, curr], stdout=PIPE, stderr=PIPE).stdout
			out = fp.read().decode('ascii', 'ignore').strip()
			fp.close()
		except:
			out = ''
		if last and out:
			pprint('LAST CHANGE: %s' % dt.strftime('%B %d %Y, %I:%M:%S %p'))
			pprint(out)
		return True

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

def rootCheck(fatal=True):
	if(os.access('/sys/power/state', os.W_OK)):
		return True
	if fatal:
		doError('Root access required, please run with sudo')
	return False

def doError(msg):
	pprint('ERROR: %s' % msg)
	sys.exit(1)

if __name__ == '__main__':
	import argparse

	parser = argparse.ArgumentParser()
	parser.add_argument('-show', action='store_true',
		help='Show the data being gathered without writing logs')
	parser.add_argument('-diff', action='store_true',
		help='Show the last known changes')
	parser.add_argument('command', choices=['all', 'system',
		'pci', 'usb', 'disk', 'cronon', 'cronoff', 'help'])
	args = parser.parse_args()

	if args.command == 'help':
		parser.print_help()
		sys.exit(0)
	elif args.command == 'cronon':
		updateCron(True)
		sys.exit(0)
	elif args.command == 'cronoff':
		updateCron(False)
		sys.exit(0)

	rootCheck()
	log = LogFile()
	if args.show or args.diff:
		for t in sorted(datalist):
			if args.command != 'all' and t != args.command:
				continue
			if args.diff:
				log.logdiff(t, args.show)
				continue
			pprint('--------------------%s--------------------' % t.upper())
			sys.stdout.flush()
			if t == 'system':
				out = sysinfo()
				for name in sorted(out):
					pprint('%-24s: %s' % (name, out[name]))
			else:
				call('%s 2>/dev/null' % (datalist[t]['cmd']), shell=True)
		sys.exit(0)

	log.runCheck(args.command)
