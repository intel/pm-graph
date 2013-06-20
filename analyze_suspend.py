#!/usr/bin/python
#
# Tool for analyzing suspend/resume timing
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
#     Todd Brandt <todd.e.brandt@intel.com>
#
# Description:
#     This tool is designed to assist kernel and OS developers in optimizing
#     their linux stack's suspend/resume time. Using a kernel image built 
#     with a few extra options enabled and a small patch to enable ftrace, 
#     the tool will execute a suspend, and will capture dmesg and ftrace
#     data until resume is complete. This data is transformed into a set of 
#     timelines and a callgraph to give a quick and detailed view of which
#     devices and kernel processes are taking the most time in suspend/resume.
#     
#     The following kernel build options are required:
#         CONFIG_PM_DEBUG=y
#         CONFIG_PM_SLEEP_DEBUG=y
#
#     The following additional kernel parameters are required:
#         (e.g. in file /etc/default/grub)
#         GRUB_CMDLINE_LINUX_DEFAULT="... initcall_debug log_buf_len=16M ..."
#
#     The following simple patch must be applied to enable ftrace data:
#         in file: kernel/power/suspend.c
#         in function: int suspend_devices_and_enter(suspend_state_t state)
#         remove call to "ftrace_stop();"
#         remove call to "ftrace_start();"
#

import sys
import os
import string
import tempfile
import re
import array
import platform
import datetime
from collections import namedtuple

# -- global objects --

class SystemValues:
    testdir = "."
    tpath = "/sys/kernel/debug/tracing/"
    powerfile = "/sys/power/state"
    suspendmode = "mem"
    prefix = "test"
    teststamp = ""
    dmesgfile = ""
    ftracefile = ""
    filterfile = ""
    htmlfile = ""
    def __init__(self):
        hostname = platform.node()
        if(hostname != ""):
            self.prefix = hostname
    def setTestStamp(self):
        self.teststamp = "# "+self.testdir+" "+self.prefix+" "+self.suspendmode
    def setTestFiles(self):
        self.dmesgfile = self.testdir+"/"+self.prefix+"_"+self.suspendmode+"_dmesg.txt"
        self.ftracefile = self.testdir+"/"+self.prefix+"_"+self.suspendmode+"_ftrace.txt"
        self.htmlfile = self.testdir+"/"+self.prefix+"_"+self.suspendmode+".html"
    def setOutputFile(self):
        if((self.htmlfile == "") and (self.dmesgfile != "")):
            m = re.match(r"(?P<name>.*)_dmesg\.txt$", self.dmesgfile)
            if(m):
                self.htmlfile = m.group("name")+".html"
        if((self.htmlfile == "") and (self.ftracefile != "")):
            m = re.match(r"(?P<name>.*)_ftrace\.txt$", self.ftracefile)
            if(m):
                self.htmlfile = m.group("name")+".html"
        if(self.htmlfile == ""):
            self.htmlfile = "output.html"
    def initTestOutput(self):
        self.testdir = os.popen("date \"+suspend-%m%d%y-%H%M%S\"").read().strip()
        self.setTestStamp()
        self.setTestFiles()
        os.mkdir(self.testdir)
sysvals = SystemValues()

class Data:
    useftrace = False
    runtime = False
    notestrun = False
    verbose = False
    longsuspend = []
    phases = []
    timelineinfo = { # output timeline parameters
        'dmesg': {'start': 0.0, 'end': 0.0, 'rows': 0},
        'ftrace': {'start': 0.0, 'end': 0.0, 'rows': 0},
        'stamp': {'time': "", 'host': "", 'mode': ""}
    }
    ftrace = 0 # ftrace log data
    dmesg = { # dmesg log data
        'suspend_general': {'list': dict(), 'start': -1.0,        'end': -1.0,
                             'row': 0,      'color': "#CCFFCC", 'order': 0},
          'suspend_early': {'list': dict(), 'start': -1.0,        'end': -1.0,
                             'row': 0,      'color': "green",   'order': 1},
          'suspend_noirq': {'list': dict(), 'start': -1.0,        'end': -1.0,
                             'row': 0,      'color': "#00FFFF", 'order': 2},
            'suspend_cpu': {'list': dict(), 'start': -1.0,        'end': -1.0,
                             'row': 0,      'color': "blue",    'order': 3},
             'resume_cpu': {'list': dict(), 'start': -1.0,        'end': -1.0,
                             'row': 0,      'color': "red",     'order': 4},
           'resume_noirq': {'list': dict(), 'start': -1.0,        'end': -1.0,
                             'row': 0,      'color': "orange",  'order': 5},
           'resume_early': {'list': dict(), 'start': -1.0,        'end': -1.0,
                             'row': 0,      'color': "yellow",  'order': 6},
         'resume_general': {'list': dict(), 'start': -1.0,        'end': -1.0,
                             'row': 0,      'color': "#FFFFCC", 'order': 7}
    }
    def __init__(self):
        self.phases = self.sortedPhases()
    def vprint(self, msg):
        if(self.verbose):
            print(msg)
    def validActionForPhase(self, phase, action):
        if(phase.startswith("suspend") and (action == "suspend")):
            return True
        if(phase.startswith("resume") and (action == "resume")):
            return True
        if((phase == "resume_runtime") and (action == "rpm_resuming")):
            return True
        return False
    def enableDeferredResume(self):
        self.runtime = True
        self.dmesg['resume_runtime'] = {
            'list': dict(), 'start': -1.0,        'end': -1.0,
             'row': 0,      'color': "#FFFFCC", 'order': 8}
        self.phases = self.sortedPhases()
    def dmesgSortVal(self, phase):
        return self.dmesg[phase]['order']
    def sortedPhases(self):
        return sorted(self.dmesg, key=self.dmesgSortVal)
    def ftraceSortVal(self, pid):
        return self.ftrace[pid]['length']
    def sortedTraces(self):
        return sorted(self.ftrace, key=self.ftraceSortVal, reverse=True)
    def fixupInitcallsThatDidntReturn(self):
        # if any calls never returned, clip them at system resume end
        for phase in self.phases:
            phaselist = self.dmesg[phase]['list']
            for devname in phaselist:
                dev = phaselist[devname]
                if(dev['end'] < 0):
                    dev['end'] = self.dmesg['resume_general']['end']
                    self.vprint("%s (%s): callback didn't return" % (devname, phase))
            if(phase == "resume_general"):
                break
    def identifyDevicesStillSuspended(self):
        # first create a list of device calls for each phase
        devices = {}
        for phase in self.phases:
            devices[phase] = []
            for dev in self.dmesg[phase]['list']:
                devices[phase].append(dev)
        for suspend_phase in self.phases:
            if(suspend_phase.startswith("suspend")):
                resume_phase = suspend_phase.replace("suspend", "resume")
                for dev in self.dmesg[suspend_phase]['list']:
                    if(dev not in self.dmesg[resume_phase]['list']):
                        self.vprint("deferred resume: %s" % (dev))
                        self.longsuspend.append(dev)
data = Data()


# -- functions --

# Function: initFtrace
# Description:
#     Configure ftrace to capture a function trace during suspend/resume
def initFtrace():
    global sysvals

    print("INITIALIZING FTRACE...")
    # turn trace off
    os.system("echo 0 > "+sysvals.tpath+"tracing_on")
    # set the trace clock to global
    os.system("echo global > "+sysvals.tpath+"trace_clock")
    # set trace buffer to a huge value
    os.system("echo nop > "+sysvals.tpath+"current_tracer")
    os.system("echo 10000 > "+sysvals.tpath+"buffer_size_kb")
    # clear the trace buffer
    os.system("echo \"\" > "+sysvals.tpath+"trace")
    # set trace type
    os.system("echo function > "+sysvals.tpath+"current_tracer")
    os.system("echo \"\" > "+sysvals.tpath+"set_ftrace_filter")
    # set the filter list
    tmp = tempfile.NamedTemporaryFile().name
    os.system("cat "+sysvals.tpath+"available_filter_functions | sed -e \"s/ .*//\" > "+tmp)
    tf = open(sysvals.filterfile, 'r')
    for line in tf:
        os.system("cat "+tmp+" | sed -n \"/^"+line[:-1]+"\$/p\" >> "+sysvals.tpath+"set_ftrace_filter")
    os.remove(tmp)

# Function: verifyFtrace
# Description:
#     Check that ftrace is working on the system
def verifyFtrace():
    global sysvals
    files = ["available_filter_functions", "buffer_size_kb",
             "current_tracer", "set_ftrace_filter", 
             "trace", "trace_marker"]
    for f in files:
        if(os.path.exists(sysvals.tpath+f) == False):
            print("ERROR: Missing %s") % (sysvals.tpath+f)
            return False
    return True

# analyzeTraceLog helper functions and classes
# Description:
#     Functions which define and manipulate the data 
#     structures in memory for a parsed ftrace log

KernelCall = namedtuple('KernelCall', 'process, pid, cpu, flags, time, call, parent, depth, length, leaf')
KernelThread = namedtuple('KernelThread', 'list, stack, depth')

def findPrevious(list, kc):
    for c in list:
        if(c.call == kc.call and c.parent == kc.parent):
            return c.depth
    return -1

def parentCall(kc, d):
    return kc._replace(flags="", call=kc.parent, parent="", depth=d)

def returnCall(kc, t, d):
    len = t - kc.time
    return kc._replace(time=t, parent="return", depth=d, length=len)

def calculateCallTime(list, rkc, kc, isleaf):
    if(list.count(rkc)):
       idx = list.index(rkc)
       len = kc.time - list[idx].time
       if(isleaf):
           list[idx] = list[idx]._replace(length=len, leaf=isleaf)
       else:
           list[idx] = list[idx]._replace(length=len)

def stackIndex(stack, name):
    d = 0
    for c in stack:
        if(c.call == name):
            return d
        d += 1
    return -1

def parseStamp(line):
    global data
    stampfmt = r"# suspend-(?P<m>[0-9]{2})(?P<d>[0-9]{2})(?P<y>[0-9]{2})-"+\
                "(?P<H>[0-9]{2})(?P<M>[0-9]{2})(?P<S>[0-9]{2})"+\
                " (?P<host>.*) (?P<mode>.*)$"
    m = re.match(stampfmt, line)
    if(m):
       dt = datetime.datetime(int(m.group("y"))+2000, int(m.group("m")),
            int(m.group("d")), int(m.group("H")), int(m.group("M")),
            int(m.group("S")))
       data.timelineinfo['stamp']['time'] = dt.strftime("%B %d %Y, %I:%M:%S %p")
       data.timelineinfo['stamp']['host'] = m.group("host")
       data.timelineinfo['stamp']['mode'] = m.group("mode") 

# Function: analyzeTraceLog
# Description:
#     Analyse an ftrace log output file generated from this app during
#     the execution phase. Create an "ftrace" structure in memory for
#     subsequent formatting in the html output file
def analyzeTraceLog():
    global sysvals, data

    # ftrace log string templates
    ftrace_suspend_start = r".* (?P<time>[0-9\.]*): tracing_mark_write: SUSPEND START.*"
    ftrace_resume_end = r".* (?P<time>[0-9\.]*): tracing_mark_write: RESUME COMPLETE.*"
    ftrace_line = r" *(?P<proc>.*)-(?P<pid>[0-9]*) *\[(?P<cpu>[0-9]*)\] *"+\
                   "(?P<flags>.{4}) *(?P<time>[0-9\.]*): *"+\
                   "(?P<call>.*) <-(?P<parent>.*)"

    # read through the ftrace and parse the data
    data.ftrace = dict()
    inthepipe = False
    tf = open(sysvals.ftracefile, 'r')
    first = True
    for line in tf:
        if(first):
            first = False
            parseStamp(line)
        # only parse the ftrace data from suspend/resume
        if(inthepipe):
            # look for the resume end marker
            m = re.match(ftrace_resume_end, line)
            if(m):
                data.timelineinfo['ftrace']['end'] = float(m.group("time"))
                if(data.timelineinfo['ftrace']['end'] - data.timelineinfo['ftrace']['start'] > 10000):
                    print("ERROR: corrupted ftrace data\n")
                    print(line)
                    sys.exit()
                inthepipe = False
                break
            m = re.match(ftrace_line, line)
            if(m):
                # parse the line
                kclist = []
                kc = KernelCall(m.group("proc"), int(m.group("pid")), 
                                int(m.group("cpu")), m.group("flags"), 
                                float(m.group("time")), m.group("call"),
                                m.group("parent"), 0, -1.0, False)

                # if the thread is new, initialize some space for it
                if(kc.pid not in data.ftrace):
                    data.ftrace[kc.pid] = {'name': kc.process, 'list': dict(), 
                                      'stack': dict(), 'depth': 0, 'length': 0.0,
                                      'extrareturns': 0}
                    data.ftrace[kc.pid]['list'] = []
                    data.ftrace[kc.pid]['stack'] = []

                kthread = data.ftrace[kc.pid]
                pindex = stackIndex(kthread['stack'], kc.parent)

                # function is a a part of the current callgraph
                if(pindex >= 0):
                    p = len(kthread['stack']) - pindex - 1
                    for i in range(p):
                        rkc = kthread['stack'].pop()
                        calculateCallTime(kthread['list'], rkc, kc, (i == 0))
                        if(i > 0):
                            kclist.append(returnCall(rkc, kc.time, kthread['depth']))
                        kthread['depth'] -= 1
                # function is outside the current callgraph
                elif(kthread['depth'] > 0):
                    pkc = parentCall(kc, kthread['depth'])
                    rkc = kthread['stack'].pop()
                    calculateCallTime(kthread['list'], rkc, kc, True)
                    kthread['stack'].append(pkc)
                    kclist.append(pkc)
                # function out of known scope
                else:
                    pkc = parentCall(kc, kthread['depth'])
                    kthread['stack'].append(pkc)
                    kthread['depth'] += 1
                    kclist.append(pkc)

                # add the current call to the callgraph
                kthread['depth'] += 1
                kc = kc._replace(depth=kthread['depth'])
                kclist.append(kc)
                kthread['stack'].append(kc)

                # add all the entries to the list
                for entry in kclist:
                    kthread['list'].append(entry)
        else:
            # look for the suspend start marker
            m = re.match(ftrace_suspend_start, line)
            if(m):
                inthepipe = True
                data.timelineinfo['ftrace']['start'] = float(m.group("time"))
    tf.close()

    # create lengths for functions that had no return call
    for pid in data.ftrace:
        kthread = data.ftrace[pid]['list']
        missing = 0
        data.ftrace[pid]['row'] = 1
        data.ftrace[pid]['start'] = kthread[0].time
        data.ftrace[pid]['end'] = kthread[-1].time
        data.ftrace[pid]['length'] = kthread[-1].time - kthread[0].time
        for kc in kthread:
            if(kc.length < 0):
                calculateCallTime(data.ftrace[pid]['list'], kc, data.ftrace[pid]['list'][-1], False)
                missing += 1
        data.ftrace[pid]['extrareturns'] = missing

# Function: sortKernelLog
# Description:
#     The dmesg output log sometimes comes with with lines that have
#     timestamps out of order. This could cause issues since a call
#     could accidentally end up in the wrong phase
def sortKernelLog():
    global sysvals
    lf = open(sysvals.dmesgfile, 'r')
    dmesglist = []
    first = True
    for line in lf:
        if(first):
            first = False
            parseStamp(line)
        if(line[0] == '['):
            dmesglist.append(line)
            continue
    lf.close()
    dmesglist.sort()
    return dmesglist

# Function: analyzeKernelLog
# Description:
#     Analyse a dmesg log output file generated from this app during
#     the execution phase. Create a set of device structures in memory 
#     for subsequent formatting in the html output file
def analyzeKernelLog():
    global sysvals, data

    if(os.path.exists(sysvals.dmesgfile) == False):
        print("ERROR: %s doesn't exist") % sysvals.dmesgfile
        return False

    lf = sortKernelLog()
    state = "suspend_runtime"

    cpususpend_start = 0.0
    for line in lf:
        # parse each dmesg line into the time and message
        m = re.match(r"(\[ *)(?P<ktime>[0-9\.]*)(\]) (?P<msg>.*)", line)
        if(m):
            ktime = float(m.group("ktime"))
            msg = m.group("msg")
        else:
            continue

        # ignore everything until we're in a suspend/resume
        if(state not in data.phases):
            # suspend start
            if(re.match(r"PM: Syncing filesystems.*", msg)):
                state = "suspend_general"
                data.dmesg[state]['start'] = ktime
                data.timelineinfo['dmesg']['start'] = ktime
            continue

        # suspend_early
        if(re.match(r"PM: suspend of devices complete after.*", msg)):
            data.dmesg[state]['end'] = ktime
            state = "suspend_early"
            data.dmesg[state]['start'] = ktime
        # suspend_noirq
        elif(re.match(r"PM: late suspend of devices complete after.*", msg)):
            data.dmesg[state]['end'] = ktime
            state = "suspend_noirq"
            data.dmesg[state]['start'] = ktime
        # suspend_cpu
        elif(re.match(r"ACPI: Preparing to enter system sleep state.*", msg)):
            data.dmesg[state]['end'] = ktime
            state = "suspend_cpu"
            data.dmesg[state]['start'] = ktime
        # resume_cpu
        elif(re.match(r"ACPI: Low-level resume complete.*", msg)):
            data.dmesg[state]['end'] = ktime
            state = "resume_cpu"
            data.dmesg[state]['start'] = ktime
        # resume_noirq
        elif(re.match(r"ACPI: Waking up from system sleep state.*", msg)):
            data.dmesg[state]['end'] = ktime
            state = "resume_noirq"
            data.dmesg[state]['start'] = ktime
        # resume_early
        elif(re.match(r"PM: noirq resume of devices complete after.*", msg)):
            data.dmesg[state]['end'] = ktime
            state = "resume_early"
            data.dmesg[state]['start'] = ktime
        # resume_general
        elif(re.match(r"PM: early resume of devices complete after.*", msg)):
            data.dmesg[state]['end'] = ktime
            state = "resume_general"
            data.dmesg[state]['start'] = ktime
        # resume complete
        elif(re.match(r".*Restarting tasks .* done.*", msg)):
            data.dmesg[state]['end'] = ktime
            data.timelineinfo['dmesg']['end'] = ktime
            state = "resume_runtime"
            if(data.runtime):
                break
        # device init call
        elif(re.match(r"calling  (?P<f>.*)\+ @ .*, parent: .*", msg)):
            if(state not in data.phases):
                print("IGNORING - %f: %s") % (ktime, msg)
                continue
            sm = re.match(r"calling  (?P<f>.*)\+ @ (?P<n>.*), parent: (?P<p>.*)", msg);
            f = sm.group("f")
            n = sm.group("n")
            p = sm.group("p")
            am = re.match(r"(?P<p>.*), (?P<a>.*)", p)
            if(am):
                action = am.group("a")
                p = am.group("p")
                if(not data.validActionForPhase(state, action)):
                    continue
            if(f and n and p):
                list = data.dmesg[state]['list']
                list[f] = {'start': ktime, 'end': -1.0, 'n': int(n), 'par': p, 'length': -1, 'row': 0}
        # device init return
        elif(re.match(r"call (?P<f>.*)\+ returned .* after (?P<t>.*) usecs", msg)):
            if(state not in data.phases):
                print("IGNORING - %f: %s") % (ktime, msg)
                continue
            sm = re.match(r"call (?P<f>.*)\+ returned .* after (?P<t>.*) usecs(?P<a>.*)", msg);
            f = sm.group("f")
            t = sm.group("t")
            am = re.match(r", (?P<a>.*)", sm.group("a"))
            if(am):
                action = am.group("a")
                if(not data.validActionForPhase(state, action)):
                    continue
            list = data.dmesg[state]['list']
            if(f in list):
                list[f]['length'] = int(t)
                list[f]['end'] = ktime
        # suspend_cpu - cpu suspends
        elif(state == "suspend_cpu"):
            if(re.match(r"Disabling non-boot CPUs .*", msg)):
                cpususpend_start = ktime
                continue
            m = re.match(r"smpboot: CPU (?P<cpu>[0-9]*) is now offline", msg)
            if(m):
                list = data.dmesg[state]['list']
                cpu = "CPU"+m.group("cpu")
                list[cpu] = {'start': cpususpend_start, 'end': ktime, 
                    'n': 0, 'par': "", 'length': (ktime-cpususpend_start), 'row': 0}
                cpususpend_start = ktime
                continue
        # suspend_cpu - cpu suspends
        elif(state == "resume_cpu"):
            list = data.dmesg[state]['list']
            m = re.match(r"smpboot: Booting Node (?P<node>[0-9]*) Processor (?P<cpu>[0-9]*) .*", msg)
            if(m):
                cpu = "CPU"+m.group("cpu")
                list[cpu] = {'start': ktime, 'end': ktime,
                    'n': 0, 'par': "", 'length': -1, 'row': 0}
                continue
            m = re.match(r"CPU(?P<cpu>[0-9]*) is up", msg)
            if(m):
                cpu = "CPU"+m.group("cpu")
                list[cpu]['end'] = ktime
                list[cpu]['length'] = ktime - list[cpu]['start']
                continue

    data.fixupInitcallsThatDidntReturn()
    data.identifyDevicesStillSuspended()

    return True

# Function: setTimelineRows
# Description:
#     Organize the device or thread lists into the smallest
#     number of rows possible, with no entry overlapping
# Arguments:
#     list: the list to sort (dmesg or ftrace)
#     sortedkeys: sorted key list to use
def setTimelineRows(list, sortedkeys):
    global data

    # clear all rows and set them to undefined
    remaining = len(list)
    for item in list:
        list[item]['row'] = -1

    # try to pack each row with as many ranges as possible
    rowdata = dict()
    row = 0
    while(remaining > 0):
        rowdata[row] = []
        for item in sortedkeys:
            if(list[item]['row'] < 0):
                s = list[item]['start']
                e = list[item]['end']
                valid = True
                for ritem in rowdata[row]:
                    rs = ritem['start']
                    re = ritem['end']
                    if(not (((s <= rs) and (e <= rs)) or ((s >= re) and (e >= re)))):
                        valid = False
                        break
                if(valid):
                    rowdata[row].append(list[item])
                    list[item]['row'] = row
                    remaining -= 1
        row += 1
    return row

# Function: createTimeScale
# Description:
#     Create timescale lines for the dmesg and ftrace timelines
# Arguments:
#     t0: start time (suspend begin)
#     tMax: end time (resume end)
#     tSuspend: time when suspend occurs
def createTimeScale(t0, tMax, tSuspended):
    global data
    timescale = "<div class=\"t\" style=\"right:{0}%\">{1}</div>\n"
    output = ""

    # set scale for timeline
    tTotal = tMax - t0
    tS = 0.1
    if(tTotal > 4):
        tS = 1
    if(tSuspended < 0):
        for i in range(int(tTotal/tS)+1):
            pos = "%0.3f" % (100 - ((float(i)*tS*100)/tTotal))
            if(i > 0):
                val = "%0.f" % (float(i)*tS*1000)
            else:
                val = ""
            output += timescale.format(pos, val)
    else:
        tSuspend = tSuspended - t0
        divTotal = int(tTotal/tS) + 1
        divSuspend = int(tSuspend/tS)
        s0 = (tSuspend - tS*divSuspend)*100/tTotal
        for i in range(divTotal):
            pos = "%0.3f" % (100 - ((float(i)*tS*100)/tTotal) - s0)
            if((i == 0) and (s0 < 3)):
                val = ""
            elif(i == divSuspend):
                val = "S/R"
            else:
                val = "%0.f" % (float(i-divSuspend)*tS*1000)
            output += timescale.format(pos, val)
    return output

class Timeline:
    html = {
        'timeline': "",
        'legend': "",
        'scale': ""
    }

# Function: createHTML
# Description:
#     Create the output html file.
def createHTML():
    global sysvals, data

    # FIRST STEP: ORGANIZE AND FORMAT THE DATA

    # html constants
    row_height_pixels = 15

    # make sure both datasets are over the same time window
    if(data.ftrace and (data.dmesg['suspend_general']['start'] >= 0)):
        if(data.timelineinfo['dmesg']['start'] > data.timelineinfo['ftrace']['start']):
            data.timelineinfo['dmesg']['start'] = data.timelineinfo['ftrace']['start']
        else:
            data.timelineinfo['ftrace']['start'] = data.timelineinfo['dmesg']['start']
        if(data.timelineinfo['dmesg']['end'] < data.timelineinfo['ftrace']['end']):
            data.timelineinfo['dmesg']['end'] = data.timelineinfo['ftrace']['end']
        else:
            data.timelineinfo['ftrace']['end'] = data.timelineinfo['dmesg']['end']

    # html function templates
    headline_stamp = "<div class=\"stamp\">{0} host({1}) mode({2})</div>\n"
    headline_dmesg = "<h1>Kernel {0} Timeline (Suspend time {1} ms, Resume time {2} ms)</h1>\n"
    headline_ftrace = "<h1>Kernel {0} Timeline (Suspend/Resume time {1} ms)</h1>\n"
    html_timeline = "<div id=\"{0}\" class=\"timeline\" style=\"height:{1}px\">\n"
    html_thread = "<div title=\"{0}\" class=\"thread\" style=\"left:{1}%;top:{2}%;width:{3}%\">{4}</div>\n"
    html_device = "<div title=\"{0}\" class=\"thread\" style=\"left:{1}%;top:{2}%;height:{3}%;width:{4}%;\">{5}</div>\n"
    html_phase = "<div class=\"phase\" style=\"left:{0}%;width:{1}%;top:{2}%;height:{3}%;background-color:{4}\">{5}</div>\n"
    html_legend = "<div class=\"square\" style=\"left:{0}%;background-color:{1}\">&nbsp;{2}</div>\n"

    # device timeline (dmesg)
    device_timeline = Timeline()
    timeline_device = ""
    if(data.dmesg['suspend_general']['start'] >= 0):

        # Generate the header for this timeline
        t0 = data.timelineinfo['dmesg']['start']
        tMax = data.timelineinfo['dmesg']['end']
        tTotal = tMax - t0
        suspend_time = "%.0f"%((data.dmesg['suspend_cpu']['end'] - data.dmesg['suspend_general']['start'])*1000)
        resume_time = "%.0f"%((data.dmesg['resume_general']['end'] - data.dmesg['resume_cpu']['start'])*1000)
        timeline_device = headline_dmesg.format("Device", suspend_time, resume_time)

        # determine the maximum number of rows we need to draw
        for phase in data.dmesg:
            list = data.dmesg[phase]['list']
            rows = setTimelineRows(list, list)
            data.dmesg[phase]['row'] = rows
            if(rows > data.timelineinfo['dmesg']['rows']):
                data.timelineinfo['dmesg']['rows'] = rows

        # calculate the timeline height and create its bounding box
	rows = float(data.timelineinfo['dmesg']['rows']) + 1.0
	head_height_percent = 100.0/rows
        timeline_height = int(rows)*row_height_pixels
        timeline_device += html_timeline.format("dmesg", timeline_height);

        # draw the colored boxes for each of the phases
        for b in data.dmesg:
            phase = data.dmesg[b]
            left = "%.3f" % (((phase['start']-data.timelineinfo['dmesg']['start'])*100)/tTotal)
            width = "%.3f" % (((phase['end']-phase['start'])*100)/tTotal)
            timeline_device += html_phase.format(left, width, "%.3f"%head_height_percent, "%.3f"%(100-head_height_percent), data.dmesg[b]['color'], "")

        # draw the time scale, try to make the number of labels readable
        device_timeline.html['scale'] = createTimeScale(t0, tMax, data.dmesg['suspend_cpu']['end'])
        timeline_device += device_timeline.html['scale']
        for b in data.dmesg:
            phaselist = data.dmesg[b]['list']
            for d in phaselist:
                dev = phaselist[d]
                height = (100.0 - head_height_percent)/data.dmesg[b]['row']
                top = "%.3f" % ((dev['row']*height) + head_height_percent)
                left = "%.3f" % (((dev['start']-data.timelineinfo['dmesg']['start'])*100)/tTotal)
                width = "%.3f" % (((dev['end']-dev['start'])*100)/tTotal)
                len = " (%0.3f ms)" % ((dev['end']-dev['start'])*1000)
                color = "rgba(204,204,204,0.5)"
                timeline_device += html_device.format(d+len, left, top, "%.3f"%height, width, d)

        # timeline is finished
        timeline_device += "</div>\n"

        # draw a legend which describes the phases by color
        device_timeline.html['legend'] = "<div class=\"legend\">\n"
        for phase in data.phases:
            if(phase == "resume_runtime"):
                continue
            order = "%.2f" % ((data.dmesg[phase]['order'] * 12.5) + 4.25)
            name = string.replace(phase, "_", " &nbsp;")
            device_timeline.html['legend'] += html_legend.format(order, data.dmesg[phase]['color'], name)
        device_timeline.html['legend'] += "</div>\n"

    # kernel thread timeline (ftrace)
    thread_timeline = Timeline()
    thread_timeline.html['legend'] = device_timeline.html['legend']
    thread_timeline.html['scale'] = device_timeline.html['scale']

    thread_height = 0;
    if(data.ftrace):
        # create a list of pids sorted by thread length
        ftrace_sorted = data.sortedTraces()
        t0 = data.timelineinfo['ftrace']['start']
        tMax = data.timelineinfo['ftrace']['end']
        tTotal = tMax - t0

        # process timeline
        data.timelineinfo['ftrace']['rows'] = setTimelineRows(data.ftrace, ftrace_sorted)
        timeline = headline_ftrace.format("Process", "%.0f" % (tTotal*1000))

        # figure out the overall timeline height
	rows = float(data.timelineinfo['ftrace']['rows']) + 1.0
	head_height_percent2 = 100.0/rows
        timeline_height = int(rows)*row_height_pixels

        timeline += html_timeline.format("ftrace", timeline_height);
        # if dmesg is available, paint the ftrace timeline
        if(data.dmesg['suspend_general']['start'] >= 0):
            for b in data.dmesg:
                phase = data.dmesg[b]
                left = "%.3f" % (((phase['start']-data.timelineinfo['dmesg']['start'])*100)/tTotal)
                width = "%.3f" % (((phase['end']-phase['start'])*100)/tTotal)
                timeline += html_phase.format(left, width, "%.3f"%head_height_percent2, "%.3f"%(100-head_height_percent2), data.dmesg[b]['color'], "")
            timeline += thread_timeline.html['scale']
        else:
            thread_timeline.html['scale'] = createTimeScale(t0, tMax, -1)
            timeline += thread_timeline.html['scale']

        thread_height = (100.0 - head_height_percent2)/data.timelineinfo['ftrace']['rows']
        for pid in ftrace_sorted:
            proc = data.ftrace[pid]
            top = "%.3f" % ((proc['row']*thread_height) + head_height_percent2)
            left = "%.3f" % (((proc['start']-data.timelineinfo['ftrace']['start'])*100)/tTotal)
            width = "%.3f" % ((proc['length']*100)/tTotal)
            len = " (%0.3f ms)" % (proc['length']*1000)
            name = proc['name']
            if(name == "<idle>"):
                name = "idle thread"
            timeline += html_thread.format(name+len, left, top, width, name)
        timeline += "</div>\n"

    # SECOND STEP: CREATE THE HTML FILE AND WRITE THE DATA

    hf = open(sysvals.htmlfile, 'w')

    # write the html header first (html head, css code, everything up to the start of body)
    html_header = "<!DOCTYPE html>\n<html>\n<head>\n\
    <meta http-equiv=\"content-type\" content=\"text/html; charset=UTF-8\">\n\
    <title>AnalyzeSuspend</title>\n\
    <style type='text/css'>\n\
        .stamp {width: 100%; height: 30px;text-align:center;background-color:gray;line-height:30px;color:white;font: 25px Arial;}\n\
        .callgraph {margin-top: 30px;box-shadow: 5px 5px 20px black;}\n\
        .callgraph article * {padding-left: 28px;}\n\
        .pf {display: none;}\n\
        .pf:checked + label {background: url(\'data:image/svg+xml;utf,<?xml version=\"1.0\" standalone=\"no\"?><svg xmlns=\"http://www.w3.org/2000/svg\" height=\"18\" width=\"18\" version=\"1.1\"><circle cx=\"9\" cy=\"9\" r=\"8\" stroke=\"black\" stroke-width=\"1\" fill=\"white\"/><rect x=\"4\" y=\"8\" width=\"10\" height=\"2\" style=\"fill:black;stroke-width:0\"/><rect x=\"8\" y=\"4\" width=\"2\" height=\"10\" style=\"fill:black;stroke-width:0\"/></svg>\') no-repeat left center;}\n\
        .pf:not(:checked) ~ label {background: url(\'data:image/svg+xml;utf,<?xml version=\"1.0\" standalone=\"no\"?><svg xmlns=\"http://www.w3.org/2000/svg\" height=\"18\" width=\"18\" version=\"1.1\"><circle cx=\"9\" cy=\"9\" r=\"8\" stroke=\"black\" stroke-width=\"1\" fill=\"white\"/><rect x=\"4\" y=\"8\" width=\"10\" height=\"2\" style=\"fill:black;stroke-width:0\"/></svg>\') no-repeat left center;}\n\
        .pf:checked ~ *:not(:nth-child(2)) {display: none;}\n\
        .timeline {position: relative; font-size: 14px;cursor: pointer;width: 100%; overflow: hidden; box-shadow: 5px 5px 20px black;}\n\
        .thread {position: absolute; height: "+"%.3f"%thread_height+"%; overflow: hidden; border:1px solid;text-align:center;white-space:nowrap;background-color:rgba(204,204,204,0.5);}\n\
        .thread:hover {background-color:white;border:1px solid red;z-index:10;}\n\
        .phase {position: absolute;overflow: hidden;border:0px;text-align:center;}\n\
        .t {position: absolute; top: 0%; height: 100%; border-right:1px solid black;}\n\
        .legend {position: relative; width: 100%; height: 40px; text-align: center;margin-bottom:20px}\n\
        .legend .square {position:absolute;top:10px; width: 0px;height: 20px;border:1px solid;padding-left:20px;}\n\
    </style>\n</head>\n<body>\n"
    hf.write(html_header)

    # write the test title and general info header
    if(data.timelineinfo['stamp']['time'] != ""):
        hf.write(headline_stamp.format(data.timelineinfo['stamp']['time'], data.timelineinfo['stamp']['host'],
                                       data.timelineinfo['stamp']['mode']))

    # write the dmesg data (device timeline, deferred resume timeline)
    if(data.dmesg['suspend_general']['start'] >= 0):
        hf.write(timeline_device)
        hf.write(device_timeline.html['legend'])

    # write the ftrace data (thread timeline, callgraph)
    if(data.ftrace):
        hf.write(timeline)
        if(timeline_device != ""):
            hf.write(thread_timeline.html['legend'])
        hf.write("<h1>Kernel Process CallGraphs</h1>\n<section class=\"callgraph\">\n")
        # write out the ftrace data converted to html
        html_func_start = "<article>\n<input type=\"checkbox\" class=\"pf\" id=\"f{0}\" checked/><label for=\"f{0}\">{1} {2}</label>\n"
        html_func_end = "</article>\n"
        html_func_leaf = "<article>{0} {1}</article>\n"
        num = 0
        for pid in ftrace_sorted:
            flen = "(%.3f ms)" % (data.ftrace[pid]['length']*1000)
            fname = data.ftrace[pid]['name']
            if(fname == "<idle>"):
                fname = "idle thread"
            hf.write(html_func_start.format(num, fname, flen))
            num += 1
            for kc in data.ftrace[pid]['list']:
                if(kc.length < 0.000001):
                    flen = ""
                else:
                    flen = "(%.3f ms)" % (kc.length*1000)
                if(kc.parent == "return"):
                    hf.write(html_func_end)
                elif(kc.leaf):
                    hf.write(html_func_leaf.format(kc.call, flen))
                else:
                    hf.write(html_func_start.format(num, kc.call, flen))
                    num += 1
            hf.write(html_func_end)
            for i in range(data.ftrace[pid]['extrareturns']):
                hf.write(html_func_end)
        hf.write("\n\n    </section>\n")
    # write the footer and close
    addScriptCode(hf)
    hf.write("</body>\n</html>\n")
    hf.close()
    return True

def addScriptCode(hf):
    script_code = \
    '<script type="text/javascript">\n'\
    '   function deviceDetail() {\n'\
    '       var s = [screen.height/5, screen.width];\n'\
    '       var p = window.open("", "", "height="+s[0]+",width="+s[1]+",");\n'\
    '       p.document.write(\n'\
    '           "<title>"+this.innerText+"</title>"+\n'\
    '           "<h1>"+this.title+"</h1>"\n'\
    '       );\n'\
    '   }\n'\
    '   window.addEventListener("load", function () {\n'\
    '       var dmesg = document.getElementById("dmesg");\n'\
    '       var dev = dmesg.getElementsByClassName("thread");\n'\
    '       for (var i = 0; i < dev.length; i++) {\n'\
    '           dev[i].onclick = deviceDetail;\n'\
    '       }\n'\
    '   });\n'\
    '</script>\n'
    hf.write(script_code);

# Function: suspendSupported
# Description:
#     Verify that the requested mode is supported
def suspendSupported():
    global sysvals

    if(not os.path.exists(sysvals.powerfile)):
        print("%s doesn't exist", sysvals.powerfile)
        return False

    ret = False
    fp = open(sysvals.powerfile, 'r')
    modes = string.split(fp.read())
    for mode in modes:
        if(mode == sysvals.suspendmode):
            ret = True
    fp.close()
    if(not ret):
        print("ERROR: %s mode not supported") % sysvals.suspendmode
        print("Available modes are: %s") % modes
    else:
        print("Using %s mode for suspend") % sysvals.suspendmode
    return ret

# Function: executeSuspend
# Description:
#     Execute system suspend through the sysfs interface
def executeSuspend():
    global sysvals, data

    pf = open(sysvals.powerfile, 'w')
    # clear the kernel ring buffer just as we start
    os.system("dmesg -C")
    # start ftrace
    if(data.useftrace):
        print("START TRACING")
        os.system("echo 1 > "+sysvals.tpath+"tracing_on")
        os.system("echo SUSPEND START > "+sysvals.tpath+"trace_marker")
    # initiate suspend
    print("SUSPEND START")
    pf.write(sysvals.suspendmode)
    # execution will pause here
    pf.close() 
    # return from suspend
    print("RESUME COMPLETE")
    # stop ftrace
    if(data.useftrace):
        os.system("echo RESUME COMPLETE > "+sysvals.tpath+"trace_marker")
        os.system("echo 0 > "+sysvals.tpath+"tracing_on")
        print("CAPTURING FTRACE")
        os.system("echo \""+sysvals.teststamp+"\" > "+sysvals.ftracefile)
        os.system("cat "+sysvals.tpath+"trace >> "+sysvals.ftracefile)
    # grab a copy of the dmesg output
    print("CAPTURING DMESG")
    os.system("echo \""+sysvals.teststamp+"\" > "+sysvals.dmesgfile)
    os.system("dmesg >> "+sysvals.dmesgfile)

    return True

def printHelp():
    global sysvals
    modes = ""
    if(os.path.exists(sysvals.powerfile)):
        fp = open(sysvals.powerfile, 'r')
        modes = string.split(fp.read())
        fp.close()

    exampledir = os.popen("date \"+suspend-%m%d%y-%H%M%S\"").read().strip()
    print("")
    print("AnalyzeSuspend")
    print("Usage: sudo analyze_suspend.py <options>")
    print("")
    print("Description:")
    print("  Initiates a system suspend/resume while capturing dmesg")
    print("  and (optionally) ftrace data to analyze device timing")
    print("")
    print("  Generates output files in subdirectory: suspend-mmddyy-HHMMSS")
    print("    HTML output:                    <hostname>_<mode>.html")
    print("    raw dmesg output:               <hostname>_<mode>_dmesg.txt")
    print("  (with -f option)")
    print("    raw ftrace output:              <hostname>_<mode>_ftrace.txt")
    print("")
    print("    ./%s/%s_%s*.txt/html") % (exampledir, sysvals.prefix, sysvals.suspendmode)
    print("")
    print("Options:")
    print("    -h                     Print this help text")
    print("    -verbose               Print extra information during execution and analysis")
    print("    -dr                    Wait for devices using deferred resume")
    print("  (Execute suspend/resume)")
    print("    -m mode                Mode to initiate for suspend (default: %s)") % sysvals.suspendmode
    if(modes != ""):
        print("                             available modes are: %s") % modes
    print("    -f filterfile          Use ftrace to create html callgraph for list of")
    print("                             functions in filterfile (default: disabled)")
    print("  (Re-analyze data from previous runs)")
    print("    -dmesg  dmesgfile      Create timeline svg from dmesg file")
    print("    -ftrace ftracefile     Create callgraph HTML from ftrace file")
    print("")
    return True

def doError(msg, help):
    print("ERROR: %s") % msg
    if(help == True):
        printHelp()
    sys.exit()

# -- script main --
# loop through the command line arguments
args = iter(sys.argv[1:])
for arg in args:
    if(arg == "-m"):
        try:
            val = args.next()
        except:
            doError("No mode supplied", True)
        sysvals.suspendmode = val
    elif(arg == "-f"):
        try:
            val = args.next()
        except:
            doError("No filter file supplied", True)
        sysvals.filterfile = val
        data.useftrace = True
    elif(arg == "-dr"):
        data.enableDeferredResume()
    elif(arg == "-verbose"):
        data.verbose = True
    elif(arg == "-dmesg"):
        try:
            val = args.next()
        except:
            doError("No dmesg file supplied", True)
        data.notestrun = True
        sysvals.dmesgfile = val
    elif(arg == "-ftrace"):
        try:
            val = args.next()
        except:
            doError("No ftrace file supplied", True)
        data.notestrun = True
        sysvals.ftracefile = val
    elif(arg == "-h"):
        printHelp()
        sys.exit()
    else:
        doError("Invalid argument: "+arg, True)

# if instructed, re-analyze existing data files
if(data.notestrun):
    sysvals.setOutputFile()
    data.vprint("Output file: %s" % sysvals.htmlfile)
    if(sysvals.dmesgfile != ""):
        analyzeKernelLog()
    if(sysvals.ftracefile != ""):
        analyzeTraceLog()
    createHTML()
    sys.exit()

# verify that we can run a test
if(os.environ['USER'] != "root"):
    doError("This script must be run as root", False)
if(not suspendSupported()):
    sys.exit()
if(data.useftrace and not verifyFtrace()):
    sys.exit()

# prepare for the test
if(data.useftrace):
    initFtrace()
sysvals.initTestOutput()

data.vprint("Output files:\n    %s" % sysvals.dmesgfile)
if(data.useftrace):
    data.vprint("    %s" % sysvals.ftracefile)
data.vprint("    %s" % sysvals.htmlfile)

# execute the test
executeSuspend()
analyzeKernelLog()
if(data.useftrace):
    analyzeTraceLog()
createHTML()
