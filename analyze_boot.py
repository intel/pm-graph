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
from subprocess import call, Popen, PIPE
try:
	import analyze_suspend as aslib
	analyze_suspend_loaded = True
except ImportError:
	analyze_suspend_loaded = False
# ----------------- CLASSES --------------------

# Class: SystemValues
# Description:
#	 A global, single-instance container used to
#	 store system values and test parameters
class SystemValues:
	version = 2.0
	hostname = 'localhost'
	testtime = ''
	kernel = ''
	dmesgfile = ''
	ftracefile = ''
	htmlfile = 'bootgraph.html'
	outfile = ''
	phoronix = False
	addlogs = False
	usecallgraph = False
	def __init__(self):
		if('LOG_FILE' in os.environ and 'TEST_RESULTS_IDENTIFIER' in os.environ):
			self.phoronix = True
			self.addlogs = True
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

# Class: Data
# Description:
#	 The primary container for test data.
class Data:
	dmesg = {}  # root data structure
	start = 0.0 # test start
	end = 0.0   # test end
	dmesgtext = []   # dmesg text file in memory
	testnumber = 0
	idstr = ''
	html_device_id = 0
	stamp = 0
	valid = False
	initstart = 0.0
	boottime = ''
	def __init__(self, num):
		self.testnumber = num
		self.idstr = 'a'
		self.dmesgtext = []
		self.dmesg = {
			'boot': {'list': dict(), 'start': -1.0, 'end': -1.0, 'row': 0}
		}
	def newAction(self, phase, name, pid, parent, start, end, drv):
		# new device callback for a specific phase
		self.html_device_id += 1
		devid = '%s%d' % (self.idstr, self.html_device_id)
		list = self.dmesg[phase]['list']
		length = -1.0
		if(start >= 0 and end >= 0):
			length = end - start
		i = 2
		origname = name
		while(name in list):
			name = '%s[%d]' % (origname, i)
			i += 1
		list[name] = {'start': start, 'end': end, 'pid': pid, 'par': parent,
					  'length': length, 'row': 0, 'id': devid, 'drv': drv }
		return name
	def deviceMatch(self, cg):
		list = self.dmesg['boot']['list']
		for devname in list:
			dev = list[devname]
			if(cg.start <= dev['start'] and
				cg.end >= dev['end']):
				dev['ftrace'] = cg
				return True
		return False

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
						rn = ritem['end']
						if(not (((s <= rs) and (e <= rs)) or
							((s >= rn) and (e >= rn)))):
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
	#	 t0: start time
	#	 tMax: end time
	# Output:
	#	 The html code needed to display the time scale
	def createTimeScale(self, t0, tMax):
		timescale = '<div class="t" style="right:{0}%">{1}</div>\n'
		output = '<div id="timescale">\n'
		# set scale for timeline
		tTotal = tMax - t0
		tS = 0.1
		if(tTotal <= 0):
			return output
		if(tTotal > 4):
			tS = 1
		divTotal = int(tTotal/tS) + 1
		for i in range(divTotal):
			pos = '%0.3f' % (100 - ((float(i)*tS*100)/tTotal))
			if(i == 0):
				val = ''
			else:
				val = '%0.fms' % (float(i)*tS*1000)
			output += timescale.format(pos, val)
		output += '</div>\n'
		self.html['scale'] = output

# ----------------- FUNCTIONS --------------------

# Function: loadKernelLog
# Description:
#	 Load a raw kernel log from dmesg
def loadKernelLog():
	data = Data(0)
	data.dmesg['boot']['start'] = data.start = ktime = 0.0
	data.stamp = {
		'time': datetime.now().strftime('%B %d %Y, %I:%M:%S %p'),
		'host': sysvals.hostname,
		'mode': 'boot', 'kernel': ''}

	devtemp = dict()
	if(sysvals.dmesgfile):
		lf = open(sysvals.dmesgfile, 'r')
	else:
		lf = Popen('dmesg', stdout=PIPE).stdout
	for line in lf:
		line = line.replace('\r\n', '')
		idx = line.find('[')
		if idx > 1:
			line = line[idx:]
		m = re.match('[ \t]*(\[ *)(?P<ktime>[0-9\.]*)(\]) (?P<msg>.*)', line)
		if(not m):
			continue
		ktime = float(m.group('ktime'))
		if(ktime > 120):
			break
		msg = m.group('msg')
		data.end = data.initstart = ktime
		data.dmesgtext.append(line)
		if(ktime == 0.0 and re.match('^Linux version .*', msg)):
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
			continue
		m = re.match('^calling *(?P<f>.*)\+.*', msg)
		if(m):
			devtemp[m.group('f')] = ktime
			continue
		m = re.match('^initcall *(?P<f>.*)\+.*', msg)
		if(m):
			data.valid = True
			f = m.group('f')
			if(f in devtemp):
				data.newAction('boot', f, 0, '', devtemp[f], ktime, '')
				data.end = ktime
				del devtemp[f]
			continue
		if(re.match('^Freeing unused kernel memory.*', msg)):
			break

	data.dmesg['boot']['end'] = data.end
	lf.close()
	return data

# Function: loadTraceLog
# Description:
#	 Check if trace is available and copy to a temp file
def loadTraceLog(data):
	# load the data to a temp file if none given
	if not sysvals.ftracefile:
		lib = aslib.sysvals
		aslib.rootCheck(True)
		if not lib.verifyFtrace():
			doError('ftrace not available')
		if lib.fgetVal('current_tracer').strip() != 'function_graph' or \
			'do_one_initcall' not in lib.fgetVal('set_graph_function'):
			doError('ftrace not configured for a boot callgraph')
		sysvals.ftracefile = '/tmp/boot_ftrace.%s.txt' % os.getpid()
		call('cat '+lib.tpath+'trace > '+sysvals.ftracefile, shell=True)
	if not sysvals.ftracefile:
		doError('No trace data available')

	# parse the trace log
	ftemp = dict()
	tp = aslib.TestProps()
	tp.setTracerType('function_graph')
	tf = open(sysvals.ftracefile, 'r')
	for line in tf:
		if line[0] == '#':
			continue
		m = re.match(tp.ftrace_line_fmt, line.strip())
		if(not m):
			continue
		m_time, m_proc, m_pid, m_msg, m_dur = \
			m.group('time', 'proc', 'pid', 'msg', 'dur')
		if float(m_time) > data.end:
			break
		if(m_time and m_pid and m_msg):
			t = aslib.FTraceLine(m_time, m_msg, m_dur)
			pid = int(m_pid)
		else:
			continue
		if t.fevent or t.fkprobe:
			continue
		key = (m_proc, pid)
		if(key not in ftemp):
			ftemp[key] = []
			ftemp[key].append(aslib.FTraceCallGraph(pid))
		cg = ftemp[key][-1]
		if(cg.addLine(t)):
			ftemp[key].append(aslib.FTraceCallGraph(pid))
	tf.close()

	# add the callgraph data to the device hierarchy
	for key in ftemp:
		proc, pid = key
		for cg in ftemp[key]:
			if len(cg.list) < 1 or cg.invalid:
				continue
			if(not cg.postProcess()):
				print('Sanity check failed for %s-%d' % (proc, pid))
				continue
			# match cg data to devices
			if not data.deviceMatch(cg):
				print ' BAD: %s %s-%d [%f - %f]' % (cg.list[0].name, proc, pid, cg.start, cg.end)

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
	# html function templates
	headline_version = '<div class="version">AnalyzeBoot v%s</div>' % sysvals.version
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
	devtl.createTimeScale(t0, tMax)
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
		.zoombox {position:relative;width:100%;overflow-x:scroll;-webkit-user-select:none;-moz-user-select:none;user-select:none;}\n\
		.timeline {position:relative;font-size:14px;cursor:pointer;width:100%;overflow:hidden;background-color:#dddddd;}\n\
		.thread {position:absolute;height:0%;overflow:hidden;line-height:30px;border:1px solid;text-align:center;white-space:nowrap}\n\
		.thread:hover {border:1px solid red;z-index:10;}\n\
		.hover {background-color:white;border:1px solid red;z-index:10;}\n\
		.phase {position:absolute;overflow:hidden;border:0px;text-align:center;}\n\
		.phaselet {position:absolute;overflow:hidden;border:0px;text-align:center;height:100px;font-size:24px;}\n\
		.t {position:absolute;top:0%;height:100%;border-right:1px solid black;}\n\
		button {height:40px;width:200px;margin-bottom:20px;margin-top:20px;font-size:24px;}\n\
		.logbtn {position:relative;float:right;height:25px;width:50px;margin-top:3px;margin-bottom:0;font-size:10px;text-align:center;}\n\
		#devicedetail {height:100px;box-shadow: 5px 5px 20px black;}\n\
		.version {position:relative;float:left;color:white;font-size:10px;line-height:30px;margin-left:10px;}\n\
	</style>\n</head>\n<body>\n'

	# no header or css if its embedded
	if(not embedded):
		hf.write(html_header)

	# write the test title and general info header
	if(data.stamp['time'] != ""):
		hf.write(headline_version)
		if sysvals.addlogs:
			hf.write('<button id="showdmesg" class="logbtn">dmesg</button>')
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

	# add the dmesg log as a hidden div
	if sysvals.addlogs:
		hf.write('<div id="dmesglog" style="display:none;">\n')
		for line in data.dmesgtext:
			line = line.replace('<', '&lt').replace('>', '&gt')
			hf.write(line)
		hf.write('</div>\n')

	if(not embedded):
		# write the footer and close
		addScriptCode(hf, [data])
		hf.write('</body>\n</html>\n')
	else:
		# embedded out will be loaded in a page, skip the js
		hf.write('<div id=bounds style=display:none>%f,%f</div>' % \
			(data.start*1000, data.initstart*1000))
	hf.close()
	return True

# Function: addScriptCode
# Description:
#	 Adds the javascript code to the output html
# Arguments:
#	 hf: the open html file pointer
#	 testruns: array of Data objects from parseKernelLog or parseTraceLog
def addScriptCode(hf, testruns):
	t0 = testruns[0].start * 1000
	tMax = testruns[-1].end * 1000
	# create an array in javascript memory with the device details
	detail = '	var devtable = [];\n'
	detail += '	var bounds = [%f,%f];\n' % (t0, tMax)
	# add the code which will manipulate the data in the browser
	script_code = \
	script_code = \
	'<script type="text/javascript">\n'+detail+\
	'	var resolution = -1;\n'\
	'	var dragval = [0, 0];\n'\
	'	function redrawTimescale(t0, tMax, tS) {\n'\
	'		var rline = \'<div class="t" style="left:0;border-left:1px solid black;border-right:0;">0ms</div>\';\n'\
	'		var tTotal = tMax - t0;\n'\
	'		var list = document.getElementsByClassName("phase");\n'\
	'		for (var i = 0; i < list.length; i++) {\n'\
	'			var timescale = document.getElementById("timescale");\n'\
	'			var m0 = t0 + (tTotal*parseFloat(list[i].style.left)/100);\n'\
	'			var mTotal = tTotal*parseFloat(list[i].style.width)/100;\n'\
	'			var mMax = m0 + mTotal;\n'\
	'			var html = "";\n'\
	'			var divTotal = Math.floor(mTotal/tS) + 1;\n'\
	'			if(divTotal > 1000) continue;\n'\
	'			var divEdge = (mTotal - tS*(divTotal-1))*100/mTotal;\n'\
	'			var pos = 0.0, val = 0.0;\n'\
	'			for (var j = 0; j < divTotal; j++) {\n'\
	'				var htmlline = "";\n'\
	'				pos = 100 - (((j)*tS*100)/mTotal);\n'\
	'				val = (j)*tS;\n'\
	'				htmlline = \'<div class="t" style="right:\'+pos+\'%">\'+val+\'ms</div>\';\n'\
	'				if(j == 0)\n'\
	'					htmlline = rline;\n'\
	'				html += htmlline;\n'\
	'			}\n'\
	'			timescale.innerHTML = html;\n'\
	'		}\n'\
	'	}\n'\
	'	function zoomTimeline() {\n'\
	'		var dmesg = document.getElementById("dmesg");\n'\
	'		var zoombox = document.getElementById("dmesgzoombox");\n'\
	'		var left = zoombox.scrollLeft;\n'\
	'		var val = parseFloat(dmesg.style.width);\n'\
	'		var newval = 100;\n'\
	'		var sh = window.outerWidth / 2;\n'\
	'		if(this.id == "zoomin") {\n'\
	'			newval = val * 1.2;\n'\
	'			if(newval > 910034) newval = 910034;\n'\
	'			dmesg.style.width = newval+"%";\n'\
	'			zoombox.scrollLeft = ((left + sh) * newval / val) - sh;\n'\
	'		} else if (this.id == "zoomout") {\n'\
	'			newval = val / 1.2;\n'\
	'			if(newval < 100) newval = 100;\n'\
	'			dmesg.style.width = newval+"%";\n'\
	'			zoombox.scrollLeft = ((left + sh) * newval / val) - sh;\n'\
	'		} else {\n'\
	'			zoombox.scrollLeft = 0;\n'\
	'			dmesg.style.width = "100%";\n'\
	'		}\n'\
	'		var tS = [10000, 5000, 2000, 1000, 500, 200, 100, 50, 20, 10, 5, 2, 1];\n'\
	'		var t0 = bounds[0];\n'\
	'		var tMax = bounds[1];\n'\
	'		var tTotal = tMax - t0;\n'\
	'		var wTotal = tTotal * 100.0 / newval;\n'\
	'		var idx = 7*window.innerWidth/1100;\n'\
	'		for(var i = 0; (i < tS.length)&&((wTotal / tS[i]) < idx); i++);\n'\
	'		if(i >= tS.length) i = tS.length - 1;\n'\
	'		if(tS[i] == resolution) return;\n'\
	'		resolution = tS[i];\n'\
	'		redrawTimescale(t0, tMax, tS[i]);\n'\
	'	}\n'\
	'	function deviceName(title) {\n'\
	'		var name = title.slice(0, title.indexOf(" ("));\n'\
	'		return name;\n'\
	'	}\n'\
	'	function deviceHover() {\n'\
	'		var name = deviceName(this.title);\n'\
	'		var dmesg = document.getElementById("dmesg");\n'\
	'		var dev = dmesg.getElementsByClassName("thread");\n'\
	'		var cpu = -1;\n'\
	'		if(name.match("CPU_ON\[[0-9]*\]"))\n'\
	'			cpu = parseInt(name.slice(7));\n'\
	'		else if(name.match("CPU_OFF\[[0-9]*\]"))\n'\
	'			cpu = parseInt(name.slice(8));\n'\
	'		for (var i = 0; i < dev.length; i++) {\n'\
	'			dname = deviceName(dev[i].title);\n'\
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
	'		var name = deviceName(title);\n'\
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
	'		var name = deviceName(this.title);\n'\
	'		var cpu = -1;\n'\
	'		if(name.match("CPU_ON\[[0-9]*\]"))\n'\
	'			cpu = parseInt(name.slice(7));\n'\
	'		else if(name.match("CPU_OFF\[[0-9]*\]"))\n'\
	'			cpu = parseInt(name.slice(8));\n'\
	'		var dmesg = document.getElementById("dmesg");\n'\
	'		var dev = dmesg.getElementsByClassName("thread");\n'\
	'		var idlist = [];\n'\
	'		var pdata = [[]];\n'\
	'		if(document.getElementById("devicedetail1"))\n'\
	'			pdata = [[], []];\n'\
	'		var pd = pdata[0];\n'\
	'		var total = [0.0, 0.0, 0.0];\n'\
	'		for (var i = 0; i < dev.length; i++) {\n'\
	'			dname = deviceName(dev[i].title);\n'\
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
	'					var pname = "<t3 style=\\"font-size:"+fs2+"px\\">"+phases[i].id.replace(new RegExp("_", "g"), " ")+"</t3>";\n'\
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
	'		if(cg.length < 10) return;\n'\
	'		for (var i = 0; i < cg.length; i++) {\n'\
	'			if(idlist.indexOf(cg[i].id) >= 0) {\n'\
	'				cg[i].style.display = "block";\n'\
	'			} else {\n'\
	'				cg[i].style.display = "none";\n'\
	'			}\n'\
	'		}\n'\
	'	}\n'\
	'	function devListWindow(e) {\n'\
	'		var win = window.open();\n'\
	'		var html = "<title>"+e.target.innerHTML+"</title>"+\n'\
	'			"<style type=\\"text/css\\">"+\n'\
	'			"   ul {list-style-type:circle;padding-left:10px;margin-left:10px;}"+\n'\
	'			"</style>"\n'\
	'		var dt = devtable[0];\n'\
	'		if(e.target.id != "devlist1")\n'\
	'			dt = devtable[1];\n'\
	'		win.document.write(html+dt);\n'\
	'	}\n'\
	'	function errWindow() {\n'\
	'		var text = this.id;\n'\
	'		var win = window.open();\n'\
	'		win.document.write("<pre>"+text+"</pre>");\n'\
	'		win.document.close();\n'\
	'	}\n'\
	'	function logWindow(e) {\n'\
	'		var name = e.target.id.slice(4);\n'\
	'		var win = window.open();\n'\
	'		var log = document.getElementById(name+"log");\n'\
	'		var title = "<title>"+document.title.split(" ")[0]+" "+name+" log</title>";\n'\
	'		win.document.write(title+"<pre>"+log.innerHTML+"</pre>");\n'\
	'		win.document.close();\n'\
	'	}\n'\
	'	function onClickPhase(e) {\n'\
	'	}\n'\
	'	function onMouseDown(e) {\n'\
	'		dragval[0] = e.clientX;\n'\
	'		dragval[1] = document.getElementById("dmesgzoombox").scrollLeft;\n'\
	'		document.onmousemove = onMouseMove;\n'\
	'	}\n'\
	'	function onMouseMove(e) {\n'\
	'		var zoombox = document.getElementById("dmesgzoombox");\n'\
	'		zoombox.scrollLeft = dragval[1] + dragval[0] - e.clientX;\n'\
	'	}\n'\
	'	function onMouseUp(e) {\n'\
	'		document.onmousemove = null;\n'\
	'	}\n'\
	'	function onKeyPress(e) {\n'\
	'		var c = e.charCode;\n'\
	'		if(c != 42 && c != 43 && c != 45) return;\n'\
	'		var click = document.createEvent("Events");\n'\
	'		click.initEvent("click", true, false);\n'\
	'		if(c == 43)  \n'\
	'			document.getElementById("zoomin").dispatchEvent(click);\n'\
	'		else if(c == 45)\n'\
	'			document.getElementById("zoomout").dispatchEvent(click);\n'\
	'		else if(c == 42)\n'\
	'			document.getElementById("zoomdef").dispatchEvent(click);\n'\
	'	}\n'\
	'	window.addEventListener("resize", function () {zoomTimeline();});\n'\
	'	window.addEventListener("load", function () {\n'\
	'		var dmesg = document.getElementById("dmesg");\n'\
	'		dmesg.style.width = "100%"\n'\
	'		dmesg.onmousedown = onMouseDown;\n'\
	'		document.onmouseup = onMouseUp;\n'\
	'		document.onkeypress = onKeyPress;\n'\
	'		document.getElementById("zoomin").onclick = zoomTimeline;\n'\
	'		document.getElementById("zoomout").onclick = zoomTimeline;\n'\
	'		document.getElementById("zoomdef").onclick = zoomTimeline;\n'\
	'		var list = document.getElementsByClassName("square");\n'\
	'		for (var i = 0; i < list.length; i++)\n'\
	'			list[i].onclick = onClickPhase;\n'\
	'		var list = document.getElementsByClassName("err");\n'\
	'		for (var i = 0; i < list.length; i++)\n'\
	'			list[i].onclick = errWindow;\n'\
	'		var list = document.getElementsByClassName("logbtn");\n'\
	'		for (var i = 0; i < list.length; i++)\n'\
	'			list[i].onclick = logWindow;\n'\
	'		list = document.getElementsByClassName("devlist");\n'\
	'		for (var i = 0; i < list.length; i++)\n'\
	'			list[i].onclick = devListWindow;\n'\
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

# Function: doError
# Description:
#	 generic error function for catastrphic failures
# Arguments:
#	 msg: the error message to print
#	 help: True if printHelp should be called after, False otherwise
def doError(msg, help=False):
	if(help == True):
		printHelp()
	print('ERROR: %s\n') % msg
	sys.exit()

# Function: printHelp
# Description:
#	 print out the help text
def printHelp():
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
	print('  -h            Print this help text')
	print('  -v            Print the current tool version')
	print('  -dmesg file   Load a stored dmesg file')
	print('  -html file    Html timeline name (default: bootgraph.html)')
	print('  -addlogs      Add the dmesg log to the html output')
	print(' [advanced]')
	print('  -f            Use ftrace to add function detail (default: disabled)')
	print('  -ftrace file  Load a stored ftrace file')
	print('')
	return True

# ----------------- MAIN --------------------
# exec start (skipped if script is loaded as library)
if __name__ == '__main__':
	# loop through the command line arguments
	args = iter(sys.argv[1:])
	for arg in args:
		if(arg == '-h'):
			printHelp()
			sys.exit()
		elif(arg == '-v'):
			print("Version %.1f" % sysvals.version)
			sys.exit()
		elif(arg == '-f'):
			if not analyze_suspend_loaded:
				doError('Missing analyze_suspend.py (required for %s)' % arg, False)
			sysvals.usecallgraph = True
		elif(arg == '-ftrace'):
			try:
				val = args.next()
			except:
				doError('No ftrace file supplied', True)
			if(os.path.exists(val) == False):
				doError('%s doesnt exist' % val)
			sysvals.ftracefile = val
		elif(arg == '-addlogs'):
			sysvals.addlogs = True
		elif(arg == '-dmesg'):
			try:
				val = args.next()
			except:
				doError('No dmesg file supplied', True)
			if(os.path.exists(val) == False):
				doError('%s doesnt exist' % val)
			if(sysvals.htmlfile == val or sysvals.outfile == val):
				doError('Output filename collision')
			sysvals.dmesgfile = val
		elif(arg == '-html'):
			try:
				val = args.next()
			except:
				doError('No HTML filename supplied', True)
			if(sysvals.dmesgfile == val):
				doError('Output filename collision')
			sysvals.htmlfile = val
		else:
			doError('Invalid argument: '+arg, True)

	data = loadKernelLog()
	if sysvals.usecallgraph:
		loadTraceLog(data)

	if(sysvals.outfile and sysvals.phoronix):
		fp = open(sysvals.outfile, 'w')
		fp.write('pass %s initstart %.3f end %.3f boot %s\n' %
			(data.valid, data.initstart*1000, data.end*1000, data.boottime))
		fp.close()
	if(not data.valid):
		if sysvals.dmesgfile:
			doError('No initcall data found in %s' % sysvals.dmesgfile)
		else:
			doError('No initcall data found, is initcall_debug enabled?')

	print('          Host: %s' % sysvals.hostname)
	print('     Test time: %s' % sysvals.testtime)
	print('     Boot time: %s' % data.boottime)
	print('Kernel Version: %s' % sysvals.kernel)
	print('  Kernel start: %.3f' % (data.start * 1000))
	print('    init start: %.3f' % (data.initstart * 1000))

	createBootGraph(data, sysvals.phoronix)
