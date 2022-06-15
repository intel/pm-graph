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
	drv = ''
	net = ''
	ip = ''
	def printLine(self, key, val, ind=18):
		fmt = '%-{0}s : %s'.format(ind)
		print(fmt % (key, val))
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
		ret = ''
		self.nmcli_off()
		if not self.check():
			return 'disabled'
		return ret

class USBEthernet(NetDev):
	title = 'USB-ETH'
	pci = ''
	anet = ''
	def __init__(self, device, pciaddr, network=''):
		self.dev = device
		self.pci = pciaddr
		if not self.isValidUSB():
			doError('%s is not the PCI address of a USB host' % self.pci)
		if network:
			self.net = network
		else:
			self.net = self.nmConnectionName()
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
		if self.nmActive():
			self.nmcli_off()
			self.nmcli_command('stop')
#		self.reloadDriver()
		self.nmcli_command('start')
		for i in range(25):
			state = self.nmDeviceState()
			if state != 'unavailable':
				break
			time.sleep(0.1)
		self.nmcli_on()
	def on(self):
		ret = ''
		self.nmcli_on()
		time.sleep(5)
		if self.check():
			return 'enabled'
		self.reset_soft()
		time.sleep(5)
		if self.check():
			return 'softreset'
#		self.reset_hard()
#		time.sleep(10)
#		if self.check():
#			return 'hardreset'
		return ret
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
		print('%s ONLINE' % self.title)
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
	def printStatus(self, args):
		res = self.check()
		if not self.adev:
			self.printLine('Device  "%s"' % self.dev, 'INACTIVE')
		elif self.adev == args.wifidev:
			self.printLine('Device  "%s"' % self.dev, 'ACTIVE')
		else:
			self.printLine('Device  "%s"' % args.wifidev, 'INACTIVE ("%s" active instead)' % self.adev)
		if self.drv:
			stat = 'ACTIVE' if self.activeDriver() else 'INACTIVE'
			self.printLine('Driver  "%s"' % self.drv, stat)
		ssid = self.activeSSID()
		name = ssid if ssid else 'INACTIVE'
		self.printLine('WIFI AP "%s"' % self.dev, name)
		self.anet = self.activeNetwork()
		name = self.anet if self.anet else 'INACTIVE'
		self.printLine('Network "%s"' % self.dev, name)
		if self.networkAddress():
			self.printLine('Connect "%s"' % self.dev, 'ONLINE (%s)' % self.ip)
		else:
			self.printLine('Connect "%s"' % self.dev, 'OFFLINE')
		stat = 'ONLINE' if res else 'OFFLINE'
		print('WIFI %s' % stat)
		return res

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
	parser.add_argument('-wifidev', metavar='device', default='',
		help='The name of the wifi device from iwconfig')
	parser.add_argument('-wifidrv', metavar='driver', default='',
		help='The kernel driver for the system wifi')
	parser.add_argument('-wifinet', metavar='conn', default='',
		help='The name of the connection used by network manager')
	parser.add_argument('-usbdev', metavar='device', default='',
		help='The name of the USB ethernet dongle device')
	parser.add_argument('-usbpci', metavar='address', default='',
		help='The PCI address of the USB bus the dongle is on')
	parser.add_argument('-usbnet', metavar='name', default='',
		help='The name of the connection used by network manager')
	parser.add_argument('-select', metavar='nettype',
		choices=['wifi', 'usbeth', 'both'], default='both',
		help='Select which device(s) to control')
	parser.add_argument('command', choices=['status', 'on',
		'off', 'softreset', 'hardreset', 'help'])
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

	if not args.wifidev and not args.usbdev:
		doError('all commands require a device')
	if args.usbdev and not args.usbpci:
		doError('ethernet requires a pci device address with -usbpci')

	devices = []
	if args.wifidev and args.select in ['wifi', 'both']:
		wifi = Wifi(args.wifidev, args.wifidrv, args.wifinet)
		wifi.verbose = args.verbose
		devices.append(wifi)
	if args.usbdev and args.select in ['usbeth', 'both']:
		eth = USBEthernet(args.usbdev, args.usbpci, args.usbnet)
		eth.verbose = args.verbose
		devices.append(eth)

	status = 1
	for netdev in devices:
		netdev.possible_or_die(args.command)
		if args.command == 'status':
			if netdev.printStatus(args):
				status = 0
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
					print('%s OFFLINE (noaction)' % netdev.title)
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
			res = netdev.check()
			netdev.reset_soft()
			time.sleep(5)
			res = netdev.check()
			stat = 'SUCCESS' if res else 'FAILED'
			print('%s SOFT RESET %s' % (netdev.title, stat))
		elif args.command == 'hardreset':
			netdev.check()
			netdev.reset_hard()
			time.sleep(10)
			res = netdev.check()
			stat = 'SUCCESS' if res else 'FAILED'
			print('%s HARD RESET %s' % (netdev.title, stat))
	if args.command == 'status':
		sys.exit(status)
