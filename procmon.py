#!/usr/bin/python
import sys
import time
import string
from subprocess import call, Popen, PIPE

if __name__ == '__main__':
	if(len(sys.argv) != 2):
		print 'Procmon - monitor a process cpu and mem usage'
		print 'USAGE: procmon.py "command to run"'
		sys.exit()
	p = Popen(sys.argv[1].split())
	maxvmem = maxpmem = 0
	lastjiff = 0
	while p.poll() == None:
		with open('/proc/%d/stat' % p.pid, 'r') as fp:
			data = fp.read().split()
		jiff = int(data[13])
		vmem = float(data[22])/(1024*1024)
		pmem = float(data[23])*4096/(1024*1024)
		maxvmem = max(vmem, maxvmem)
		maxpmem = max(pmem, maxpmem)
		print 'CPU=%3d%%, VMEM=%.3f MB, PMEM=%.3f MB, MAX=[%.3f MB %.3f MB]' % (jiff - lastjiff, vmem, pmem, maxvmem, maxpmem)
		lastjiff = jiff
		time.sleep(1)
