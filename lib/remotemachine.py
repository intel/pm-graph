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
from lib.parallel import AsyncProcess, AsyncCall

class RemoteMachine:
	edev = ''
	emac = ''
	eip = ''
	wdev = ''
	wmac = ''
	wip = ''
	status = False
	grubfile = '/etc/default/grub'
	grubfileorig = '/etc/default/grub.stresstest.orig'
	grubfilemine = '/etc/default/grub.stresstest'
	def __init__(self, user, host, addr, reset=None, on=None, off=None,
		dstart=None, dstop=None, reserve=None, release=None):
		self.user = user
		self.host = host
		self.addr = addr
		self.resetcmd = reset
		self.oncmd = on
		self.offcmd = off
		self.dstartcmd = dstart
		self.dstopcmd = dstop
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
			h = self.sshcmd('hostname', 60, False).strip()
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
		if self.emac and self.eip:
			call('wakeonlan -i %s %s' % (self.eip, self.emac), shell=True)
		if self.wmac and self.wip:
			call('wakeonlan -i %s %s' % (self.wip, self.wmac), shell=True)
	def wakeonlan_delay(self, delay):
		time.sleep(delay)
		i = 0
		while not self.ping(3):
			if i > 20:
				return
			self.wakeonlan()
			time.sleep(5)
			i += 1
	def wolwake(self, delay=15):
		obj = AsyncCall(self.wakeonlan_delay, [delay])
		obj.run()
	def wifisetup(self, wowlan=False):
		ret, conns, dev = '', dict(), ''
		out = self.sshcmd('ifconfig', 60)
		for line in out.split('\n'):
			m = re.match(r'^(?P<dev>[\S+]*)\: flags.*', line)
			if m:
				dev = m.group('dev')
				conns[dev] = {'mac': '', 'ip': ''}
			m = re.match(r'.* inet (?P<ip>[0-9\.]*)', line)
			if m and dev:
				conns[dev]['ip'] = m.group('ip')
			m = re.match(r'.* ether (?P<mac>[0-9a-f\:]*)', line)
			if m and dev:
				conns[dev]['mac'] = m.group('mac')
		for dev in conns:
			ip, mac = conns[dev]['ip'], conns[dev]['mac']
			if not ip or not mac:
				continue
			if dev[0] == 'e':
				self.edev = dev
				self.emac = mac
				self.eip = ip
				ret += 'e'
				print('ETH DEVICE NAME: %s' % self.edev)
				print('ETH MAC ADDRESS: %s' % self.emac)
				print('ETH IP ADDRESS : %s' % self.eip)
			elif dev[0] == 'w':
				self.wdev = dev
				self.wmac = mac
				self.wip = ip
				ret += 'w'
				print('WIFI DEVICE NAME: %s' % self.wdev)
				print('WIFI MAC ADDRESS: %s' % self.wmac)
				print('WIFI IP ADDRESS : %s' % self.wip)
		if not self.eip and not self.wip:
			return ''
		if wowlan:
			if self.edev:
				self.sshcmd('netfix -select wired wolon', 60)
			if self.wdev:
				self.sshcmd('netfix -select wifi wolon', 60)
		return ret
	def bootsetup(self):
		self.sshcmd('sudo systemctl stop fstrim.timer', 60)
		self.sshcmd('sudo systemctl unmask sleep.target suspend.target hibernate.target hybrid-sleep.target', 60)
		os = self.oscheck()
		if os != 'ubuntu':
			return
		self.sshcmd('sudo systemctl stop apt-daily-upgrade', 60)
		self.sshcmd('sudo systemctl stop apt-daily', 60)
		self.sshcmd('sudo systemctl stop upower', 60)
		self.sshcmd('sudo systemctl stop snapd.socket', 60)
		self.sshcmd('sudo systemctl stop snapd', 60)
		# use custom grub file
		check = self.sshcmd('test -f %s && echo yes' % self.grubfileorig, 10)
		if check.strip():
			return
		check = self.sshcmd('test -f %s && echo "yes"' % self.grubfilemine, 10)
		if not check.strip():
			return
		self.sshcmd('sudo cp -f %s %s' % (self.grubfile, self.grubfileorig), 10)
		self.sshcmd('sudo cp -f %s %s' % (self.grubfilemine, self.grubfile), 10)
		self.sshcmd('sudo update-grub', 300)
	def bootclean(self):
		self.sshcmd('sudo systemctl start fstrim.timer', 60)
		os = self.oscheck()
		if os != 'ubuntu':
			return
		self.sshcmd('sudo systemctl start upower', 60)
		# restore original grub file
		check = self.sshcmd('test -f %s && echo yes' % self.grubfileorig, 10)
		if not check.strip():
			return
		self.sshcmd('sudo mv -f %s %s' % (self.grubfileorig, self.grubfile), 10)
		self.sshcmd('sudo update-grub', 300)
	def bioscheck(self, wowlan=False):
		print('MACHINE: %s' % self.host)
		out = self.sshcmd('sudo sleepgraph -sysinfo', 60, False)
		bios = dict()
		for line in out.split('\n'):
			for val in ['bios-release-date', 'bios-vendor', 'bios-version']:
				m = re.match(val+r' *\: *(?P<val>.*)', line)
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
		out = self.sshcmd('grep GRUB_DEFAULT /etc/default/grub 2>/dev/null', 60).strip()
		if out != 'GRUB_DEFAULT=saved':
			cmd = 'sudo sed -i s/%s/GRUB_DEFAULT=saved/g /etc/default/grub' % out
			out = 'Changing GRUB_DEFAULT to saved\n'
			out += self.sshcmd(cmd, 60)
			out += self.sshcmd('sudo update-grub', 300)
			return out
		return ''
	def oscheck(self):
		if not self.ping(5):
			return 'offline'
		out = self.sshcmd('cat /etc/os-release', 60)
		for line in out.split('\n'):
			m = re.match(r'^NAME=[\"]*(?P<os>[^\s\"]*)[\"]*', line)
			if m:
				return m.group('os').lower()
		return ''
	def ping(self, count):
		val = os.system('ping -q -c 1 -W %d %s > /dev/null 2>&1' % (count, self.addr))
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
			' ; cd pm-graph ; sudo make uninstall ; sudo make install; sudo make hwcheck-install'
		out = self.sshcmd(cmd, 100)
		cmd = 'sudo hwcheck all'
		out += self.sshcmd(cmd, 100)
		cmd = r'netfix defconfig | sed -e s/#\ pingaddr:/pingaddr:\ localhost/g > /tmp/netfix.cfg; sudo mv /tmp/netfix.cfg /usr/share/pm-graph/'
		out += self.sshcmd(cmd, 100)
		out += self.sshcmd('netfix status', 100)
		return out
	def install_kernel(self, os, version, pkglist, default=False):
		out, plist = '', ' '.join(pkglist)
		if os in ['ubuntu']:
			out += self.sshcmd('sudo dpkg -i %s' % plist, 600)
			idx = self.kernel_index_grub(version, os)
			if idx < 0:
				return (out, False)
			if default:
				out += self.sshcmd('sudo grub-set-default \'1>%d\'' % idx, 30)
			else:
				out += self.sshcmd('sudo grub-reboot \'1>%d\'' % idx, 30)
		elif os in ['fedora', 'centos']:
			out += self.sshcmd('sudo rpm -ivh --oldpackage %s' % plist, 1200)
			klist, found = self.sshcmd('sudo ls -1 /boot/loader/entries/', 60), ''
			for line in klist.split('\n'):
				if line.endswith(version+'.conf'):
					found = line[:-5]
					break
			if not found:
				return (out, False)
			out += self.sshcmd('sudo grub2-set-default %s' % found, 30)
		return (out, True)
	def list_kernel_packages(self, os):
		packages = []
		if os in ['ubuntu']:
			for line in self.sshcmd('dpkg -l', 30).split('\n'):
				v = line.split()
				if len(v) > 2 and (v[1].startswith('linux-headers-') or \
					v[1].startswith('linux-image-')):
					packages.append(v[1])
		elif os in ['fedora', 'centos']:
			for line in self.sshcmd('rpm -qa kernel', 30).split('\n'):
				if line.strip():
					packages.append(line.strip())
		return packages
	def uninstall_package(self, os, pkgname):
		if os in ['ubuntu']:
			return self.sshcmd('sudo dpkg --purge %s' % pkgname, 600)
		elif os in ['fedora', 'centos']:
			return self.sshcmd('sudo rpm -evh %s' % pkgname, 600)
		return 'uninstall error: %s os is not recognized' % os
	def list_kernels(self, os):
		versions = []
		if os in ['ubuntu']:
			out = self.sshcmd(r'sudo grep ,\ with\ Linux /boot/grub/grub.cfg', 60)
			for line in out.split('\n'):
				if not line.strip() or 'menuentry' not in line:
					continue
				m = re.match(r'.*, with Linux (?P<v>.*)\' --.*', line)
				if not m:
					continue
				versions.append(m.group('v'))
		elif os in ['fedora', 'centos']:
			out = self.sshcmd('rpm -qa kernel', 60)
			for line in out.split('\n'):
				if not line.startswith('kernel-'):
					continue
				versions.append(line.strip())
		return versions
	def kernel_index_grub(self, kver, os):
		versions = self.list_kernels(os)
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
			version = self.sshcmd('cat /proc/version', 120).strip()
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
	def power_on_machine(self):
		if not self.oncmd:
			return True
		values = {'host': self.host, 'addr': self.addr, 'user': self.user}
		cmd = self.oncmd.format(**values)
		print('Power on machine: %s' % cmd)
		return call(cmd, shell=True) == 0
	def power_off_machine(self):
		if not self.offcmd:
			return True
		values = {'host': self.host, 'addr': self.addr, 'user': self.user}
		cmd = self.offcmd.format(**values)
		print('Power off machine: %s' % cmd)
		return call(cmd, shell=True) == 0
	def data_start_collection(self):
		if not self.dstartcmd:
			return True
		values = {'host': self.host, 'addr': self.addr, 'user': self.user}
		cmd = self.dstartcmd.format(**values)
		print('Data start tracing: %s' % cmd)
		return call(cmd, shell=True) == 0
	def data_stop_collection(self, file):
		if not self.dstopcmd:
			return True
		values = {'host': self.host, 'addr': self.addr, 'user': self.user, 'file': file}
		cmd = self.dstopcmd.format(**values)
		print('Data stop & download trace: %s' % cmd)
		return call(cmd, shell=True) == 0
	def reserve_machine(self, minutes):
		if not self.reservecmd:
			return True
		self.sshcmd('access_control -u sleepgraph reserve', 10)
		values = {'host': self.host, 'addr': self.addr,
			'user': self.user, 'minutes': ('%d' % minutes)}
		cmd = self.reservecmd.format(**values)
		print('Reserve %s for %dmin: %s' % (self.host, minutes, cmd))
		return call(cmd, shell=True) == 0
	def release_machine(self):
		if not self.releasecmd:
			return True
		self.sshcmd('access_control release', 10)
		values = {'host': self.host, 'addr': self.addr, 'user': self.user}
		cmd = self.releasecmd.format(**values)
		print('Release machine: %s' % cmd)
		return call(cmd, shell=True) == 0
	def restart_or_die(self, serialout=''):
		if not self.resetcmd:
			print('Machine is dead: %s' % self.host)
			if serialout:
				self.data_stop_collection(serialout)
			self.die()
		print('RESTARTING %s...' % self.host)
		i, rebooted = 0, False
		if (self.wmac and self.wip) or (self.emac and self.eip):
			self.wakeonlan()
		elif not self.resetcmd:
			print('Machine is dead: %s' % self.host)
			if serialout:
				self.data_stop_collection(serialout)
			self.die()
		else:
			self.reset_machine()
			rebooted = True
		while not self.ping(3):
			if i >= 30:
				print('Machine is dead: %s' % self.host)
				if serialout:
					self.data_stop_collection(serialout)
				self.die()
			elif i != 0 and i % 10 == 0:
				print('restarting again...')
				self.reset_machine()
				rebooted = True
			time.sleep(10)
			i += 1
		if not rebooted:
			# wait a few seconds to allow sleepgraph to finish
			time.sleep(10)
			return
		self.bootsetup()
		self.wifisetup(True)
	def reboot(self, kver, default=False):
		os = self.oscheck()
		if os in ['ubuntu']:
			idx = self.kernel_index_grub(kver, os)
			if idx >= 0:
				if default:
					self.sshcmd('sudo grub-set-default \'1>%d\'' % idx, 60)
				else:
					self.sshcmd('sudo grub-reboot \'1>%d\'' % idx, 60)
		print('REBOOTING %s...' % self.host)
		print(self.sshcmd('sudo shutdown -r now', 60))
	def wait_for_boot(self, kver, timeout):
		error, start = 'offline', time.time()
		time.sleep(10)
		while (time.time() - start < timeout):
			error = self.checkhost(False)
			if not error:
				break
		if error:
			return error
		if kver:
			k = self.kernel_version()
			if k != kver:
				return 'wrong kernel (tgt=%s, actual=%s)' % (kver, k)
		return ''
	def reboot_or_die(self, kver):
		self.bootsetup()
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
