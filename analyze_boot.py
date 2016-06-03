#!/usr/bin/python
#
# Tool for analyzing boot timing
# Copyright (c) 2013, Intel Corporation.
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
# You should have received a copy of the GNU General Public License along with
# this program; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin St - Fifth Floor, Boston, MA 02110-1301 USA.
#
# Authors:
#	 Todd Brandt <todd.e.brandt@linux.intel.com>
#
# Description:
#	 This tool is designed to assist kernel and OS developers in optimizing
#	 their linux stack's boot time. It creates an html representation of
#	 the kernel boot timeline up to the start of the init process.
#
#	 The following additional kernel parameters are required:
#		 (e.g. in file /etc/default/grub)
#		 GRUB_CMDLINE_LINUX_DEFAULT="... initcall_debug log_buf_len=16M ..."
#

# ----------------- LIBRARIES --------------------

import sys
import time
import os
import string
import re
import platform
from datetime import datetime, timedelta

# ----------------- CLASSES --------------------

# Class: SystemValues
# Description:
#	 A global, single-instance container used to
#	 store system values and test parameters
class SystemValues:
	version = 1.0
	hostname = 'localhost'
	testtime = ''
	kernel = ''
	verbose = False
	dmesgfile = ''
	htmlfile = 'bootgraph.html'
	outfile = ''
	phoronix = False
	def __init__(self):
		if('LOG_FILE' in os.environ and 'TEST_RESULTS_IDENTIFIER' in os.environ):
			self.phoronix = True
			self.outfile = os.environ['LOG_FILE']
			self.htmlfile = os.environ['LOG_FILE']
		self.hostname = platform.node()
		self.testtime = datetime.now().strftime('%Y-%m-%d_%H:%M:%S')
		fp = open('/proc/version', 'r')
		val = fp.read().strip()
		fp.close()
		self.kernel = self.kernelVersion(val)
	def kernelVersion(self, msg):
		return msg.split()[2]
sysvals = SystemValues()

# Class: DeviceNode
# Description:
#	 A container used to create a device hierachy, with a single root node
#	 and a tree of child nodes. Used by Data.deviceTopology()
class DeviceNode:
	name = ''
	children = 0
	depth = 0
	def __init__(self, nodename, nodedepth):
		self.name = nodename
		self.children = []
		self.depth = nodedepth

# Class: Data
# Description:
#	 The primary container for test data. There is one for
#	 each test run. The data is organized into a cronological hierarchy:
#	 Data.dmesg {
#		root structure, started as dmesg & ftrace, but now only ftrace
#		contents: times for suspend start/end, resume start/end, fwdata
#		phases {
#			10 sequential, non-overlapping phases of S/R
#			contents: times for phase start/end, order/color data for html
#			devlist {
#				device callback or action list for this phase
#				device {
#					a single device callback or generic action
#					contents: start/stop times, pid/cpu/driver info
#						parents/children, html id for timeline/callgraph
#						optionally includes an ftrace callgraph
#						optionally includes intradev trace events
#				}
#			}
#		}
#	}
#
class Data:
	dmesg = {}  # root data structure
	phases = [] # ordered list of phases
	start = 0.0 # test start
	end = 0.0   # test end
	tSuspended = 0.0 # low-level suspend start
	tResumed = 0.0   # low-level resume start
	dmesgtext = []   # dmesg text file in memory
	testnumber = 0
	idstr = ''
	html_device_id = 0
	stamp = 0
	valid = False
	initstart = 0.0
	boottime = ''
	def __init__(self, num):
		idchar = 'abcdefghijklmnopqrstuvwxyz'
		self.testnumber = num
		self.idstr = idchar[num]
		self.dmesgtext = []
		self.phases = []
		self.dmesg = { # fixed list of 10 phases
			'boot': {'list': dict(), 'start': -1.0, 'end': -1.0,
								'row': 0, 'color': '#FFFFCC', 'order': 9}
		}
		self.phases = self.sortedPhases()
	def getStart(self):
		return self.dmesg[self.phases[0]]['start']
	def setStart(self, time):
		self.start = time
		self.dmesg[self.phases[0]]['start'] = time
	def getEnd(self):
		return self.dmesg[self.phases[-1]]['end']
	def setEnd(self, time):
		self.end = time
		self.dmesg[self.phases[-1]]['end'] = time
	def setPhase(self, phase, ktime, isbegin):
		if(isbegin):
			self.dmesg[phase]['start'] = ktime
		else:
			self.dmesg[phase]['end'] = ktime
	def dmesgSortVal(self, phase):
		return self.dmesg[phase]['order']
	def sortedPhases(self):
		return sorted(self.dmesg, key=self.dmesgSortVal)
	def sortedDevices(self, phase):
		list = self.dmesg[phase]['list']
		slist = []
		tmp = dict()
		for devname in list:
			dev = list[devname]
			tmp[dev['start']] = devname
		for t in sorted(tmp):
			slist.append(tmp[t])
		return slist
	def fixupInitcalls(self, phase, end):
		# if any calls never returned, clip them at system resume end
		phaselist = self.dmesg[phase]['list']
		for devname in phaselist:
			dev = phaselist[devname]
			if(dev['end'] < 0):
				dev['end'] = end
				vprint('%s (%s): callback didnt return' % (devname, phase))
	def deviceFilter(self, devicefilter):
		# remove all by the relatives of the filter devnames
		filter = []
		for phase in self.phases:
			list = self.dmesg[phase]['list']
			for name in devicefilter:
				dev = name
				while(dev in list):
					if(dev not in filter):
						filter.append(dev)
					dev = list[dev]['par']
				children = self.deviceDescendants(name, phase)
				for dev in children:
					if(dev not in filter):
						filter.append(dev)
		for phase in self.phases:
			list = self.dmesg[phase]['list']
			rmlist = []
			for name in list:
				pid = list[name]['pid']
				if(name not in filter and pid >= 0):
					rmlist.append(name)
			for name in rmlist:
				del list[name]
	def fixupInitcallsThatDidntReturn(self):
		# if any calls never returned, clip them at system resume end
		for phase in self.phases:
			self.fixupInitcalls(phase, self.getEnd())
	def newActionGlobal(self, name, start, end):
		# which phase is this device callback or action "in"
		targetphase = "none"
		overlap = 0.0
		for phase in self.phases:
			pstart = self.dmesg[phase]['start']
			pend = self.dmesg[phase]['end']
			o = max(0, min(end, pend) - max(start, pstart))
			if(o > overlap):
				targetphase = phase
				overlap = o
		if targetphase in self.phases:
			self.newAction(targetphase, name, -1, '', start, end, '')
			return True
		return False
	def newAction(self, phase, name, pid, parent, start, end, drv):
		# new device callback for a specific phase
		self.html_device_id += 1
		devid = '%s%d' % (self.idstr, self.html_device_id)
		list = self.dmesg[phase]['list']
		length = -1.0
		if(start >= 0 and end >= 0):
			length = end - start
		list[name] = {'start': start, 'end': end, 'pid': pid, 'par': parent,
					  'length': length, 'row': 0, 'id': devid, 'drv': drv }
	def deviceIDs(self, devlist, phase):
		idlist = []
		list = self.dmesg[phase]['list']
		for devname in list:
			if devname in devlist:
				idlist.append(list[devname]['id'])
		return idlist
	def deviceParentID(self, devname, phase):
		pdev = ''
		pdevid = ''
		list = self.dmesg[phase]['list']
		if devname in list:
			pdev = list[devname]['par']
		if pdev in list:
			return list[pdev]['id']
		return pdev
	def deviceChildren(self, devname, phase):
		devlist = []
		list = self.dmesg[phase]['list']
		for child in list:
			if(list[child]['par'] == devname):
				devlist.append(child)
		return devlist
	def deviceDescendants(self, devname, phase):
		children = self.deviceChildren(devname, phase)
		family = children
		for child in children:
			family += self.deviceDescendants(child, phase)
		return family
	def deviceChildrenIDs(self, devname, phase):
		devlist = self.deviceChildren(devname, phase)
		return self.deviceIDs(devlist, phase)
	def printDetails(self):
		vprint('          test start: %f' % self.start)
		for phase in self.phases:
			dc = len(self.dmesg[phase]['list'])
			vprint('    %16s: %f - %f (%d devices)' % (phase, \
				self.dmesg[phase]['start'], self.dmesg[phase]['end'], dc))
		vprint('            test end: %f' % self.end)
	def masterTopology(self, name, list, depth):
		node = DeviceNode(name, depth)
		for cname in list:
			clist = self.deviceChildren(cname, 'resume')
			cnode = self.masterTopology(cname, clist, depth+1)
			node.children.append(cnode)
		return node
	def printTopology(self, node):
		html = ''
		if node.name:
			info = ''
			drv = ''
			for phase in self.phases:
				list = self.dmesg[phase]['list']
				if node.name in list:
					s = list[node.name]['start']
					e = list[node.name]['end']
					if list[node.name]['drv']:
						drv = ' {'+list[node.name]['drv']+'}'
					info += ('<li>%s: %.3fms</li>' % (phase, (e-s)*1000))
			html += '<li><b>'+node.name+drv+'</b>'
			if info:
				html += '<ul>'+info+'</ul>'
			html += '</li>'
		if len(node.children) > 0:
			html += '<ul>'
			for cnode in node.children:
				html += self.printTopology(cnode)
			html += '</ul>'
		return html
	def rootDeviceList(self):
		# list of devices graphed
		real = []
		for phase in self.dmesg:
			list = self.dmesg[phase]['list']
			for dev in list:
				if list[dev]['pid'] >= 0 and dev not in real:
					real.append(dev)
		# list of top-most root devices
		rootlist = []
		for phase in self.dmesg:
			list = self.dmesg[phase]['list']
			for dev in list:
				pdev = list[dev]['par']
				if(re.match('[0-9]*-[0-9]*\.[0-9]*[\.0-9]*\:[\.0-9]*$', pdev)):
					continue
				if pdev and pdev not in real and pdev not in rootlist:
					rootlist.append(pdev)
		return rootlist
	def deviceTopology(self):
		rootlist = self.rootDeviceList()
		master = self.masterTopology('', rootlist, 0)
		return self.printTopology(master)

# Class: Timeline
# Description:
#	 A container for a device timeline which calculates
#	 all the html properties to display it correctly
class Timeline:
	html = {}
	height = 0	# total timeline height
	scaleH = 20	# timescale (top) row height
	rowH = 30	# device row height
	bodyH = 0	# body height
	rows = 0	# total timeline rows
	def __init__(self):
		self.html = {
			'header': '',
			'timeline': '',
			'legend': '',
			'scale': ''
		}
	# Function: calcTotalRows
	# Description:
	#	 Calculate the heights and offsets for the header and rows
	def calcTotalRows(self):
		self.height = self.scaleH + (self.rows*self.rowH)
		self.bodyH = self.height - self.scaleH
	# Function: getPhaseRows
	# Description:
	#	 Organize the timeline entries into the smallest
	#	 number of rows possible, with no entry overlapping
	# Arguments:
	#	 list: the list of devices/actions for a single phase
	#	 sortedkeys: cronologically sorted key list to use
	# Output:
	#	 The total number of rows needed to display this phase of the timeline
	def getPhaseRows(self, list, sortedkeys):
		# clear all rows and set them to undefined
		remaining = len(list)
		rowdata = dict()
		row = 0
		for item in list:
			list[item]['row'] = -1
		# try to pack each row with as many ranges as possible
		while(remaining > 0):
			if(row not in rowdata):
				rowdata[row] = []
			for item in sortedkeys:
				if(list[item]['row'] < 0):
					s = list[item]['start']
					e = list[item]['end']
					valid = True
					for ritem in rowdata[row]:
						rs = ritem['start']
						re = ritem['end']
						if(not (((s <= rs) and (e <= rs)) or
							((s >= re) and (e >= re)))):
							valid = False
							break
					if(valid):
						rowdata[row].append(list[item])
						list[item]['row'] = row
						remaining -= 1
			row += 1
		if(row > self.rows):
			self.rows = int(row)
		return row
	# Function: createTimeScale
	# Description:
	#	 Create the timescale header for the html timeline
	# Arguments:
	#	 t0: start time (suspend begin)
	#	 tMax: end time (resume end)
	#	 tSuspend: time when suspend occurs, i.e. the zero time
	# Output:
	#	 The html code needed to display the time scale
	def createTimeScale(self, t0, tMax, tSuspended):
		timescale = '<div class="t" style="right:{0}%">{1}</div>\n'
		output = '<div id="timescale">\n'
		# set scale for timeline
		tTotal = tMax - t0
		tS = 0.1
		if(tTotal <= 0):
			return output
		if(tTotal > 4):
			tS = 1
		if(tSuspended < 0):
			for i in range(int(tTotal/tS)+1):
				pos = '%0.3f' % (100 - ((float(i)*tS*100)/tTotal))
				if(i > 0):
					val = '%0.fms' % (float(i)*tS*1000)
				else:
					val = ''
				output += timescale.format(pos, val)
		else:
			tSuspend = tSuspended - t0
			divTotal = int(tTotal/tS) + 1
			divSuspend = int(tSuspend/tS)
			s0 = (tSuspend - tS*divSuspend)*100/tTotal
			for i in range(divTotal):
				pos = '%0.3f' % (100 - ((float(i)*tS*100)/tTotal) - s0)
				if((i == 0) and (s0 < 3)):
					val = ''
				elif(i == divSuspend):
					val = 'S/R'
				else:
					val = '%0.fms' % (float(i-divSuspend)*tS*1000)
				output += timescale.format(pos, val)
		output += '</div>\n'
		self.html['scale'] = output

# ----------------- FUNCTIONS --------------------

# Function: vprint
# Description:
#	 verbose print (prints only with -verbose option)
# Arguments:
#	 msg: the debug/log message to print
def vprint(msg):
	global sysvals
	if(sysvals.verbose):
		print(msg)

# Function: loadRawKernelLog
# Description:
#	 Load a raw kernel log from dmesg
def loadRawKernelLog():
	global sysvals

	data = Data(0)
	ktime = 0.0
	data.start = ktime
	initcall = False

	data.stamp = {
		'time': datetime.now().strftime('%B %d %Y, %I:%M:%S %p'),
		'host': sysvals.hostname,
		'mode': 'boot', 'kernel': ''}

	if(sysvals.dmesgfile):
		lf = open(sysvals.dmesgfile, 'r')
	else:
		lf = os.popen('dmesg')
	for line in lf:
		line = line.replace('\r\n', '')
		idx = line.find('[')
		if idx > 1:
			line = line[idx:]
		m = re.match('[ \t]*(\[ *)(?P<ktime>[0-9\.]*)(\]) (?P<msg>.*)', line)
		if(not m):
			continue
		val = m.group('ktime')
		try:
			ktime = float(val)
		except:
			continue
		msg = m.group('msg')
		if(ktime > 120 or re.match('PM: Syncing filesystems.*', msg)):
			break
		if(not data.valid):
			if(ktime == 0.0 and re.match('^Linux version .*', msg)):
				vprint("Dmesg data includes a boot log")
				data.dmesgtext.append(line.strip())
				data.valid = True
				if(not data.stamp['kernel']):
					data.stamp['kernel'] = sysvals.kernelVersion(msg)
			continue
		m = re.match('.* setting system clock to (?P<t>.*) UTC.*', msg)
		if(m):
			utc = int((datetime.now() - datetime.utcnow()).total_seconds())
			bt = datetime.strptime(m.group('t'), '%Y-%m-%d %H:%M:%S')
			bt = bt - timedelta(seconds=int(ktime)-utc)
			data.boottime = bt.strftime('%Y-%m-%d_%H:%M:%S')
			data.stamp['time'] = bt.strftime('%B %d %Y, %I:%M:%S %p')
			vprint("Boot started at %s" % data.boottime)
		elif(re.match('^calling *(?P<f>.*)\+.*', msg)):
			initcall = True
		elif(re.match('^initcall *(?P<f>.*)\+.*', msg)):
			initcall = True
		elif(re.match('^Freeing unused kernel memory.*', msg) and \
			(data.initstart == 0)):
			vprint("Init process starts at %.3f" % (ktime*1000))
			data.initstart = ktime
		else:
			continue
		data.dmesgtext.append(line.strip())
		data.end = ktime	

	data.start *= 1000.0
	data.end *= 1000.0
	data.initstart *= 1000.0
	lf.close()
	if(initcall):
		vprint("Boot data ends at %.3f" % data.end)
	else:
		vprint("No initcalls, initcall_debug is missing")
		data.valid = False
	return data

def parseKernelBootLog(data):
	global sysvals

	ktime = 0.0
	phase = 'boot'
	data.start = ktime
	data.dmesg[phase]['start'] = ktime

	for line in data.dmesgtext:
		# parse each dmesg line into the time and message
		m = re.match('[ \t]*(\[ *)(?P<ktime>[0-9\.]*)(\]) (?P<msg>.*)', line)
		if(m):
			val = m.group('ktime')
			try:
				ktime = float(val)
			except:
				doWarning('INVALID DMESG LINE: '+\
					line.strip(), 'dmesg')
				continue
			msg = m.group('msg')
		else:
			continue
		# only parse a max of 120 seconds
		if ktime > 120:
			break
		# stop at start of user mode
		if(re.match('^Freeing unused kernel memory.*', msg)):
			break
		# initcall call
		m = re.match('^calling *(?P<f>.*)\+.*', msg)
		if(m):
			f = m.group('f')
			data.newAction(phase, f, 0, '', ktime, -1, '')
			continue
		# initcall return
		m = re.match('^initcall *(?P<f>.*)\+.*', msg)
		if(m):
			f = m.group('f')
			list = data.dmesg[phase]['list']
			if(f in list):
				dev = list[f]
				dev['end'] = ktime
				data.end = ktime
			continue

	data.dmesg[phase]['end'] = data.end

# Function: colorForName
# Description:
#	 Generate a repeatable color from a list for a given name
def colorForName(name, list):
	i = 0
	total = 0
	count = len(list)
	while i < len(name):
		total += ord(name[i])
		i += 1
	return list[total % count]

# Function: createBootGraph
# Description:
#	 Create the output html file from the resident test data
# Arguments:
#	 testruns: array of Data objects from parseKernelLog or parseTraceLog
# Output:
#	 True if the html file was created, false if it failed
def createBootGraph(data, embedded):
	global sysvals

	# html function templates
	headline_stamp = '<div class="stamp">{0} {1} {2} {3}</div>\n'
	html_zoombox = '<center><button id="zoomin">ZOOM IN</button><button id="zoomout">ZOOM OUT</button><button id="zoomdef">ZOOM 1:1</button></center>\n'
	html_timeline = '<div id="dmesgzoombox" class="zoombox">\n<div id="{0}" class="timeline" style="height:{1}px">\n'
	html_device = '<div id="{0}" title="{1}" class="thread{7}" style="left:{2}%;top:{3}px;height:{4}px;width:{5}%;">{6}</div>\n'
	html_phase = '<div class="phase" style="left:{0}%;width:{1}%;top:{2}px;height:{3}px;background-color:{4}">{5}</div>\n'
	html_phaselet = '<div id="{0}" class="phaselet" style="left:{1}%;width:{2}%;background-color:{3}"></div>\n'
	html_timetotal = '<table class="time1">\n<tr>'\
		'<td class="blue">Time from Kernel Boot to start of User Mode: <b>{0} ms</b></td>'\
		'</tr>\n</table>\n'

	# device timeline
	vprint('Creating Boot Timeline...')
	devtl = Timeline()
	devtl.rowH = 100

	# Generate the header for this timeline
	t0 = data.start
	tMax = data.end
	tTotal = tMax - t0
	if(tTotal == 0):
		print('ERROR: No timeline data')
		return False
	boot_time = '%.0f'%(tTotal*1000)
	devtl.html['timeline'] += html_timetotal.format(boot_time)

	# determine the maximum number of rows we need to draw
	phase = 'boot'
	list = data.dmesg[phase]['list']
	data.dmesg[phase]['row'] = devtl.getPhaseRows(list, list)
	devtl.calcTotalRows()

	# create bounding box, add buttons
	devtl.html['timeline'] += html_zoombox
	devtl.html['timeline'] += html_timeline.format('dmesg', devtl.height)

	# draw the colored boxes for each of the phases
	boot = data.dmesg[phase]
	length = boot['end']-boot['start']
	left = '%.3f' % (((boot['start']-t0)*100.0)/tTotal)
	width = '%.3f' % ((length*100.0)/tTotal)
	devtl.html['timeline'] += html_phase.format('0', '100', \
		'%.3f'%devtl.scaleH, '%.3f'%devtl.bodyH, \
		'white', '')

	# draw the time scale, try to make the number of labels readable
	devtl.createTimeScale(t0, tMax, t0)
	devtl.html['timeline'] += devtl.html['scale']

	# draw the device timeline
	phaselist = data.dmesg[phase]['list']
	color = ['c1', 'c2', 'c3', 'c4', 'c5',
		'c6', 'c7', 'c8', 'c9', 'c10']
	for d in phaselist:
		name = d
		c = colorForName(name, color)
		dev = phaselist[d]
		height = devtl.bodyH/data.dmesg[phase]['row']
		top = '%.3f' % ((dev['row']*height) + devtl.scaleH)
		left = '%.3f' % (((dev['start']-t0)*100)/tTotal)
		width = '%.3f' % (((dev['end']-dev['start'])*100)/tTotal)
		length = ' (%0.3f ms) ' % ((dev['end']-dev['start'])*1000)
		devtl.html['timeline'] += html_device.format(dev['id'], \
			d+length+'kernel_mode', left, top, '%.3f'%height, width, name, ' '+c)

	# timeline is finished
	devtl.html['timeline'] += '</div>\n</div>\n'

	if(sysvals.outfile == sysvals.htmlfile):
		hf = open(sysvals.htmlfile, 'a')
	else:
		hf = open(sysvals.htmlfile, 'w')

	# write the html header first (html head, css code, up to body start)
	html_header = '<!DOCTYPE html>\n<html>\n<head>\n\
	<meta http-equiv="content-type" content="text/html; charset=UTF-8">\n\
	<title>Boot Graph</title>\n\
	<style type=\'text/css\'>\n\
		body {overflow-y: scroll;}\n\
		.stamp {width: 100%;text-align:center;background-color:gray;line-height:30px;color:white;font: 25px Arial;}\n\
		t0 {color:black;font: bold 30px Times;}\n\
		t1 {color:black;font: 30px Times;}\n\
		t2 {color:black;font: 25px Times;}\n\
		t3 {color:black;font: 20px Times;white-space:nowrap;}\n\
		t4 {color:black;font: bold 30px Times;line-height:60px;white-space:nowrap;}\n\
		table {width:100%;}\n\
		.blue {background-color:rgba(169,208,245,0.4);}\n\
		.c1 {background-color:rgba(209,0,0,0.4);}\n\
		.c2 {background-color:rgba(255,102,34,0.4);}\n\
		.c3 {background-color:rgba(255,218,33,0.4);}\n\
		.c4 {background-color:rgba(51,221,0,0.4);}\n\
		.c5 {background-color:rgba(17,51,204,0.4);}\n\
		.c6 {background-color:rgba(34,0,102,0.4);}\n\
		.c7 {background-color:rgba(51,0,68,0.4);}\n\
		.c8 {background-color:rgba(204,255,204,0.4);}\n\
		.c9 {background-color:rgba(169,208,245,0.4);}\n\
		.c10 {background-color:rgba(255,255,204,0.4);}\n\
		.time1 {font: 22px Arial;border:1px solid;}\n\
		td {text-align: center;}\n\
		.zoombox {position: relative; width: 100%; overflow-x: scroll;}\n\
		.timeline {position: relative; font-size: 14px;cursor: pointer;width: 100%; overflow: hidden; background-color:#dddddd;}\n\
		.thread {position: absolute; height: 0%; overflow: hidden; line-height: 30px; border:1px solid;text-align:center;white-space:nowrap}\n\
		.thread:hover {border:1px solid red;z-index:10;}\n\
		.hover {background-color:white;border:1px solid red;z-index:10;}\n\
		.phase {position: absolute;overflow: hidden;border:0px;text-align:center;}\n\
		.phaselet {position:absolute;overflow:hidden;border:0px;text-align:center;height:100px;font-size:24px;}\n\
		.t {position:absolute;top:0%;height:100%;border-right:1px solid black;}\n\
		button {height:40px;width:200px;margin-bottom:20px;margin-top:20px;font-size:24px;}\n\
		#devicedetail {height:100px;box-shadow: 5px 5px 20px black;}\n\
	</style>\n</head>\n<body>\n'

	# no header or css if its embedded
	if(not embedded):
		hf.write(html_header)

	# write the test title and general info header
	if(data.stamp['time'] != ""):
		hf.write(headline_stamp.format(data.stamp['host'],
			data.stamp['kernel'], 'boot', \
				data.stamp['time']))

	# write the device timeline
	hf.write(devtl.html['timeline'])

	# draw the colored boxes for the device detail section
	hf.write('<div id="devicedetailtitle"></div>\n')
	hf.write('<div id="devicedetail" style="display:none;">\n')
	hf.write('<div id="devicedetail%d">\n' % data.testnumber)
	hf.write(html_phaselet.format('kernel_mode', '0', '100', '#DDDDDD'))
	hf.write('</div>\n')
	hf.write('</div>\n')

	if(not embedded):
		# write the footer and close
		addScriptCode(hf, [data])
		hf.write('</body>\n</html>\n')
	else:
		# embedded out will be loaded in a page, skip the js
		hf.write('<div id=bounds style=display:none>%f,%f</div>' % \
			(data.start, data.initstart))
	hf.close()
	return True

# Function: addScriptCode
# Description:
#	 Adds the javascript code to the output html
# Arguments:
#	 hf: the open html file pointer
#	 testruns: array of Data objects from parseKernelLog or parseTraceLog
def addScriptCode(hf, testruns):
	t0 = (testruns[0].start - testruns[-1].tSuspended) * 1000
	tMax = (testruns[-1].end - testruns[-1].tSuspended) * 1000
	# create an array in javascript memory with the device details
	detail = '	var devtable = [];\n'
	for data in testruns:
		topo = data.deviceTopology()
		detail += '	devtable[%d] = "%s";\n' % (data.testnumber, topo)
	detail += '	var bounds = [%f,%f];\n' % (t0, tMax)
	# add the code which will manipulate the data in the browser
	script_code = \
	'<script type="text/javascript">\n'+detail+\
	'	function zoomTimeline() {\n'\
	'		var timescale = document.getElementById("timescale");\n'\
	'		var dmesg = document.getElementById("dmesg");\n'\
	'		var zoombox = document.getElementById("dmesgzoombox");\n'\
	'		var val = parseFloat(dmesg.style.width);\n'\
	'		var newval = 100;\n'\
	'		var sh = window.outerWidth / 2;\n'\
	'		if(this.id == "zoomin") {\n'\
	'			newval = val * 1.2;\n'\
	'			if(newval > 40000) newval = 40000;\n'\
	'			dmesg.style.width = newval+"%";\n'\
	'			zoombox.scrollLeft = ((zoombox.scrollLeft + sh) * newval / val) - sh;\n'\
	'		} else if (this.id == "zoomout") {\n'\
	'			newval = val / 1.2;\n'\
	'			if(newval < 100) newval = 100;\n'\
	'			dmesg.style.width = newval+"%";\n'\
	'			zoombox.scrollLeft = ((zoombox.scrollLeft + sh) * newval / val) - sh;\n'\
	'		} else {\n'\
	'			zoombox.scrollLeft = 0;\n'\
	'			dmesg.style.width = "100%";\n'\
	'		}\n'\
	'		var html = "";\n'\
	'		var t0 = bounds[0];\n'\
	'		var tMax = bounds[1];\n'\
	'		var tTotal = tMax - t0;\n'\
	'		var wTotal = tTotal * 100.0 / newval;\n'\
	'		for(var tS = 1000; (wTotal / tS) < 3; tS /= 10);\n'\
	'		if(tS < 1) tS = 1;\n'\
	'		for(var s = ((t0 / tS)|0) * tS; s < tMax; s += tS) {\n'\
	'			var pos = (tMax - s) * 100.0 / tTotal;\n'\
	'			var name = (s == 0)?"S/R":(s+"ms");\n'\
	'			html += "<div class=\\"t\\" style=\\"right:"+pos+"%\\">"+name+"</div>";\n'\
	'		}\n'\
	'		timescale.innerHTML = html;\n'\
	'	}\n'\
	'	function deviceHover() {\n'\
	'		var name = this.title.slice(0, this.title.indexOf(" ("));\n'\
	'		var dmesg = document.getElementById("dmesg");\n'\
	'		var dev = dmesg.getElementsByClassName("thread");\n'\
	'		var cpu = -1;\n'\
	'		if(name.match("CPU_ON\[[0-9]*\]"))\n'\
	'			cpu = parseInt(name.slice(7));\n'\
	'		else if(name.match("CPU_OFF\[[0-9]*\]"))\n'\
	'			cpu = parseInt(name.slice(8));\n'\
	'		for (var i = 0; i < dev.length; i++) {\n'\
	'			dname = dev[i].title.slice(0, dev[i].title.indexOf(" ("));\n'\
	'			var cname = dev[i].className.slice(dev[i].className.indexOf("thread"));\n'\
	'			if((cpu >= 0 && dname.match("CPU_O[NF]*\\\[*"+cpu+"\\\]")) ||\n'\
	'				(name == dname))\n'\
	'			{\n'\
	'				dev[i].className = "hover "+cname;\n'\
	'			} else {\n'\
	'				dev[i].className = cname;\n'\
	'			}\n'\
	'		}\n'\
	'	}\n'\
	'	function deviceUnhover() {\n'\
	'		var dmesg = document.getElementById("dmesg");\n'\
	'		var dev = dmesg.getElementsByClassName("thread");\n'\
	'		for (var i = 0; i < dev.length; i++) {\n'\
	'			dev[i].className = dev[i].className.slice(dev[i].className.indexOf("thread"));\n'\
	'		}\n'\
	'	}\n'\
	'	function deviceTitle(title, total, cpu) {\n'\
	'		var prefix = "Total";\n'\
	'		if(total.length > 3) {\n'\
	'			prefix = "Average";\n'\
	'			total[1] = (total[1]+total[3])/2;\n'\
	'			total[2] = (total[2]+total[4])/2;\n'\
	'		}\n'\
	'		var devtitle = document.getElementById("devicedetailtitle");\n'\
	'		var name = title.slice(0, title.indexOf(" "));\n'\
	'		if(cpu >= 0) name = "CPU"+cpu;\n'\
	'		var driver = "";\n'\
	'		var tS = "<t2>(</t2>";\n'\
	'		var tR = "<t2>)</t2>";\n'\
	'		if(total[1] > 0)\n'\
	'			tS = "<t2>("+prefix+" Suspend:</t2><t0> "+total[1].toFixed(3)+" ms</t0> ";\n'\
	'		if(total[2] > 0)\n'\
	'			tR = " <t2>"+prefix+" Resume:</t2><t0> "+total[2].toFixed(3)+" ms<t2>)</t2></t0>";\n'\
	'		var s = title.indexOf("{");\n'\
	'		var e = title.indexOf("}");\n'\
	'		if((s >= 0) && (e >= 0))\n'\
	'			driver = title.slice(s+1, e) + " <t1>@</t1> ";\n'\
	'		if(total[1] > 0 && total[2] > 0)\n'\
	'			devtitle.innerHTML = "<t0>"+driver+name+"</t0> "+tS+tR;\n'\
	'		else\n'\
	'			devtitle.innerHTML = "<t0>"+title+"</t0>";\n'\
	'		return name;\n'\
	'	}\n'\
	'	function deviceDetail() {\n'\
	'		var devinfo = document.getElementById("devicedetail");\n'\
	'		devinfo.style.display = "block";\n'\
	'		var name = this.title.slice(0, this.title.indexOf(" ("));\n'\
	'		var cpu = -1;\n'\
	'		if(name.match("CPU_ON\[[0-9]*\]"))\n'\
	'			cpu = parseInt(name.slice(7));\n'\
	'		else if(name.match("CPU_OFF\[[0-9]*\]"))\n'\
	'			cpu = parseInt(name.slice(8));\n'\
	'		var dmesg = document.getElementById("dmesg");\n'\
	'		var dev = dmesg.getElementsByClassName("thread");\n'\
	'		var idlist = [];\n'\
	'		var pdata = [[]];\n'\
	'		var pd = pdata[0];\n'\
	'		var total = [0.0, 0.0, 0.0];\n'\
	'		for (var i = 0; i < dev.length; i++) {\n'\
	'			dname = dev[i].title.slice(0, dev[i].title.indexOf(" ("));\n'\
	'			if((cpu >= 0 && dname.match("CPU_O[NF]*\\\[*"+cpu+"\\\]")) ||\n'\
	'				(name == dname))\n'\
	'			{\n'\
	'				idlist[idlist.length] = dev[i].id;\n'\
	'				var tidx = 1;\n'\
	'				if(dev[i].id[0] == "a") {\n'\
	'					pd = pdata[0];\n'\
	'				} else {\n'\
	'					if(pdata.length == 1) pdata[1] = [];\n'\
	'					if(total.length == 3) total[3]=total[4]=0.0;\n'\
	'					pd = pdata[1];\n'\
	'					tidx = 3;\n'\
	'				}\n'\
	'				var info = dev[i].title.split(" ");\n'\
	'				var pname = info[info.length-1];\n'\
	'				pd[pname] = parseFloat(info[info.length-3].slice(1));\n'\
	'				total[0] += pd[pname];\n'\
	'				if(pname.indexOf("suspend") >= 0)\n'\
	'					total[tidx] += pd[pname];\n'\
	'				else\n'\
	'					total[tidx+1] += pd[pname];\n'\
	'			}\n'\
	'		}\n'\
	'		var devname = deviceTitle(this.title, total, cpu);\n'\
	'		var left = 0.0;\n'\
	'		for (var t = 0; t < pdata.length; t++) {\n'\
	'			pd = pdata[t];\n'\
	'			devinfo = document.getElementById("devicedetail"+t);\n'\
	'			var phases = devinfo.getElementsByClassName("phaselet");\n'\
	'			for (var i = 0; i < phases.length; i++) {\n'\
	'				if(phases[i].id in pd) {\n'\
	'					var w = 100.0*pd[phases[i].id]/total[0];\n'\
	'					var fs = 32;\n'\
	'					if(w < 8) fs = 4*w | 0;\n'\
	'					var fs2 = fs*3/4;\n'\
	'					phases[i].style.width = w+"%";\n'\
	'					phases[i].style.left = left+"%";\n'\
	'					phases[i].title = phases[i].id+" "+pd[phases[i].id]+" ms";\n'\
	'					left += w;\n'\
	'					var time = "<t4 style=\\"font-size:"+fs+"px\\">"+pd[phases[i].id]+" ms<br></t4>";\n'\
	'					var pname = "<t3 style=\\"font-size:"+fs2+"px\\">"+phases[i].id.replace("_", " ")+"</t3>";\n'\
	'					phases[i].innerHTML = time+pname;\n'\
	'				} else {\n'\
	'					phases[i].style.width = "0%";\n'\
	'					phases[i].style.left = left+"%";\n'\
	'				}\n'\
	'			}\n'\
	'		}\n'\
	'		var cglist = document.getElementById("callgraphs");\n'\
	'		if(!cglist) return;\n'\
	'		var cg = cglist.getElementsByClassName("atop");\n'\
	'		for (var i = 0; i < cg.length; i++) {\n'\
	'			if(idlist.indexOf(cg[i].id) >= 0) {\n'\
	'				cg[i].style.display = "block";\n'\
	'			} else {\n'\
	'				cg[i].style.display = "none";\n'\
	'			}\n'\
	'		}\n'\
	'	}\n'\
	'	function devListWindow(e) {\n'\
	'		var sx = e.clientX;\n'\
	'		if(sx > window.innerWidth - 440)\n'\
	'			sx = window.innerWidth - 440;\n'\
	'		var cfg="top="+e.screenY+", left="+sx+", width=440, height=720, scrollbars=yes";\n'\
	'		var win = window.open("", "_blank", cfg);\n'\
	'		if(window.chrome) win.moveBy(sx, 0);\n'\
	'		var html = "<title>"+e.target.innerHTML+"</title>"+\n'\
	'			"<style type=\\"text/css\\">"+\n'\
	'			"   ul {list-style-type:circle;padding-left:10px;margin-left:10px;}"+\n'\
	'			"</style>"\n'\
	'		var dt = devtable[0];\n'\
	'		if(e.target.id != "devlist1")\n'\
	'			dt = devtable[1];\n'\
	'		win.document.write(html+dt);\n'\
	'	}\n'\
	'	window.addEventListener("load", function () {\n'\
	'		var dmesg = document.getElementById("dmesg");\n'\
	'		dmesg.style.width = "100%"\n'\
	'		document.getElementById("zoomin").onclick = zoomTimeline;\n'\
	'		document.getElementById("zoomout").onclick = zoomTimeline;\n'\
	'		document.getElementById("zoomdef").onclick = zoomTimeline;\n'\
	'		var devlist = document.getElementsByClassName("devlist");\n'\
	'		for (var i = 0; i < devlist.length; i++)\n'\
	'			devlist[i].onclick = devListWindow;\n'\
	'		var dev = dmesg.getElementsByClassName("thread");\n'\
	'		for (var i = 0; i < dev.length; i++) {\n'\
	'			dev[i].onclick = deviceDetail;\n'\
	'			dev[i].onmouseover = deviceHover;\n'\
	'			dev[i].onmouseout = deviceUnhover;\n'\
	'		}\n'\
	'		zoomTimeline();\n'\
	'	});\n'\
	'</script>\n'
	hf.write(script_code);

def testResults(data, embedded):
	global sysvals
	if(sysvals.outfile):
		fp = open(sysvals.outfile, 'w')
		if(embedded):
			fp.write('pass %s initstart %.3f end %.3f boot %s\n' %
				(data.valid, data.initstart, data.end, data.boottime))
		else:
			for line in data.dmesgtext:
				fp.write(line+'\n')
		fp.close()
	print('           Host: %s' % sysvals.hostname)
	print('      Test time: %s' % sysvals.testtime)
	print('      Boot time: %s' % data.boottime)
	print(' Kernel Version: %s' % sysvals.kernel)
	print('Boot data found: %s' % data.valid)
	if(not data.valid):
		return
	print('   Kernel start: %.3f' % data.start)
	print('     init start: %.3f' % data.initstart)
	print('       Data end: %.3f' % data.end)

# Function: doError
# Description:
#	 generic error function for catastrphic failures
# Arguments:
#	 msg: the error message to print
#	 help: True if printHelp should be called after, False otherwise
def doError(msg, help):
	if(help == True):
		printHelp()
	print('ERROR: %s\n') % msg
	sys.exit()

# Function: printHelp
# Description:
#	 print out the help text
def printHelp():
	global sysvals

	print('')
	print('AnalyzeBoot v%.1f' % sysvals.version)
	print('Usage: analyze_boot.py <options>')
	print('')
	print('Description:')
	print('  This tool reads in a dmesg log of linux kernel boot and')
	print('  creates an html representation of the boot timeline up to')
	print('  the start of the init process.')
	print('  If no arguments are given the tool reads the host dmesg log')
	print('  and outputs bootgraph.html')
	print('')
	print('Options:')
	print('  -h                 Print this help text')
	print('  -v                 Print the current tool version')
	print('  -verbose           Print extra information')
	print('  -embed             Format out & html for embedding in a web page')
	print('  -dmesg dmesgfile   Load a stored dmesg file')
	print('  -html file         Create the HTML timeline')
	print('  -out file          Output the test out to file')
	print('')
	return True

# ----------------- MAIN --------------------
# exec start (skipped if script is loaded as library)
if __name__ == '__main__':
	embed = False
	# loop through the command line arguments
	args = iter(sys.argv[1:])
	for arg in args:
		if(arg == '-h'):
			printHelp()
			sys.exit()
		elif(arg == '-v'):
			print("Version %.1f" % sysvals.version)
			sys.exit()
		elif(arg == '-verbose'):
			sysvals.verbose = True
		elif(arg == '-embed'):
			embed = True
		elif(arg == '-dmesg'):
			try:
				val = args.next()
			except:
				doError('No dmesg file supplied', True)
			if(os.path.exists(val) == False):
				doError('%s doesnt exist' % val, False)
			if(sysvals.htmlfile == val or sysvals.outfile == val):
				doError('Output filename collision', False)
			sysvals.dmesgfile = val
		elif(arg == '-out'):
			try:
				val = args.next()
			except:
				doError('No output filename supplied', True)
			if(sysvals.dmesgfile == val):
				doError('Output filename collision', False)
			sysvals.outfile = val
		elif(arg == '-html'):
			try:
				val = args.next()
			except:
				doError('No HTML filename supplied', True)
			if(sysvals.dmesgfile == val):
				doError('Output filename collision', False)
			sysvals.htmlfile = val
		else:
			doError('Invalid argument: '+arg, True)

	if(sysvals.phoronix):
		embed = True
	data = loadRawKernelLog()
	testResults(data, embed)
	if(data.valid):
		parseKernelBootLog(data)
		createBootGraph(data, embed)
