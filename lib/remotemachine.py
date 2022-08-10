#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
#
# RemoteMachine library
# Copyright (c) 2020, Intel Corporation.
#
# This program is free software; you can redistribute it and/or modify it
# under the terms and conditions of the GNU General Public License,
# version 2, as published by the Free Software Foundation.
#
# This program is distributed in the hope it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or
# FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License for
# more details.
#
# Authors:
#    Todd Brandt <todd.e.brandt@linux.intel.com>
#
# Description:
#    Class interface for managing a networked linux machine via ssh.

import os
import sys
import re
import time
from subprocess import call, Popen, PIPE
from lib.parallel import AsyncProcess

class RemoteMachine:
	wdev = ''
	wmac = ''
	wip = ''
	wap = ''
	status = False
	def __init__(self, user, host, addr, reset=None, reserve=None, release=None):
		self.user = user
		self.host = host
		self.addr = addr
		self.resetcmd = reset
		self.reservecmd = reserve
		self.releasecmd = release
	def sshcopyid(self, userinput):
		if userinput:
			res = call('ssh-copy-id %s@%s' % (self.user, self.addr), shell=True)
		else:
			res = call('ssh-copy-id -o BatchMode=yes -o ConnectTimeout=5 %s@%s' % (self.user, self.addr), shell=True)
		return res == 0
	def sshkeyworks(self):
		cmd = 'ssh -q -o BatchMode=yes -o ConnectTimeout=5 %s@%s echo -n' % \
			(self.user, self.addr)
		res = call(cmd, shell=True)
		return res == 0
	def checkhost(self, userinput):
		if not self.ping(5):
			return 'offline'
		i = 0
		# handle all the ssh key errors and warnings
		while True:
			h = self.sshcmd('hostname', 10, False).strip()
			if 'Permanently added' in h:
				i += 1
			elif 'Permission denied' in h:
				if userinput:
					self.sshcopyid(userinput)
				else:
					break
				i += 1
			elif 'REMOTE HOST IDENTIFICATION HAS CHANGED' in h:
				if os.environ.get('USER'):
					cmd = 'ssh-keygen -f "/home/%s/.ssh/known_hosts" -R "%s"' % \
						(os.environ.get('USER'), self.addr)
					call(cmd, shell=True)
				i += 1
			else:
				break
			if i > 3:
				break
		if self.host != h:
			if 'refused' in h.lower() or 'denied' in h.lower():
				return 'ssh permission denied'
			else:
				return 'wrong host (actual=%s)' % h
		return ''
	def setup(self):
		print('Enabling password-less access on %s.\n'\
			'I will try to add your id_rsa/id_rsa.pub using ssh-copy-id...' %\
			(self.host))
		if not self.sshcopyid(True):
			return False
		if not self.sshkeyworks():
			print('ERROR: failed to setup ssh key access.')
			return False
		print('SUCCESS: you now have password-less access.\n')
		return True
	def setupordie(self):
		if not self.setup():
			sys.exit(1)
	def sshproc(self, cmd, timeout=60, userinput=False, ping=True):
		if userinput:
			cmdfmt = 'ssh %s@%s -oStrictHostKeyChecking=no "{0}"'
		else:
			cmdfmt = 'nohup ssh -oBatchMode=yes -oStrictHostKeyChecking=no %s@%s "{0}"'
		cmdline = (cmdfmt % (self.user, self.addr)).format(cmd)
		if ping:
			return AsyncProcess(cmdline, timeout, self.addr)
		return AsyncProcess(cmdline, timeout)
	def sshcmd(self, cmd, timeout=60, fatal=False, userinput=False, ping=True):
		ap = self.sshproc(cmd, timeout, userinput, ping)
		out = ap.runcmd()
		if out.startswith('nohup:'):
			tmp = out.split('\n')
			out = '\n'.join(tmp[1:])
		if ap.terminated:
			if fatal:
				print('SSH TIMEOUT: %s' % cmd)
				self.die()
			else:
				return('SSH TIMEOUT: %s' % cmd)
		return out
	def scpfile(self, file, dir):
		res = call('scp %s %s@%s:%s/' % (file, self.user, self.addr, dir), shell=True)
		return res == 0
	def scpfileget(self, file, dir):
		res = call('scp %s@%s:%s %s/' % (self.user, self.addr, file, dir), shell=True)
		return res == 0
	def openshell(self):
		call('ssh -X %s@%s' % (self.user, self.addr), shell=True)
	def sshcmdfancy(self, cmd, timeout, fatal=True):
		ap, out = self.sshproc(cmd, timeout), ''
		for i in range(2):
			out = ap.runcmd()
			if ap.terminated:
				if fatal:
					print('SSH TIMEOUT: %s' % cmd)
					self.die()
				else:
					return('SSH TIMEOUT: %s' % cmd)
			keygen = re.search(r'ssh-keygen -f ".*" -R ".*"', out)
			if keygen:
				call(keygen.group(), shell=True)
				continue
			break
		return out
	def wakeonlan(self):
		if not self.wmac or not self.wip:
			return
		call('wakeonlan -i %s %s' % (self.wip, self.wmac), shell=True)
	def wifisetup(self, wowlan=False):
		out = self.sshcmd('iwconfig', 10)
		for line in out.split('\n'):
			m = re.match('(?P<dev>\S*) .* ESSID:(?P<ess>\S*)', line)
			if not m:
				continue
			self.wdev = m.group('dev')
			if '"' in m.group('ess'):
				self.wap = m.group('ess').strip('"')
			break
		if not self.wdev:
			return ''
		self.sshcmd('sudo nmcli c reload LabWLAN && sudo nmcli c up LabWLAN', 120)
		out = self.sshcmd('ifconfig %s' % self.wdev, 10)
		for line in out.split('\n'):
			m = re.match('.* inet (?P<ip>[0-9\.]*)', line)
			if m:
				self.wip = m.group('ip')
			m = re.match('.* ether (?P<mac>[0-9a-f\:]*)', line)
			if m:
				self.wmac = m.group('mac')
			if self.wip and self.wmac:
				break
		if not self.wmac or not self.wip:
			return ''
		out = ''
		if wowlan:
			out += self.sshcmd('sudo iw phy0 wowlan enable magic-packet disconnect', 30)
			out += self.sshcmd('sudo iw phy0 wowlan show', 30)
		return out
	def bootsetup(self):
		self.sshcmd('sudo systemctl stop otcpl_dut', 30)
		self.sshcmd('sudo systemctl stop apt-daily-upgrade', 30)
		self.sshcmd('sudo systemctl stop apt-daily', 30)
		self.sshcmd('sudo systemctl stop upower', 30)
		self.sshcmd('sudo telemctl stop', 30)
		self.sshcmd('sudo telemctl opt-out', 30)
		self.sshcmd('sudo systemctl stop sleepprobe', 30)
		self.sshcmd('sudo systemctl disable sleepprobe', 30)
		self.sshcmd('sudo systemctl stop powerprobe', 30)
		self.sshcmd('sudo systemctl disable powerprobe', 30)
	def bootclean(self):
		self.sshcmd('sudo systemctl enable sleepprobe', 30)
		self.sshcmd('sudo systemctl enable powerprobe', 30)
		self.sshcmd('sudo telemctl opt-in', 30)
		self.sshcmd('sudo telemctl start', 30)
	def bioscheck(self, wowlan=False):
		print('MACHINE: %s' % self.host)
		out = self.sshcmd('sudo sleepgraph -sysinfo', 10, False)
		bios = dict()
		for line in out.split('\n'):
			for val in ['bios-release-date', 'bios-vendor', 'bios-version']:
				m = re.match(val+' *\: *(?P<val>.*)', line)
				if m:
					bios[val] = m.group('val')
		m, session = 0, Session()
		list = session.query(db.Machine).having(db.Machine.id==self.id).all()
		if len(list) > 0:
			m = list[0]
		for val in ['bios-release-date', 'bios-vendor', 'bios-version']:
			if val in bios:
				print('%-17s : %s' % (val, bios[val]))
				if not m:
					continue
				if val == 'bios-version':
					m.bios_version = bios[val]
				elif val == 'bios-release-date':
					m.bios_config = bios[val]
				elif val == 'bios-vendor':
					m.me_version = bios[val]
		if m:
			session.commit()
		session.close()
	def configure_grub(self):
		out = self.sshcmd('grep GRUB_DEFAULT /etc/default/grub 2>/dev/null', 10).strip()
		if out != 'GRUB_DEFAULT=saved':
			cmd = 'sudo sed -i s/%s/GRUB_DEFAULT=saved/g /etc/default/grub' % out
			out = 'Changing GRUB_DEFAULT to saved\n'
			out += self.sshcmd(cmd, 10)
			out += self.sshcmd('sudo update-grub', 300)
			return out
		return ''
	def grub_reset(self):
		self.sshcmd('sudo rm /boot/grub/grubenv', 30)
		self.sshcmd('sudo systemctl start otcpl_dut', 30)
	def oscheck(self):
		if not self.ping(5):
			return 'offline'
		out = self.sshcmd('ls -d /boot/grub/ 2>/dev/null', 10)
		if '/boot/grub' in out:
			return 'ubuntu'
		else:
			return ''
	def ping(self, count):
		val = os.system('ping -q -c %d %s > /dev/null 2>&1' % (count, self.addr))
		if val != 0:
			return False
		return True
	def install_mcelog(self, proxy=''):
		git = 'git -c http.sslVerify=false clone http://git.kernel.org/pub/scm/utils/cpu/mce/mcelog.git'
		if proxy:
			git = 'http_proxy=%s %s' % (proxy, git)
		cmd = 'cd /tmp ; rm -rf mcelog ; '+ git + \
			' ; cd mcelog ; sudo make install'
		return self.sshcmd(cmd, 100)
	def install_sleepgraph(self, proxy=''):
		git = 'git -c http.sslVerify=false clone -b master http://github.com/intel/pm-graph.git'
		if proxy:
			git = 'http_proxy=%s %s' % (proxy, git)
		cmd = 'cd /tmp ; rm -rf pm-graph ; ' + git + \
			' ; cd pm-graph ; sudo make uninstall ; sudo make install'
		out = self.sshcmd(cmd, 100)
		cfg = '/usr/share/pm-graph/netfix.cfg'
		cmd = 'test ! -f %s && sudo netfix defconfig > %s' % (cfg, cfg)
		self.sshcmd(cmd, 100)
		return out
	def list_kernels(self, fatal=False):
		versions = []
		out = self.sshcmd('sudo grep ,\ with\ Linux /boot/grub/grub.cfg', 5)
		for line in out.split('\n'):
			if not line.strip() or 'menuentry' not in line:
				continue
			m = re.match('.*, with Linux (?P<v>.*)\' --.*', line)
			if not m:
				if fatal:
					return False
				else:
					continue
			versions.append(m.group('v'))
		if fatal:
			return True
		else:
			return versions
	def kernel_index(self, kver):
		versions = self.list_kernels()
		idx = 0
		for v in versions:
			if 'recovery' in v or 'upstart' in v:
				idx += 1
				continue
			if v.split()[0] == kver:
				return idx
			idx += 1
		return -1
	def kernel_version(self):
		for i in range(3):
			version = self.sshcmd('cat /proc/version', 20).strip()
			if version.startswith('Linux'):
				return version.split()[2]
			time.sleep(1)
		return version
	def reset_machine(self):
		if not self.resetcmd:
			return True
		values = {'host': self.host, 'addr': self.addr, 'user': self.user}
		cmd = self.resetcmd.format(**values)
		print('Reset machine: %s' % cmd)
		return call(cmd, shell=True) == 0
	def reserve_machine(self, minutes):
		if not self.reservecmd:
			return True
		values = {'host': self.host, 'addr': self.addr,
			'user': self.user, 'minutes': ('%d' % minutes)}
		cmd = self.reservecmd.format(**values)
		print('Reserve %s for %dmin: %s' % (self.host, minutes, cmd))
		return call(cmd, shell=True) == 0
	def release_machine(self):
		if not self.releasecmd:
			return True
		values = {'host': self.host, 'addr': self.addr, 'user': self.user}
		cmd = self.releasecmd.format(**values)
		print('Release machine: %s' % cmd)
		return call(cmd, shell=True) == 0
	def restart_or_die(self, logdir=''):
		if not self.resetcmd:
			print('Machine is dead: %s' % self.host)
			self.die()
		print('RESTARTING %s...' % self.host)
		i, rebooted = 0, False
		if self.wmac and self.wip:
			self.wakeonlan()
		elif not self.resetcmd:
			print('Machine is dead: %s' % self.host)
			self.die()
		else:
			self.reset_machine()
			rebooted = True
		while not self.ping(3):
			if i >= 30:
				print('Machine is dead: %s' % self.host)
				self.die()
			elif i != 0 and i % 10 == 0:
				print('restarting again...')
				self.reset_machine()
				rebooted = True
			time.sleep(10)
			i += 1
		if not rebooted:
			# wait a few seconds to allow sleepgraph to finish
			print('WAKE ON WLAN pause...')
			if logdir:
				with open('%s/wlan.log' % logdir, 'a') as fp:
					fp.write('WAKE ON LAN EXECUTED\n')
					fp.close()
			time.sleep(10)
			return
		self.bootsetup()
		self.wifisetup(True)
		if logdir:
			log = self.sshcmd('dmesg', 120)
			with open('%s/dmesg.log' % logdir, 'w') as fp:
				fp.write(log)
				fp.close()
	def reboot(self, kver):
		idx = self.kernel_index(kver)
		if idx >= 0:
			self.sshcmd('sudo grub-set-default \'1>%d\'' % idx, 30)
		print('REBOOTING %s...' % self.host)
		print(self.sshcmd('sudo reboot', 30))
	def reboot_or_die(self, kver):
		self.reboot(kver)
		time.sleep(20)
		i = 0
		while not self.ping(3):
			if i >= 15:
				print('Machine failed to come back: %s' % self.host)
				self.die()
			time.sleep(10)
			i += 1
		self.bootsetup()
		self.wifisetup(True)
		print('Machine is back: %s' % self.host)
	def die(self):
		self.release_machine()
		sys.exit(1)
