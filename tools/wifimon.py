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

class NetDev:
	valid = True
	verbose = True
	dev = ''
	net = ''
	drv = ''
	def vprint(self, msg):
		if not self.verbose:
			return
		t = datetime.now().strftime('%y%m%d-%H%M%S')
		print('[%s] %s' % (t, msg))
		sys.stdout.flush()
	def runQuiet(self, cmdargs):
		try:
			fp = Popen(cmdargs, stdout=PIPE, stderr=PIPE).stderr
			out = fp.read().decode('ascii', 'ignore').strip()
			fp.close()
		except:
			return 'ERROR'
		return out
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
				self.net = m.group('addr').split('/')[0]
				return True
		return False

class USBEthernet(NetDev):
	title = 'USB ETHERNET'
	pci = ''
	def __init__(self, device, pciaddr):
		self.dev = device
		self.pci = pciaddr
		if not self.isValidUSB():
			doError('%s is not the PCI address of a USB host' % self.pci)
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
		return True
	def printStatus(self, args):
		if self.isDeviceActive():
			printLine('Device  "%s"' % self.dev, 'ACTIVE')
		else:
			printLine('Device  "%s"' % self.dev, 'INACTIVE')
			return False
		if self.networkAddress():
			printLine('Network "%s"' % self.dev, 'ONLINE (%s)' % self.net)
		else:
			printLine('Network "%s"' % self.dev, 'OFFLINE')
			return False
		return True

class Wifi(NetDev):
	title = 'WIFI'
	adev = ''
	anet = ''
	def __init__(self, device, driver='', network=''):
		self.dev = device
		self.net = network
		if driver:
			self.drv = driver
		else:
			self.drv = self.wifiDriver()
	def wifiDriver(self):
		try:
			file = '/sys/class/net/%s/device/uevent' % self.dev
			info = open(file, 'r').read().strip()
		except:
			return ''
		for prop in info.split('\n'):
			if prop.startswith('DRIVER='):
				return prop.split('=')[-1]
		return ''
	def activeDevice(self):
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
		return ''
	def activeNetwork(self):
		try:
			fp = Popen(['nmcli', 'c', 'show', '--active'], stdout=PIPE, stderr=PIPE).stdout
			out = fp.read().decode('ascii', 'ignore').strip()
			fp.close()
		except:
			return ''
		for line in out.split('\n'):
			val = line.split()
			if 'NAME' in line or len(val) != 4:
				continue
			if val[-1] == self.dev:
				return val[0]
		return ''
	def nmActive(self):
		out = self.runQuiet(['nmcli', 'c', 'show'])
		if 'error' in out.lower():
			return False
		return True
	def deviceState(self):
		try:
			fp = Popen(['nmcli', 'd'], stdout=PIPE, stderr=PIPE).stdout
			out = fp.read().decode('ascii', 'ignore').strip()
			fp.close()
		except:
			return ''
		for line in out.split('\n'):
			val = line.split()
			if len(val) == 4 and val[0] == self.dev:
				return val[2]
		return ''
	def check(self):
		self.adev = self.activeDevice()
		if self.dev != self.adev:
			return False
		if self.net:
			self.anet = self.activeNetwork()
			if self.net != self.anet:
				return False
		return True
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
	def nmcli_on(self):
		if not self.net or not self.nmActive():
			return False
		if not self.activeDriver():
			self.driver_on()
			time.sleep(1)
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
	def reset_soft(self):
		self.nmcli_off()
		self.nmcli_command('restart')
		for i in range(25):
			state = self.deviceState()
			if state != 'unavailable':
				break
			time.sleep(0.1)
		self.nmcli_on()
	def reset_hard(self):
		if self.nmActive():
			self.nmcli_off()
			self.nmcli_command('stop')
		self.reloadDriver()
		self.nmcli_command('start')
		for i in range(25):
			state = self.deviceState()
			if state != 'unavailable':
				break
			time.sleep(0.1)
		self.nmcli_on()
	def on(self):
		ret = ''
		if self.drv and not self.activeDriver():
			self.driver_on()
		self.nmcli_on()
		time.sleep(5)
		if self.check():
			return 'enabled'
		self.reset_soft()
		time.sleep(5)
		if self.check():
			return 'softreset'
		self.reset_hard()
		time.sleep(10)
		if self.check():
			return 'hardreset'
		return ret
	def off(self):
		ret = ''
		self.nmcli_off()
		if not self.check():
			return 'disabled'
		return ret
	def poll(self, retries=10):
		i = 0
		while True:
			if self.check():
				i = 0
				time.sleep(10)
				continue
			else:
				self.on()
				if (i + 1) % (retries + 1) == 0:
					break
			i += 1
		return i
	def printStatus(self, args):
		ret = self.check()
		if not self.adev:
			printLine('Device "%s"' % self.dev, 'INACTIVE')
		elif self.adev == args.dev:
			printLine('Device "%s"' % self.dev, 'ACTIVE')
		else:
			printLine('Device "%s"' % args.dev, 'INACTIVE ("%s" active instead)' % self.adev)
		if self.drv:
			if self.activeDriver():
				printLine('Driver "%s"' % self.drv, 'ACTIVE')
			else:
				printLine('Driver "%s"' % self.drv, 'INACTIVE')
		ssid = self.activeSSID()
		if ssid:
			printLine('WIFI AP "%s"' % ssid, 'ACTIVE')
		else:
			printLine('WIFI AP', 'INACTIVE')
		if not self.anet:
			text = 'Network "%s"' % args.network if args.network else 'Network (any)'
			printLine(text, 'INACTIVE')
		elif self.anet == args.network:
			printLine('Network "%s"' % args.network, 'ACTIVE')
		else:
			if args.network:
				printLine('Network "%s"' % args.network, 'INACTIVE ("%s" active instead)' % self.anet)
			else:
				printLine('Network "%s"' % self.anet, 'ACTIVE')
		if ret:
			print('WIFI ONLINE')
		else:
			print('WIFI OFFLINE')
		return ret

def printLine(key, val):
	print('%-20s : %s' % (key, val))

def configFile(file):
	if not file:
		file = 'wifimon.cfg'
	dir = os.path.dirname(os.path.realpath(__file__))
	if op.exists(file):
		return file
	elif op.exists(dir+'/'+file):
		return dir+'/'+file
	elif op.exists(dir+'/config/'+file):
		return dir+'/config/'+file
	return ''

def doError(msg):
	print('ERROR: %s\n' % msg)
	sys.exit(1)

if __name__ == '__main__':
	import argparse

	parser = argparse.ArgumentParser()
	parser.add_argument('-verbose', action='store_true',
		help='print extra info to show what the tool is doing')
	parser.add_argument('-noconfig', action='store_true',
		help='skip loading the config, otherwise the default is used')
	parser.add_argument('-config', metavar='file', default='',
		help='use config file to fill out the remaining args')
	parser.add_argument('-dev', metavar='device', default='',
		help='The name of the wifi device from iwconfig')
	parser.add_argument('-driver', metavar='driver', default='',
		help='The kernel driver for the system wifi')
	parser.add_argument('-network', metavar='conn', default='',
		help='The name of the connection used by network manager')
	parser.add_argument('-usbdev', metavar='device', default='',
		help='The name of the USB ethernet dongle device')
	parser.add_argument('-usbpci', metavar='address', default='',
		help='The PCI address of the USB bus the dongle is on')
	parser.add_argument('command', choices=['status', 'on',
		'off', 'softreset', 'hardreset', 'monitor', 'help'])
	args = parser.parse_args()

	if args.command == 'help':
		parser.print_help()
		sys.exit(0)

	if not args.noconfig:
		cfg = configFile(args.config)
		if args.config and not cfg:
			doError('config file not found (%s)' % args.config)
		if cfg:
			err = args_from_config(parser, args, cfg, 'setup')
			if err:
				doError(err)

	if not args.dev and not args.usbdev:
		doError('all commands require a device')
	if args.usbdev and not args.usbpci:
		doError('ethernet requires a pci device address with -usbpci')

	devices = []
	if args.dev:
		wifi = Wifi(args.dev, args.driver, args.network)
		wifi.verbose = args.verbose
		devices.append(wifi)
	if args.usbdev:
		eth = USBEthernet(args.usbdev, args.usbpci)
		eth.verbose = args.verbose
		devices.append(eth)

	status = False
	for netdev in devices:
		if args.command == 'status':
			if netdev.printStatus(args):
				status = True
		elif args.command in ['on', 'off']:
			res = netdev.check()
			if args.command == 'on':
				if res:
					print('%s ONLINE (noaction)' % netdev.title)
					status = True
					continue
				res = netdev.on()
			elif args.command == 'off':
				if not res:
					print('%s OFFLINE (noaction) % netdev.title')
					status = True
					continue
				res = netdev.off()
			str = {'on': ['ONLINE', 'ON FAILED'],'off': ['OFFLINE', 'OFF FAILED']}
			out = str[args.command][0] if res else str[args.command][1]
			if res:
				print('%s %s (%s)' % (netdev.title, out, res))
			else:
				print('%s %s' % (netdev.title, out))
		elif args.command == 'softreset':
			if not args.network:
				doError('softreset reqires a network')
			res = netdev.check()
			netdev.reset_soft()
			time.sleep(5)
			res = netdev.check()
			if res:
				print('%s SOFT RESET SUCCESS' % netdev.title)
			else:
				print('%s SOFT RESET FAILED' % netdev.title)
		elif args.command == 'hardreset':
			netdev.check()
			if not args.network and not netdev.drv:
				doError('hardreset needs a driver and/or network')
			netdev.reset_hard()
			time.sleep(10)
			res = netdev.check()
			if res:
				print('%s HARD RESET SUCCESS' % netdev.title)
			else:
				print('%s HARD RESET FAILED' % netdev.title)
		elif args.command == 'monitor':
			netdev.check()
			if not args.network and not netdev.drv:
				doError('monitor needs a driver and/or network')
			netdev.poll()
	if args.command == 'status':
		if status:
			sys.exit(0)
		else:
			sys.exit(1)
