#!/usr/bin/python
#
# Tool for analyzing an ftrace callgraph
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
#	 Todd Brandt <todd.e.brandt@intel.com>
#

import sys
import time
import os
import string
import re
import array
import platform
import datetime
import struct

class FTraceLine:
	time = 0.0
	length = 0.0
	fcall = False
	freturn = False
	fevent = False
	depth = 0
	name = ""
	def __init__(self, t, m, d):
		self.time = float(t)
		if(d == 'traceevent'):
			self.name = m
			self.fevent = True
			return
		# check to see if this is a trace event
		em = re.match(r"^ *\/\* *(?P<msg>.*) \*\/ *$", m)
		if(em):
			self.name = em.group("msg")
			emm = re.match(r"(?P<call>.*): (?P<msg>.*)", self.name)
			if(emm):
				self.name = emm.group("msg")
			self.fevent = True
			return
		# convert the duration to seconds
		if(d):
			self.length = float(d)/1000000
		# the indentation determines the depth
		match = re.match(r"^(?P<d> *)(?P<o>.*)$", m)
		if(not match):
			return
		self.depth = self.getDepth(match.group('d'))
		m = match.group('o')
		# function return
		if(m[0] == '}'):
			self.freturn = True
			if(len(m) > 1):
				# includes comment with function name
				match = re.match(r"^} *\/\* *(?P<n>.*) *\*\/$", m)
				if(match):
					self.name = match.group('n')
		# function call
		else:
			self.fcall = True
			# function call with children
			if(m[-1] == '{'):
				match = re.match(r"^(?P<n>.*) *\(.*", m)
				if(match):
					self.name = match.group('n')
			# function call with no children (leaf)
			elif(m[-1] == ';'):
				self.freturn = True
				match = re.match(r"^(?P<n>.*) *\(.*", m)
				if(match):
					self.name = match.group('n')
			# something else (possibly a trace marker)
			else:
				self.name = m
	def getDepth(self, str):
		return len(str)/2

class FTraceCallGraph:
	start = -1.0
	end = -1.0
	list = []
	invalid = False
	depth = 0
	stamp = ""
	def __init__(self):
		self.start = -1.0
		self.end = -1.0
		self.list = []
		self.depth = 0
	def setDepth(self, line):
		if(line.fcall and not line.freturn):
			line.depth = self.depth
			self.depth += 1
		elif(line.freturn and not line.fcall):
			self.depth -= 1
			line.depth = self.depth
		else:
			line.depth = self.depth
	def addLine(self, line, match):
		if(not self.invalid):
			self.setDepth(line)
		if(line.depth == 0 and line.freturn):
			self.end = line.time
			self.list.append(line)
			return True
		if(self.invalid):
			return False
		if(len(self.list) >= 1000000 or self.depth < 0):
		   if(len(self.list) > 0):
			   first = self.list[0]
			   self.list = []
			   self.list.append(first)
		   self.invalid = True
		   id = "task %s cpu %s" % (match.group("pid"), match.group("cpu"))
		   window = "(%f - %f)" % (self.start, line.time)
		   if(self.depth < 0):
			   print("Too much data for "+id+" (buffer overflow), ignoring this callback")
		   else:
			   print("Too much data for "+id+" "+window+", ignoring this callback")
		   return False
		self.list.append(line)
		if(self.start < 0):
			self.start = line.time
		return False
	def sanityCheck(self):
		stack = dict()
		cnt = 0
		for l in self.list:
			if(l.fcall and not l.freturn):
				stack[l.depth] = l
				cnt += 1
			elif(l.freturn and not l.fcall):
				if(l.depth not in stack):
					return False
				stack[l.depth].length = l.length
				stack[l.depth] = 0
				l.length = 0
				cnt -= 1
		if(cnt == 0):
			return True
		return False
	def debugPrint(self, filename):
		if(filename == "stdout"):
			print("[%f - %f]") % (self.start, self.end)
			for l in self.list:
				if(l.freturn and l.fcall):
					print("%f (%02d): %s(); (%.3f us)" % (l.time, l.depth, l.name, l.length*1000000))
				elif(l.freturn):
					print("%f (%02d): %s} (%.3f us)" % (l.time, l.depth, l.name, l.length*1000000))
				else:
					print("%f (%02d): %s() { (%.3f us)" % (l.time, l.depth, l.name, l.length*1000000))
			print(" ")
		else:
			fp = open(filename, 'w')
			print(filename)
			for l in self.list:
				if(l.freturn and l.fcall):
					fp.write("%f (%02d): %s(); (%.3f us)\n" % (l.time, l.depth, l.name, l.length*1000000))
				elif(l.freturn):
					fp.write("%f (%02d): %s} (%.3f us)\n" % (l.time, l.depth, l.name, l.length*1000000))
				else:
					fp.write("%f (%02d): %s() { (%.3f us)\n" % (l.time, l.depth, l.name, l.length*1000000))
			fp.close()

# Function: analyzeTraceLog
# Description:
#	 Analyse an ftrace log output file generated from this app during
#	 the execution phase. Create an "ftrace" structure in memory for
#	 subsequent formatting in the html output file
def analyzeTraceLog(file):
	global sysvals

	tracer = ""
	cg = FTraceCallGraph()
	tZero = -1.0

	# read through the ftrace and parse the data
	print("Analyzing the ftrace data...")
	ttypefmt = r"# tracer: (?P<t>.*)"
	stampfmt = r"# (?P<name>.*)-(?P<m>[0-9]{2})(?P<d>[0-9]{2})(?P<y>[0-9]{2})-"+\
				"(?P<H>[0-9]{2})(?P<M>[0-9]{2})(?P<S>[0-9]{2})$"
	linefmt = r"^ *(?P<time>[0-9\.]*) *\| *(?P<cpu>[0-9]*)\)"+\
		" *(?P<proc>.*)-(?P<pid>[0-9]*) *\|"+\
		"[ +!]*(?P<dur>[0-9\.]*) .*\|  (?P<msg>.*)"

	# extract the callgraph and traceevent data
	tf = open(file, 'r')
	for line in tf:
		# remove any latent carriage returns
		line = line.replace("\r\n", "")
		# grab the time stamp first (signifies the start of the test run)
		m = re.match(stampfmt, line)
		if(m):
			dt = datetime.datetime(int(m.group("y"))+2000, int(m.group("m")),
				int(m.group("d")), int(m.group("H")), int(m.group("M")),
				int(m.group("S")))
			cg.stamp = dt.strftime("%B %d %Y, %I:%M:%S %p")
			if(m.group("name")):
				cg.stamp = m.group("name")+" "+cg.stamp
			print cg.stamp
			continue
		# determine the trace data type (required for further parsing)
		m = re.match(ttypefmt, line)
		if(m):
			tracer = m.group("t")
			if(tracer != "function_graph"):
				print("Invalid tracer type: %s" % tracer)
				sys.exit()
			continue
		# parse only valid lines, if this isn't one move on
		m = re.match(linefmt, line)
		if(not m):
			continue
		# gather the basic message data from the line
		m_time = m.group("time")
		m_pid = m.group("pid")
		m_msg = m.group("msg")
		m_param3 = m.group("dur")
		if(m_time and m_pid and m_msg):
			t = FTraceLine(m_time, m_msg, m_param3)
			pid = int(m_pid)
			if(tZero < 0):
				tZero = t.time
		else:
			continue
		# the line should be a call, return, or event
		if(not t.fcall and not t.freturn and not t.fevent):
			continue
		cg.addLine(t, m)
	tf.close()

	# normalize time to start of first line
	cg.start -= tZero
	cg.end -= tZero
	for line in cg.list:
		line.time -= tZero

	return cg

# Function: createHTML
# Description:
#	 Create the output html file.
def createHTML(cg, file):

	hf = open(file, 'w')

	# write the html header first (html head, css code, everything up to the start of body)
	html_header = "<!DOCTYPE html>\n<html>\n<head>\n\
	<meta http-equiv=\"content-type\" content=\"text/html; charset=UTF-8\">\n\
	<title>AnalyzeSuspend</title>\n\
	<style type='text/css'>\n\
		body {overflow-y: scroll;}\n\
		.stamp {width: 100%;text-align:center;background-color:gray;line-height:30px;color:white;font: 25px Arial;}\n\
		.callgraph {margin-top: 30px;box-shadow: 5px 5px 20px black;}\n\
		.callgraph article * {padding-left: 28px;}\n\
		h1 {color:black;font: bold 30px Times;}\n\
		r {color:#500000;font:15px Tahoma;}\n\
		n {color:#505050;font:15px Tahoma;}\n\
		.hide {display: none;}\n\
		.pf {display: none;}\n\
		.pf:checked + label {background: url(\'data:image/svg+xml;utf,<?xml version=\"1.0\" standalone=\"no\"?><svg xmlns=\"http://www.w3.org/2000/svg\" height=\"18\" width=\"18\" version=\"1.1\"><circle cx=\"9\" cy=\"9\" r=\"8\" stroke=\"black\" stroke-width=\"1\" fill=\"white\"/><rect x=\"4\" y=\"8\" width=\"10\" height=\"2\" style=\"fill:black;stroke-width:0\"/><rect x=\"8\" y=\"4\" width=\"2\" height=\"10\" style=\"fill:black;stroke-width:0\"/></svg>\') no-repeat left center;}\n\
		.pf:not(:checked) ~ label {background: url(\'data:image/svg+xml;utf,<?xml version=\"1.0\" standalone=\"no\"?><svg xmlns=\"http://www.w3.org/2000/svg\" height=\"18\" width=\"18\" version=\"1.1\"><circle cx=\"9\" cy=\"9\" r=\"8\" stroke=\"black\" stroke-width=\"1\" fill=\"white\"/><rect x=\"4\" y=\"8\" width=\"10\" height=\"2\" style=\"fill:black;stroke-width:0\"/></svg>\') no-repeat left center;}\n\
		.pf:checked ~ *:not(:nth-child(2)) {display: none;}\n\
	</style>\n</head>\n<body>\n"
	hf.write(html_header)

	hf.write('<div class="stamp">'+cg.stamp+'</div>\n')
	# write the ftrace data (callgraph)
	hf.write('<section id="callgraphs" class="callgraph">\n')
	# write out the ftrace data converted to html
	html_func_top = '<article id="{0}" class="atop" style="background-color:{1}">\n<input type="checkbox" class="pf" id="f{2}" checked/><label for="f{2}">{3} {4}</label>\n'
	html_func_start = '<article>\n<input type="checkbox" class="pf" id="f{0}" checked/><label for="f{0}">{1} {2}</label>\n'
	html_func_end = '</article>\n'
	html_func_leaf = '<article>{0} {1}</article>\n'
	num = 0
	flen = "<r>(%.3f ms, from %.3f to %.3f)</r>" % ((cg.end - cg.start)*1000, cg.start*1000, cg.end*1000)
	hf.write(html_func_top.format("rootnode", "#FFFFCC", num, "ftrace callgraph", flen))
	num += 1
	for line in cg.list:
		if(line.length < 0.000000001):
			flen = "<n>(<1us @ %.3f)</n>" % (line.time*1000)
		else:
			flen = "<n>(%.3f ms @ %.3f)</n>" % (line.length*1000, line.time*1000)
		if(line.freturn and line.fcall):
			hf.write(html_func_leaf.format(line.name, flen))
		elif(line.freturn):
			hf.write(html_func_end)
		else:
			hf.write(html_func_start.format(num, line.name, flen))
			num += 1
	hf.write(html_func_end)
	hf.write("\n\n    </section>\n")
	hf.write("</body>\n</html>\n")
	hf.close()
	return True

def printHelp():
	print("")
	print("FTrace callgraph htmlification")
	print("Usage: ftrace.py <options>")
	print("")
	print("Description:")
	print("  Create an HTML version of an ftrace callgraph")
	print("Options:")
	print("   -h                    Print this help text")
	print("   -ftrace ftracefile    Create HTML callgraph from ftrace file")
	print("")
	return True

def doError(msg, help):
	print("ERROR: %s") % msg
	if(help == True):
		printHelp()
	sys.exit()

if __name__ == '__main__':
	# -- script main --
	# loop through the command line arguments
	args = iter(sys.argv[1:])
	for arg in args:
		if(arg == "-ftrace"):
			try:
				val = args.next()
			except:
				doError("No ftrace file supplied", True)
			m = re.match(r"(?P<name>.*)\.txt$", val)
			htmlfile = "output.html"
			if(m):
				htmlfile = m.group("name")+".html"
			cg = analyzeTraceLog(val)
			createHTML(cg, htmlfile)
		elif(arg == "-h"):
			printHelp()
			sys.exit()
		else:
			doError("Invalid argument: "+arg, True)
