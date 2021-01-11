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
from subprocess import call, Popen, PIPE
from lib.parallel import AsyncProcess

class RemoteMachine:
	wdev = ''
	wmac = ''
	wip = ''
	wap = ''
	status = False
	def __init__(self, user, host, addr):
		self.user = user
		self.host = host
		self.addr = addr
	def sshcopyid(self):
		res = call('ssh-copy-id %s@%s' % (self.user, self.addr), shell=True)
		return res == 0
	def sshkeyworks(self):
		cmd = 'ssh -q -o BatchMode=yes -o ConnectTimeout=5 %s@%s echo -n' % \
			(self.user, self.addr)
		res = call(cmd, shell=True)
		return res == 0
	def checkhost(self, userinput):
		if not self.ping(5):
			return 'offline'
		# run it twice, first one is to flush out ssh ip change notices
		if not userinput:
			self.sshcmd('hostname', 5, False)
		h = self.sshcmd('hostname', 10, False, userinput).strip()
		if self.host != h:
			if 'refused' in h.lower() or 'denied' in h.lower():
				return 'ssh connect problem'
			else:
				return 'wrong host (actual=%s)' % h
		if userinput and not self.sshkeyworks():
			self.sshcopyid()
		return ''
	def setup(self):
		print('Enabling password-less access on %s.\n'\
			'I will try to add your id_rsa/id_rsa.pub using ssh-copy-id...' %\
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
	def sshproc(self, cmd, timeout=60, userinput=False):
		if userinput:
			cmdfmt = 'ssh %s@%s -oStrictHostKeyChecking=no "{0}"'
		else:
			cmdfmt = 'nohup ssh -oBatchMode=yes -oStrictHostKeyChecking=no %s@%s "{0}"'
		return AsyncProcess((cmdfmt % (self.user, self.addr)).format(cmd), timeout, self.addr)
	def sshcmd(self, cmd, timeout=60, fatal=False, userinput=False):
		ap = self.sshproc(cmd, timeout, userinput)
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
		self.sshcmd('sudo systemctl stop apt-daily', 30)
		self.sshcmd('sudo systemctl stop upower', 30)
	def bioscheck(self, wowlan=False):
		print('MACHINE: %s' % self.name)
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
			' ; cd pm-graph ; sudo make uninstall;  sudo make install'
		return self.sshcmd(cmd, 100)
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
		version = self.sshcmd('cat /proc/version', 20).strip()
		return version.split()[2]
	def restart_machine(self):
		return True
	def restart_or_die(self, ilab, logdir=''):
		print('RESTARTING %s...' % self.name)
		i = 0
		rebooted = False
		if self.wmac and self.wip:
			self.wakeonlan()
		else:
			rebooted = True
			self.restart_machine()
		while not self.ping(3):
			if i >= 30:
				print('Machine is dead: %s' % self.name)
				self.die()
			elif i != 0 and i % 10 == 0:
				print('restarting again...')
				rebooted = True
				self.restart_machine()
			time.sleep(10)
			i += 1
		if not rebooted:
			# wait a few seconds to allow sleepgraph to finish
			print('WAKE ON WLAN pause...')
			time.sleep(10)
		self.bootsetup()
		if logdir:
			log = self.sshcmd('dmesg', 120)
			with open('%s/dmesg.log' % logdir, 'w') as fp:
				fp.write(log)
				fp.close()
			if not rebooted:
				with open('%s/wlan.log' % logdir, 'a') as fp:
					fp.write('WAKE ON LAN EXECUTED\n')
					fp.close()
	def reboot_or_die(self):
		print('REBOOTING %s...' % self.name)
		i = 0
		print(self.sshcmd('sudo reboot', 30))
		time.sleep(20)
		while not self.ping(3):
			if i >= 15:
				print('Machine failed to come back: %s' % self.name)
				self.die()
			time.sleep(10)
			i += 1
		self.bootsetup()
		print('Machine is back: %s' % self.name)
	def die(self):
		sys.exit(1)
