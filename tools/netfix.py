#!/usr/bin/env python3

import os
import os.path as op
import sys
sys.path.insert(1, 'lib')
import re
import time
from datetime import datetime
from subprocess import call, Popen, PIPE
from argconfig import args_from_config

default_config_file = '/usr/share/pm-graph/netfix.cfg'

class NetDev:
	valid = True
	verbose = True
	dev = ''
	drv = ''
	net = ''
	ip = ''
	paddr = ''
	def printLine(self, key, val, ind=18):
		fmt = '%-{0}s : %s'.format(ind)
		print(fmt % (key, val))
	def vprint(self, msg):
		if not self.verbose:
			return
		t = datetime.now().strftime('%y%m%d-%H%M%S')
		print('[%s] %s' % (t, msg))
		sys.stdout.flush()
	def ping(self, count=1):
		if not self.paddr:
			return True
		val = os.system('ping -I %s -q -c %d %s > /dev/null 2>&1' % \
			(self.dev, count, self.paddr))
		if val != 0:
			return False
		return True
	def runQuiet(self, cmdargs):
		try:
			fp = Popen(cmdargs, stdout=PIPE, stderr=PIPE).stderr
			out = fp.read().decode('ascii', 'ignore').strip()
			fp.close()
		except:
			return 'ERROR'
		return out
	def runStdout(self, cmdargs):
		try:
			fp = Popen(cmdargs, stdout=PIPE, stderr=PIPE).stdout
			out = fp.read().decode('ascii', 'ignore').strip()
			fp.close()
		except:
			return 'ERROR'
		return out
	def setVal(self, val, file):
		try:
			fp = open(file, 'wb', 0)
			fp.write(val.encode())
			fp.flush()
			fp.close()
		except:
			return False
		return True
	def devicePCI(self, usbonly=True):
		dir = '/sys/class/net/%s' % self.dev
		if not op.exists(dir) or not op.islink(dir):
			return ''
		link = os.readlink(dir)
		if usbonly and 'usb' not in link:
			return ''
		m = re.match('.*/devices/pci[0-9,a-z:\.]*/(?P<addr>[0-9,a-z:\.]*)/.*', link)
		if not m:
			return ''
		return m.group('addr')
	def deviceDriver(self):
		try:
			file = '/sys/class/net/%s/device/uevent' % self.dev
			info = open(file, 'r').read().strip()
		except:
			return ''
		for prop in info.split('\n'):
			if prop.startswith('DRIVER='):
				return prop.split('=')[-1]
		return ''
	@staticmethod
	def activeNetworkbyType(type):
		try:
			fp = Popen(['nmcli', '-f', 'TYPE,DEVICE,NAME', 'c', 'show', '--active'],
				stdout=PIPE, stderr=PIPE).stdout
			out = fp.read().decode('ascii', 'ignore').strip()
			fp.close()
		except:
			return ('', '')
		for line in out.split('\n'):
			if 'TYPE' in line:
				continue
			m = re.match('%s\s+(?P<dev>\S*)\s+(?P<name>.*)' % type, line)
			if m:
				return (m.group('dev'), m.group('name').strip())
		return ('', '')
	def activeNetwork(self):
		try:
			fp = Popen(['nmcli', '-f', 'DEVICE,NAME', 'c', 'show', '--active'],
				stdout=PIPE, stderr=PIPE).stdout
			out = fp.read().decode('ascii', 'ignore').strip()
			fp.close()
		except:
			return ''
		for line in out.split('\n'):
			m = re.match('%s\s+(?P<name>.*)' % self.dev, line)
			if m:
				return m.group('name').strip()
		return ''
	def nmActive(self):
		out = self.runQuiet(['nmcli', 'c', 'show'])
		if 'error' in out.lower():
			return False
		return True
	def nmDeviceState(self):
		try:
			fp = Popen(['nmcli', '-f', 'DEVICE,STATE', 'd'],
				stdout=PIPE, stderr=PIPE).stdout
			out = fp.read().decode('ascii', 'ignore').strip()
			fp.close()
		except:
			return ''
		for line in out.split('\n'):
			m = re.match('%s\s+(?P<stat>.*)' % self.dev, line)
			if m:
				return m.group('stat').strip()
		return ''
	def nmcli_on(self):
		if not self.net or not self.nmActive():
			return False
		self.vprint('network "%s" on' % self.net)
		ret = self.runQuiet(['sudo', 'nmcli', 'c', 'up', self.net])
		return ret
	def nmcli_off(self):
		if not self.net or not self.nmActive():
			return False
		self.vprint('network "%s" off' % self.net)
		ret = self.runQuiet(['sudo', 'nmcli', 'c', 'down', self.net])
		return ret
	def nmcli_command(self, cmd):
		if not self.net:
			return False
		self.vprint('NetworkManager %s' % cmd)
		ret = self.runQuiet(['sudo', 'systemctl', cmd, 'NetworkManager'])
		return ret
	def isDeviceActive(self):
		try:
			fp = Popen(['ip', '-o', 'link'], stdout=PIPE, stderr=PIPE).stdout
			out = fp.read().decode('ascii', 'ignore').strip()
			fp.close()
		except:
			return False
		for line in out.split('\n'):
			tmp = re.split(':\s*', line)
			if len(tmp) > 1 and tmp[1] == self.dev:
				return True
		return False
	def networkAddress(self):
		try:
			fp = Popen(['ip', '-o', 'addr'], stdout=PIPE, stderr=PIPE).stdout
			out = fp.read().decode('ascii', 'ignore').strip()
			fp.close()
		except:
			return False
		for line in out.split('\n'):
			m = re.match('[0-9]*\:\s* (?P<dev>\S*)\s*inet\s+(?P<addr>\S*)\s.*', line)
			if m and m.group('dev') == self.dev:
				self.ip = m.group('addr').split('/')[0]
				return True
		return False
	def nmConnectionName(self):
		try:
			fp = Popen(['nmcli', '-f', 'DEVICE,NAME', 'c', 'show'],
				stdout=PIPE, stderr=PIPE).stdout
			out = fp.read().decode('ascii', 'ignore').strip()
			fp.close()
		except:
			return ''
		for line in out.split('\n'):
			m = re.match('%s\s+(?P<name>.*)' % self.dev, line)
			if m:
				return m.group('name').strip()
		return ''
	def off(self):
		self.nmcli_off()
		if not self.check():
			return ('disabled', 'offline')
		return ('disabled', 'online')

class Wired(NetDev):
	title = 'WIRED'
	pci = ''
	anet = ''
	bind = ''
	unbind = ''
	def __init__(self, device, pingaddr='', pciaddr='', network=''):
		self.dev = device
		self.pci = pciaddr
		if pciaddr and not self.isValidUSB():
			doError('%s is not the PCI address of a USB host' % self.pci)
		if pciaddr and not self.usbBindUnbind():
			doError('could not find the USB bind/unbind file %s' % self.pci)
		if pingaddr:
			self.paddr = pingaddr
		if network:
			self.net = network
		else:
			self.net = self.nmConnectionName()
	def usbBindUnbind(self):
		if not self.pci:
			return False
		usbdir = ''
		for dirname, dirnames, filenames in os.walk('/sys/devices'):
			if dirname.endswith('/'+self.pci) and 'driver' in dirnames:
				usbdir = op.join(dirname, 'driver')
				if op.islink(usbdir):
					link = os.readlink(usbdir)
					usbdir = op.abspath(op.join(dirname, link))
				break
		if usbdir:
			self.bind = op.join(usbdir, 'bind')
			self.unbind = op.join(usbdir, 'unbind')
			if not op.exists(self.bind) or not op.exists(self.unbind):
				self.bind = self.unbind = ''
				return False
			return True
		return False
	def isValidUSB(self):
		if not self.pci:
			return False
		try:
			fp = Popen(['lspci', '-D'], stdout=PIPE, stderr=PIPE).stdout
			out = fp.read().decode('ascii', 'ignore').strip()
			fp.close()
		except:
			return False
		for line in out.split('\n'):
			if line.startswith(self.pci) and 'USB' in line:
				return True
		return False
	def check(self):
		if not self.isDeviceActive():
			return False
		if not self.networkAddress():
			return False
		if self.paddr and not self.ping():
			return False
		return True
	def possible_or_die(self, cmd):
		if cmd == 'softreset' and not self.net:
			doError('softreset reqires a network')
		elif cmd == 'hardreset' and not self.pci:
			doError('hardreset needs a pci address for usb ethernet')
	def reset_soft(self):
		self.nmcli_off()
		self.nmcli_command('restart')
		for i in range(25):
			state = self.nmDeviceState()
			if state != 'unavailable':
				break
			time.sleep(0.1)
		self.nmcli_on()
	def reset_hard(self):
		if not self.pci:
			return
		if self.nmActive():
			self.nmcli_off()
			self.nmcli_command('stop')
		self.setVal(self.pci, self.unbind)
		self.setVal(self.pci, self.bind)
		self.nmcli_command('start')
		for i in range(30):
			state = self.nmDeviceState()
			if state != 'unavailable':
				break
			time.sleep(0.1)
		self.nmcli_on()
	def on(self):
		self.nmcli_on()
		time.sleep(5)
		if self.check():
			return ('enabled', 'online')
		self.reset_soft()
		time.sleep(5)
		if self.check():
			return ('softreset', 'online')
		if self.pci:
			self.reset_hard()
			time.sleep(10)
			if self.check():
				return ('hardreset', 'online')
			return ('hardreset', 'offline')
		return ('softreset', 'offline')
	def printStatus(self, args):
		if self.isDeviceActive():
			self.printLine('Device  "%s"' % self.dev, 'ACTIVE')
		else:
			self.printLine('Device  "%s"' % self.dev, 'INACTIVE')
			print('%s OFFLINE' % self.title)
			return False
		self.anet = self.activeNetwork()
		name = self.anet if self.anet else 'INACTIVE'
		self.printLine('Network "%s"' % self.dev, name)
		if self.networkAddress():
			self.printLine('Connect "%s"' % self.dev, 'ONLINE (%s)' % self.ip)
		else:
			self.printLine('Connect "%s"' % self.dev, 'OFFLINE')
			print('%s OFFLINE' % self.title)
			return False
		stat = 'ONLINE' if self.check() else 'OFFLINE'
		print('%s %s' % (self.title, stat))
		return True
	def wakeOnLan(self, val):
		out = self.runQuiet(['sudo', 'ethtool', '-s', self.dev, 'wol', val])
		if 'ERROR' in out:
			return 'error'
		out = self.runStdout(['sudo', 'ethtool', self.dev])
		for line in out.split('\n'):
			m = re.match('\s*Wake\-on\: (?P<v>\S*).*', line)
			if m:
				return m.group('v')
		return 'unknown'

class Wifi(NetDev):
	title = 'WIFI'
	adev = ''
	anet = ''
	def __init__(self, device, pingaddr='', driver='', network=''):
		self.dev = device
		self.net = network
		if pingaddr:
			self.paddr = pingaddr
		if driver:
			self.drv = driver
		else:
			self.drv = self.deviceDriver()
	@staticmethod
	def activeDevice():
		try:
			w = open('/proc/net/wireless', 'r').read().strip()
		except:
			return ''
		for line in reversed(w.split('\n')):
			m = re.match(' *(?P<dev>.*): (?P<stat>[0-9a-f]*) .*', line)
			if m:
				return m.group('dev')
		return ''
	def activeDriver(self):
		if not self.drv:
			return False
		try:
			fp = Popen(['lsmod'], stdout=PIPE, stderr=PIPE).stdout
			out = fp.read().decode('ascii', 'ignore').strip()
			fp.close()
		except:
			return False
		for line in out.split('\n'):
			if line.startswith(self.drv):
				return True
		return False
	def activeSSID(self):
		try:
			fp = Popen(['iwconfig'], stdout=PIPE, stderr=PIPE).stdout
			out = fp.read().decode('ascii', 'ignore').strip()
			fp.close()
		except:
			return ''
		for line in out.split('\n'):
			m = re.match('\s*(?P<dev>\S*)\s*.*ESSID:"(?P<net>\S*)".*', line)
			if m and (m.group('dev') == self.dev):
				return m.group('net')
		return 'INACTIVE'
	def driver_on(self):
		if not self.drv:
			return False
		self.vprint('driver "%s" on' % self.drv)
		ret = self.runQuiet(['sudo', 'modprobe', self.drv])
		return ret
	def driver_off(self):
		if not self.drv:
			return False
		self.vprint('driver "%s" off' % self.drv)
		ret = self.runQuiet(['sudo', 'modprobe', '-r', self.drv])
		return ret
	def reloadDriver(self):
		if not self.drv:
			return False
		if self.activeDriver():
			self.driver_off()
			time.sleep(1)
		self.driver_on()
		time.sleep(1)
		return self.activeDriver()
	def check(self):
		self.adev = self.activeDevice()
		if self.dev != self.adev:
			return False
		if self.net:
			self.anet = self.activeNetwork()
			if self.net != self.anet:
				return False
		if self.paddr and not self.ping():
			return False
		return True
	def possible_or_die(self, cmd):
		if cmd == 'softreset' and not self.net:
			doError('softreset reqires a network')
		elif cmd == 'hardreset' and not self.net and not self.drv:
			doError('hardreset needs a driver and/or network')
	def reset_soft(self):
		self.nmcli_off()
		self.nmcli_command('restart')
		for i in range(25):
			state = self.nmDeviceState()
			if state != 'unavailable':
				break
			time.sleep(0.1)
		if not self.activeDriver():
			self.driver_on()
			time.sleep(1)
		self.nmcli_on()
	def reset_hard(self):
		if self.nmActive():
			self.nmcli_off()
			self.nmcli_command('stop')
		self.reloadDriver()
		self.nmcli_command('start')
		for i in range(25):
			state = self.nmDeviceState()
			if state != 'unavailable':
				break
			time.sleep(0.1)
		if not self.activeDriver():
			self.driver_on()
			time.sleep(1)
		self.nmcli_on()
	def on(self):
		if self.drv and not self.activeDriver():
			self.driver_on()
		self.nmcli_on()
		time.sleep(5)
		if self.check():
			return ('enabled', 'online')
		self.reset_soft()
		time.sleep(5)
		if self.check():
			return ('softreset', 'online')
		if self.drv:
			self.reset_hard()
			time.sleep(10)
			if self.check():
				return ('hardreset', 'online')
			return ('hardreset', 'offline')
		return ('softreset', 'offline')
	def printStatus(self, args):
		res = self.check()
		if not self.adev:
			self.printLine('Device  "%s"' % self.dev, 'INACTIVE')
		elif self.adev == args.wifidev:
			self.printLine('Device  "%s"' % self.dev, 'ACTIVE')
		else:
			self.printLine('Device  "%s"' % args.wifidev,
				'INACTIVE ("%s" active instead)' % self.adev)
		if self.drv:
			stat = 'ACTIVE' if self.activeDriver() else 'INACTIVE'
			self.printLine('Driver  "%s"' % self.drv, stat)
		ssid = self.activeSSID()
		if ssid:
			self.printLine('WIFI AP "%s"' % self.dev, ssid)
		self.anet = self.activeNetwork()
		if self.net and self.anet and self.net != self.anet:
			self.printLine('Network "%s"' % self.dev,
				'%s (should be "%s")' % (self.anet, self.net))
		else:
			name = self.anet if self.anet else 'INACTIVE'
			self.printLine('Network "%s"' % self.dev, name)
		if self.networkAddress():
			self.printLine('Connect "%s"' % self.dev, 'ONLINE (%s)' % self.ip)
		else:
			self.printLine('Connect "%s"' % self.dev, 'OFFLINE')
		stat = 'ONLINE' if res else 'OFFLINE'
		print('WIFI %s' % stat)
		return res

def generateConfig():

	# get the wifi device config

	wifidev = Wifi.activeDevice()
	if wifidev:
		wifi = Wifi(wifidev)
		wifidrv = wifi.deviceDriver()
		wifinet = wifi.activeNetwork()
	else:
		wifidrv = wifinet = ''

	print('#\n# Network Fixer Tool Config\n#\n')
	print('[setup]\n')
	print('# Wifi device name')
	if wifidev:
		print('wifidev: %s' % wifidev)
	else:
		print('# wifidev:')
	print('\n# Kernel module for the wifi device')
	if wifidrv:
		print('wifidrv: %s' % wifidrv)
	else:
		print('# wifidrv:')
	print('\n# network name as defined by NetworkManager')
	if wifinet:
		print('wifinet: %s' % wifinet)
	else:
		print('# wifinet:')

	# get the wired device config

	ethdev, ethnet = Wired.activeNetworkbyType('ethernet')
	if not ethdev or not ethnet:
		return
	print('\n# Ethernet device name')
	if ethdev:
		print('ethdev: %s' % ethdev)
	else:
		print('# ethdev:')
	print('\n# NetworkManager network name for ETH device')
	if ethnet:
		print('ethnet: %s' % ethnet)
	else:
		print('# ethnet:')
	eth = Wired(ethdev, '', '', ethnet)
	eth.pci = eth.devicePCI()
	if eth.isValidUSB() and eth.usbBindUnbind():
		print('\n# USB Ethernet pci bus address (for dongles)')
		print('ethusb: %s' % eth.pci)
	print('\n# remote address to ping to check the connection')
	print('# pingaddr:')

def doError(msg):
	print('ERROR: %s\n' % msg)
	sys.exit(1)

if __name__ == '__main__':
	import argparse

	parser = argparse.ArgumentParser()
	parser.add_argument('-verbose', '-v', action='store_true',
		help='print extra info to show what the tool is doing')
	parser.add_argument('-noconfig', '-n', action='store_true',
		help='skip loading the config, otherwise the default is used')
	parser.add_argument('-config', '-c', metavar='txt', default='',
		help='use config file to fill out the remaining args')
	parser.add_argument('-wifidev', metavar='device', default='',
		help='The name of the wifi device from iwconfig')
	parser.add_argument('-wifinet', metavar='conn', default='',
		help='The name of the connection used by network manager')
	parser.add_argument('-wifidrv', metavar='driver', default='',
		help='The kernel driver for the system wifi')
	parser.add_argument('-ethdev', metavar='device', default='',
		help='The name of the wired ethernet device')
	parser.add_argument('-ethnet', metavar='conn', default='',
		help='The name of the connection used by network manager')
	parser.add_argument('-ethusb', metavar='address', default='',
		help='The PCI address of the USB bus the dongle is on')
	parser.add_argument('-select', '-s', metavar='net',
		choices=['wifi', 'wired', 'both'], default='both',
		help='Select which device(s) to control (wifi|wired|both)')
	parser.add_argument('-pingaddr', metavar='address', default='',
		help='Remote address to ping to check the connection')
	parser.add_argument('-rebootonfail', '-r', action='store_true',
		help='if command on/softreset/hardreset fails, reboot the system')
	parser.add_argument('-timestamp', '-t', action='store_true',
		help='prefix output with a timestamp')
	parser.add_argument('command', choices=['status', 'on', 'woloff',
		'off', 'softreset', 'hardreset', 'defconfig', 'help'])
	args = parser.parse_args()

	if args.command == 'help':
		parser.print_help()
		sys.exit(0)
	elif args.command == 'defconfig':
		generateConfig()
		sys.exit(0)

	if not args.noconfig:
		if not args.config and op.exists(default_config_file):
			args.config = default_config_file
		if args.config:
			err = args_from_config(parser, args, args.config, 'setup')
			if err:
				doError(err)

	if not args.wifidev and not args.ethdev:
		print('ERROR: no device(s) configured', file=sys.stderr)
		sys.exit(1)

	devices = []
	if args.wifidev and args.select in ['wifi', 'both']:
		wifi = Wifi(args.wifidev, args.pingaddr, args.wifidrv, args.wifinet)
		wifi.verbose = args.verbose
		devices.append(wifi)
	if args.ethdev and args.select in ['wired', 'both']:
		eth = Wired(args.ethdev, args.pingaddr, args.ethusb, args.ethnet)
		eth.verbose = args.verbose
		devices.append(eth)

	status = True
	output = dict()
	for netdev in devices:
		netdev.possible_or_die(args.command)
		out = output[netdev.title] = {'dev': netdev.dev}
		if args.command == 'status':
			if not netdev.printStatus(args):
				status = False
		elif args.command in ['on', 'off']:
			res = netdev.check()
			if args.command == 'on':
				if res:
					out['act'], out['net'] = 'noaction', 'online'
					continue
				out['act'], out['net'] = netdev.on()
				if out['net'] == 'offline':
					status = False
			elif args.command == 'off':
				if not res:
					out['act'], out['net'] = 'noaction', 'offline'
					continue
				out['act'], out['net'] = netdev.off()
				if out['net'] == 'online':
					status = False
		elif args.command == 'softreset':
			out['act'] = args.command
			res = netdev.check()
			netdev.reset_soft()
			time.sleep(5)
			res = netdev.check()
			if not res:
				status = False
			out['net'] = 'online' if res else 'offline'
		elif args.command == 'hardreset':
			out['act'] = args.command
			netdev.check()
			netdev.reset_hard()
			time.sleep(10)
			res = netdev.check()
			if not res:
				status = False
			out['net'] = 'online' if res else 'offline'
		elif args.command == 'woloff':
			out['act'] = args.command
			if netdev.title != 'WIRED':
				out['net'] = 'unsupported'
				continue
			out['net']= netdev.wakeOnLan('d')
	if args.command != 'status' and len(output) > 0:
		outtext = []
		for t in output:
			o = output[t]
			s = '%s %s %s %s' % (t, o['dev'], o['net'].upper(), o['act'])
			outtext.append(s)
		out = ', '.join(outtext)
		if args.timestamp:
			tm = datetime.now().strftime('%y/%m/%d-%H:%M:%S')
			print('%s: %s' % (tm, out))
		else:
			print(out)

	if not status and args.rebootonfail and \
		args.command in ['on', 'softreset', 'hardreset']:
		os.system('sudo reboot')
	sys.exit(0 if status else 1)
