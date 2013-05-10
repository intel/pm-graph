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

# -- global variables --

teststamp = ""
testdir = "."
tpath = "/sys/kernel/debug/tracing/"
powerfile = "/sys/power/state"
suspendmode = "mem"
prefix = "test"
dmesg = {
    'suspend_general': {'list': dict(), 'start': -1.0, 'end': -1.0, 'row': 0, 'color': "#CCFFCC", 'order': 0},
    'suspend_early': {'list': dict(), 'start': -1.0, 'end': -1.0, 'row': 0, 'color': "green", 'order': 1},
    'suspend_noirq': {'list': dict(), 'start': -1.0, 'end': -1.0, 'row': 0, 'color': "#00FFFF", 'order': 2},
    'suspend_cpu': {'list': dict(), 'start': -1.0, 'end': -1.0, 'row': 0, 'color': "blue", 'order': 3},
    'resume_cpu': {'list': dict(), 'start': -1.0, 'end': -1.0, 'row': 0, 'color': "red", 'order': 4},
    'resume_noirq': {'list': dict(), 'start': -1.0, 'end': -1.0, 'row': 0, 'color': "orange", 'order': 5},
    'resume_early': {'list': dict(), 'start': -1.0, 'end': -1.0, 'row': 0, 'color': "yellow", 'order': 6},
    'resume_general': {'list': dict(), 'start': -1.0, 'end': -1.0, 'row': 0, 'color': "#FFFFCC", 'order': 7}
}
useftrace = False
ftrace = 0
timelineinfo = {
    'dmesg': {'start': 0.0, 'end': 0.0, 'rows': 0},
    'ftrace': {'start': 0.0, 'end': 0.0, 'rows': 0},
    'stamp': {'time': "", 'host': "", 'mode': ""}
}

# -- functions --

# Function: initFtrace
# Description:
#     Configure ftrace to capture a function trace during suspend/resume
# Arguments:
#     file: text file containing the list of functions to trace, it's
#           provided by the -f command line argument
def initFtrace(file):
    global tpath, useftrace

    print("INITIALIZING FTRACE...")
    # turn trace off
    os.system("echo 0 > "+tpath+"tracing_on")
    # set trace buffer to a huge value
    os.system("echo nop > "+tpath+"current_tracer")
    os.system("echo 10000 > "+tpath+"buffer_size_kb")
    # clear the trace buffer
    os.system("echo \"\" > "+tpath+"trace")
    # set trace type
    os.system("echo function > "+tpath+"current_tracer")
    os.system("echo \"\" > "+tpath+"set_ftrace_filter")
    # set the filter list
    tmp = tempfile.NamedTemporaryFile().name
    os.system("cat "+tpath+"available_filter_functions | sed -e \"s/ .*//\" > "+tmp)
    tf = open(file, 'r')
    for line in tf:
        os.system("cat "+tmp+" | sed -n \"/^"+line[:-1]+"\$/p\" >> "+tpath+"set_ftrace_filter")
    os.remove(tmp)
    useftrace = True

# Function: verifyFtrace
# Description:
#     Check that ftrace is working on the system
def verifyFtrace():
    global tpath
    files = ["available_filter_functions", "buffer_size_kb",
             "current_tracer", "set_ftrace_filter", 
             "trace", "trace_marker"]
    for f in files:
        if(os.path.exists(tpath+f) == False):
            print("ERROR: Missing %s") % (tpath+f)
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
    global timelineinfo
    stampfmt = r"# suspend-(?P<m>[0-9]{2})(?P<d>[0-9]{2})(?P<y>[0-9]{2})-"+\
                "(?P<H>[0-9]{2})(?P<M>[0-9]{2})(?P<S>[0-9]{2})"+\
                " (?P<host>.*) (?P<mode>.*)$"
    m = re.match(stampfmt, line)
    if(m):
       dt = datetime.datetime(int(m.group("y"))+2000, int(m.group("m")),
            int(m.group("d")), int(m.group("H")), int(m.group("M")),
            int(m.group("S")))
       timelineinfo['stamp']['time'] = dt.strftime("%B %d %Y, %I:%M:%S %p")
       timelineinfo['stamp']['host'] = m.group("host")
       timelineinfo['stamp']['mode'] = m.group("mode") 

# Function: analyzeTraceLog
# Description:
#     Analyse an ftrace log output file generated from this app during
#     the execution phase. Create an "ftrace" structure in memory for
#     subsequent formatting in the html output file
# Arguments:
#     logfile: the ftrace output log file to parse
def analyzeTraceLog(logfile):
    global ftrace, timelineinfo

    # ftrace log string templates
    ftrace_suspend_start = r".* (?P<time>[0-9\.]*): tracing_mark_write: SUSPEND START.*"
    ftrace_resume_end = r".* (?P<time>[0-9\.]*): tracing_mark_write: RESUME COMPLETE.*"
    ftrace_line = r" *(?P<proc>.*)-(?P<pid>[0-9]*) *\[(?P<cpu>[0-9]*)\] *"+\
                   "(?P<flags>.{4}) *(?P<time>[0-9\.]*): *"+\
                   "(?P<call>.*) <-(?P<parent>.*)"

    # read through the ftrace and parse the data
    ftrace = dict()
    inthepipe = False
    tf = open(logfile, 'r')
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
                timelineinfo['ftrace']['end'] = float(m.group("time"))
                if(timelineinfo['ftrace']['end'] - timelineinfo['ftrace']['start'] > 10000):
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
                if(kc.pid not in ftrace):
                    ftrace[kc.pid] = {'name': kc.process, 'list': dict(), 
                                      'stack': dict(), 'depth': 0, 'length': 0.0,
                                      'extrareturns': 0}
                    ftrace[kc.pid]['list'] = []
                    ftrace[kc.pid]['stack'] = []

                kthread = ftrace[kc.pid]
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
                timelineinfo['ftrace']['start'] = float(m.group("time"))
    tf.close()

    # create lengths for functions that had no return call
    for pid in ftrace:
        kthread = ftrace[pid]['list']
        missing = 0
        ftrace[pid]['row'] = 1
        ftrace[pid]['start'] = kthread[0].time
        ftrace[pid]['end'] = kthread[-1].time
        ftrace[pid]['length'] = kthread[-1].time - kthread[0].time
        for kc in kthread:
            if(kc.length < 0):
                calculateCallTime(ftrace[pid]['list'], kc, ftrace[pid]['list'][-1], False)
                missing += 1
        ftrace[pid]['extrareturns'] = missing

# Function: analyzeKernelLog
# Description:
#     Analyse a dmesg log output file generated from this app during
#     the execution phase. Create a set of device structures in memory 
#     for subsequent formatting in the html output file
# Arguments:
#     logfile: the dmesg output log file to parse
def analyzeKernelLog(logfile):
    global dmesg, timelineinfo

    if(os.path.exists(logfile) == False):
        print("ERROR: %s doesn't exist") % logfile
        return False

    lf = open(logfile, 'r')
    state = "unknown"

    first = True
    cpususpend_start = 0.0
    for line in lf:
        if(first):
            first = False
            parseStamp(line)

        if(line[0] != '['):
            continue

        # parse each dmesg line into the time and message
        m = re.match(r"(\[ *)(?P<ktime>[0-9\.]*)(\]) (?P<msg>.*)", line)
        if(m):
            ktime = float(m.group("ktime"))
            msg = m.group("msg")
        else:
            continue

        # ignore everything until we're in a suspend/resume
        if(state == "unknown"):
            # suspend start
            if(re.match(r"PM: Syncing filesystems.*", msg)):
                state = "suspend_general"
                dmesg[state]['start'] = ktime
                timelineinfo['dmesg']['start'] = ktime
            continue

        # suspend_early
        if(re.match(r"PM: suspend of devices complete after.*", msg)):
            dmesg[state]['end'] = ktime
            state = "suspend_early"
            dmesg[state]['start'] = ktime
        # suspend_noirq
        elif(re.match(r"PM: late suspend of devices complete after.*", msg)):
            dmesg[state]['end'] = ktime
            state = "suspend_noirq"
            dmesg[state]['start'] = ktime
        # suspend_cpu
        elif(re.match(r"ACPI: Preparing to enter system sleep state.*", msg)):
            dmesg[state]['end'] = ktime
            state = "suspend_cpu"
            dmesg[state]['start'] = ktime
        # resume_cpu
        elif(re.match(r"ACPI: Low-level resume complete.*", msg)):
            dmesg[state]['end'] = ktime
            state = "resume_cpu"
            dmesg[state]['start'] = ktime
        # resume_noirq
        elif(re.match(r"ACPI: Waking up from system sleep state.*", msg)):
            dmesg[state]['end'] = ktime
            state = "resume_noirq"
            dmesg[state]['start'] = ktime
        # resume_early
        elif(re.match(r"PM: noirq resume of devices complete after.*", msg)):
            dmesg[state]['end'] = ktime
            state = "resume_early"
            dmesg[state]['start'] = ktime
        # resume_general
        elif(re.match(r"PM: early resume of devices complete after.*", msg)):
            dmesg[state]['end'] = ktime
            state = "resume_general"
            dmesg[state]['start'] = ktime
        # resume complete
        elif(re.match(r".*Restarting tasks .* done.*", msg)):
            dmesg[state]['end'] = ktime
            timelineinfo['dmesg']['end'] = ktime
            if(timelineinfo['dmesg']['end'] - timelineinfo['dmesg']['start'] > 10000):
                print("ERROR: corrupted dmesg data\n")
                print(line)
                sys.exit()
            state = "unknown"
            break
        # device init call
        elif(re.match(r"calling  (?P<f>.*)\+ @ .*, parent: .*", msg)):
            sm = re.match(r"calling  (?P<f>.*)\+ @ (?P<n>.*), parent: (?P<p>.*)", msg);
            f = sm.group("f")
            n = sm.group("n")
            p = sm.group("p")
            if(state == "unknown"):
                print("IGNORING - %f: %s") % (ktime, msg)
                continue
            if(f and n and p):
                list = dmesg[state]['list']
                list[f] = {'start': ktime, 'end': -1.0, 'n': int(n), 'par': p, 'length': -1, 'row': 0}
        # device init return
        elif(re.match(r"call (?P<f>.*)\+ returned .* after (?P<t>.*) usecs", msg)):
            sm = re.match(r"call (?P<f>.*)\+ returned .* after (?P<t>.*) usecs", msg);
            f = sm.group("f")
            t = sm.group("t")
            if(state == "unknown"):
                print("IGNORING - %f: %s") % (ktime, msg)
                continue
            list = dmesg[state]['list']
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
                list = dmesg[state]['list']
                cpu = "CPU"+m.group("cpu")
                list[cpu] = {'start': cpususpend_start, 'end': ktime, 
                    'n': 0, 'par': "", 'length': (ktime-cpususpend_start), 'row': 0}
                cpususpend_start = ktime
                continue
        # suspend_cpu - cpu suspends
        elif(state == "resume_cpu"):
            list = dmesg[state]['list']
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
    lf.close()
    # if any calls never returned, set their end to resume end
    for b in dmesg:
        blocklist = dmesg[b]['list']
        for d in blocklist:
            dev = blocklist[d]
            if(dev['end'] < 0):
                dev['end'] = dmesg['resume_general']['end']
    return True

# createHTML helper functions
# Description:
#     Functions which sort and organize the dmesg
#     and ftrace timing data for display
def ftraceSortVal(pid):
    global ftrace
    return ftrace[pid]['length']

def dmesgSortVal(block):
    global dmesg
    return dmesg[block]['order']

def formatDeviceName(bx, by, bw, bh, name):
    tfmt = '<text x=\"{0}\" y=\"{1}\" font-size=\"{2}\">{3}</text>'
    fontsize = 30
    tl = len(name)
    if((tl*fontsize/3) > bw):
        fontsize = (3*bw)/(2*tl);
    line = tfmt.format(bx+(bw/2)-(tl*fontsize/5), by+(bh/3), fontsize, name)
    return line

# Function: setTimelineRows
# Description:
#     Organize the device or thread lists into the smallest
#     number of rows possible, with no entry overlapping
# Arguments:
#     list: the list to sort (dmesg or ftrace)
#     sortedkeys: sorted key list to use
def setTimelineRows(list, sortedkeys):
    global timelineinfo

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
    global dmesg, timelineinfo
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

# Function: createHTML
# Description:
#     Create the output html file.
# Arguments:
#     htmlfile: the output filename
def createHTML(htmlfile):
    global dmesg, ftrace, timelineinfo

    # make sure both datasets are over the same time window
    if(ftrace and (dmesg['suspend_general']['start'] >= 0)):
        if(timelineinfo['dmesg']['start'] > timelineinfo['ftrace']['start']):
            timelineinfo['dmesg']['start'] = timelineinfo['ftrace']['start']
        else:
            timelineinfo['ftrace']['start'] = timelineinfo['dmesg']['start']
        if(timelineinfo['dmesg']['end'] < timelineinfo['ftrace']['end']):
            timelineinfo['dmesg']['end'] = timelineinfo['ftrace']['end']
        else:
            timelineinfo['ftrace']['end'] = timelineinfo['dmesg']['end']

    # html function templates
    html_func_start = "<article>\n<input type=\"checkbox\" \
class=\"pf\" id=\"f{0}\" checked/><label for=\"f{0}\">{1} {2}</label>\n"
    html_func_end = "</article>\n"
    html_func_leaf = "<article>{0} {1}</article>\n"
    headline_stamp = "<div class=\"stamp\">{0} host({1}) mode({2})</div>\n"
    headline_dmesg = "<h1>Kernel {0} Timeline (Suspend time {1} ms, Resume time {2} ms)</h1>\n"
    headline_ftrace = "<h1>Kernel {0} Timeline (Suspend/Resume time {1} ms)</h1>\n"
    html_timeline = "<div id=\"{0}\" class=\"timeline\" style=\"height:{1}px\">\n"
    html_thread = "<div title=\"{0}\" class=\"thread\" style=\"left:{1}%;top:{2}%;width:{3}%\">{4}</div>\n"
    html_device = "<div title=\"{0}\" class=\"thread\" style=\"left:{1}%;top:{2}%;height:{3}%;width:{4}%;\">{5}</div>\n"
    html_block = "<div class=\"block\" style=\"left:{0}%;width:{1}%;background-color:{2}\">{3}</div>\n"
    html_legend = "<div class=\"square\" style=\"left:{0}%;background-color:{1}\">&nbsp;{2}</div>\n"

    # device timeline
    timeline_device = ""
    timeline_device_legend = ""
    timescale = ""
    if(dmesg['suspend_general']['start'] >= 0):
        # basic timing events
        t0 = timelineinfo['dmesg']['start']
        tMax = timelineinfo['dmesg']['end']
        tTotal = tMax - t0
        suspend_time = "%.0f"%((dmesg['suspend_cpu']['end'] - dmesg['suspend_general']['start'])*1000)
        resume_time = "%.0f"%((dmesg['resume_general']['end'] - dmesg['resume_cpu']['start'])*1000)

        timeline_device = headline_dmesg.format("Device", suspend_time, resume_time)
        for block in dmesg:
            list = dmesg[block]['list']
            rows = setTimelineRows(list, list)
            dmesg[block]['row'] = rows
            if(rows > timelineinfo['dmesg']['rows']):
                timelineinfo['dmesg']['rows'] = rows
        timeline_height = (timelineinfo['dmesg']['rows']+1)*40
        timeline_device += html_timeline.format("dmesg", timeline_height);
        for b in dmesg:
            block = dmesg[b]
            left = "%.3f" % (((block['start']-timelineinfo['dmesg']['start'])*100)/tTotal)
            width = "%.3f" % (((block['end']-block['start'])*100)/tTotal)
            timeline_device += html_block.format(left, width, dmesg[b]['color'], "")
        timescale = createTimeScale(t0, tMax, dmesg['suspend_cpu']['end'])
        timeline_device += timescale
        for b in dmesg:
            blocklist = dmesg[b]['list']
            for d in blocklist:
                dev = blocklist[d]
                height = 97.0/dmesg[b]['row']
                top = "%.3f" % ((dev['row']*height)+3)
                left = "%.3f" % (((dev['start']-timelineinfo['dmesg']['start'])*100)/tTotal)
                width = "%.3f" % (((dev['end']-dev['start'])*100)/tTotal)
                len = " (%0.3f ms)" % ((dev['end']-dev['start'])*1000)
                color = "rgba(204,204,204,0.5)"
                timeline_device += html_device.format(d+len, left, top, "%.3f"%height, width, d)
        timeline_device += "</div>\n"
        timeline_device_legend = "<div class=\"legend\">\n"
        block_sorted = sorted(dmesg, key=dmesgSortVal)
        for block in block_sorted:
            order = "%.2f" % ((dmesg[block]['order'] * 12.5) + 4.25)
            name = string.replace(block, "_", " &nbsp;")
            timeline_device_legend += html_legend.format(order, dmesg[block]['color'], name)
        timeline_device_legend += "</div>\n"

    thread_height = 0;
    if(ftrace):
        # create a list of pids sorted by thread length
        ftrace_sorted = sorted(ftrace, key=ftraceSortVal, reverse=True)
        t0 = timelineinfo['ftrace']['start']
        tMax = timelineinfo['ftrace']['end']
        tTotal = tMax - t0
        # process timeline
        timelineinfo['ftrace']['rows'] = setTimelineRows(ftrace, ftrace_sorted)
        timeline = headline_ftrace.format("Process", "%.0f" % (tTotal*1000))
        timeline_height = (timelineinfo['ftrace']['rows']+1)*40
        timeline += html_timeline.format("ftrace", timeline_height);
        # if dmesg is available, paint the ftrace timeline
        if(dmesg['suspend_general']['start'] >= 0):
            for b in dmesg:
                block = dmesg[b]
                left = "%.3f" % (((block['start']-timelineinfo['dmesg']['start'])*100)/tTotal)
                width = "%.3f" % (((block['end']-block['start'])*100)/tTotal)
                timeline += html_block.format(left, width, dmesg[b]['color'], "")
            timeline += timescale
        else:
            timeline += createTimeScale(t0, tMax, -1)

        thread_height = 97.0/timelineinfo['ftrace']['rows']
        for pid in ftrace_sorted:
            proc = ftrace[pid]
            top = "%.3f" % ((proc['row']*thread_height)+3)
            left = "%.3f" % (((proc['start']-timelineinfo['ftrace']['start'])*100)/tTotal)
            width = "%.3f" % ((proc['length']*100)/tTotal)
            len = " (%0.3f ms)" % (proc['length']*1000)
            name = proc['name']
            if(name == "<idle>"):
                name = "idle thread"
            timeline += html_thread.format(name+len, left, top, width, name)
        timeline += "</div>\n"

    # html header, footer, and css code
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
        .block {position: absolute;top: 3%;height: 97%;overflow: hidden;border:0px;text-align:center;}\n\
        .t {position: absolute; top: 0%; height: 100%; border-right:1px solid black;}\n\
        .legend {position: relative; width: 100%; height: 40px; text-align: center;margin-bottom:20px}\n\
        .legend .square {position:absolute;top:10px; width: 0px;height: 20px;border:1px solid;padding-left:20px;}\n\
    </style>\n</head>\n<body>\n"

    # write the header first
    hf = open(htmlfile, 'w')
    hf.write(html_header)
    if(timelineinfo['stamp']['time'] != ""):
        hf.write(headline_stamp.format(timelineinfo['stamp']['time'], timelineinfo['stamp']['host'],
                                       timelineinfo['stamp']['mode']))
    # write the data that's available
    if(timeline_device != ""):
        hf.write(timeline_device)
        hf.write(timeline_device_legend)
    if(ftrace):
        hf.write(timeline)
        if(timeline_device != ""):
            hf.write(timeline_device_legend)
        hf.write("<h1>Kernel Process CallGraphs</h1>\n<section class=\"callgraph\">\n")
        # write out the ftrace data converted to html
        num = 0
        for pid in ftrace_sorted:
            flen = "(%.3f ms)" % (ftrace[pid]['length']*1000)
            fname = ftrace[pid]['name']
            if(fname == "<idle>"):
                fname = "idle thread"
            hf.write(html_func_start.format(num, fname, flen))
            num += 1
            for kc in ftrace[pid]['list']:
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
            for i in range(ftrace[pid]['extrareturns']):
                hf.write(html_func_end)
        hf.write("\n\n    </section>\n")
    # write the footer and close
    hf.write("</body>\n</html>\n")
    hf.close()
    return True

# Function: generateSVG (deprecated)
# Description:
#     Create the output svg file.
# Arguments:
#     svgfile: the output svg file
#      target: the device to highlight
def generateSVG(svgfile, target):
    global dmesg, timelineinfo

    targetlist = []
    if(target != ""):
        for b in dmesg:
            list = dmesg[b]['list']
            t = target
            while(t in list):
                targetlist.append(t)
                t = list[t]['par']

    total_rows = 0
    for block in dmesg:
        list = dmesg[block]['list']
        rows = setTimelineRows(list, list)
        dmesg[block]['row'] = rows
        if(rows > total_rows):
            total_rows = rows

    # svg size
    svgw = 1920
    svgh = 1080
    # calculate font size from svg size
    svgf = svgh/50
    svgr = 94/float(total_rows)

    # begin the file with a white background
    sf = open(svgfile, 'w')
    sf.write("<!-- resume graphical output -->\n")
    sf.write('<svg xmlns=\"http://www.w3.org/2000/svg\" \
              width=\"{0}\" height=\"{1}\">\n'.format(svgw, svgh))
    sf.write("<rect width=\"100%\" height=\"100%\" fill=\"white\"/>\n")

    
    # calculate the time scale values
    total_time = dmesg['resume_general']['end'] - dmesg['suspend_general']['start']
    timewindow = float(int(10*total_time)+1)/10
    if(timewindow >= 5):
        tdiv = 0.5
    elif(timewindow >= 1):
        tdiv = 1.0
    elif(timewindow > 0.5):
        tdiv = 5.0
    else:
        tdiv = 10.0
    dx = 98/float(timewindow*tdiv*10)
    trange = int(timewindow*tdiv*10) + 1

    # draw resume block timeline
    rfmt = '<rect x=\"{0}%\" y=\"{1}%\" width=\"{2}%\" height=\"{3}%\" style=\"fill:{4};stroke:black;stroke-width:1\"/>\n'
    t0 = timelineinfo['dmesg']['start']
    for d in dmesg:
        val = dmesg[d];
        c = val['color']
        x = ((val['start'] - t0)/ timewindow) * 98.0
        w = (((val['end'] - t0)/ timewindow) * 98.0) - x
        y = val['row']*svgr + 5
        if(d in targetlist):
            c = "green"
        sf.write(rfmt.format(x+0.2, 0, w, 100, c))

    # draw the time scale to the nearest 10th of a second
    x = 0.2
    tfmt = '<text x=\"{0}%\" y=\"{1}\" font-size=\"{2}\">{3}</text>\n'
    for i in range(trange):
        n = float(i)/(10*tdiv)
        if((timewindow >= 1) and (int(n)/1 == float(n)/1)):
            line = tfmt.format(x, svgf, svgf, n)
        elif((timewindow < 1) and (int(n*10)/1 == float(n*10)/1)):
            line = tfmt.format(x, svgf, svgf, n)
        else:
            line = tfmt.format(x, svgf*0.9, svgf*0.8, n)
        sf.write(line)
        x += dx

    # draw resume device timeline
    for block in dmesg:
        list = dmesg[block]['list']
        for i in list:
            val = list[i]
            c = dmesg[block]['color']
            x = ((val['start'] - t0)/ timewindow) * 98.0
            w = (((val['end'] - t0)/ timewindow) * 98.0) - x
            y = val['row']*svgr + 5
            if(d in targetlist):
                c = "green"
            sf.write(rfmt.format(x+0.2, y, w, svgr, c))
            if(w > 0.5):
                line = formatDeviceName(x*float(svgw)/100, y*float(svgh)/100,
                                        w*float(svgw)/100, svgr*float(svgw)/100, i)
                sf.write(line)
    sf.write("</svg>\n")
    sf.close()
    return True

# Function: suspendSupported
# Description:
#     Verify that the requested mode is supported
# Arguments:
#     suspendmode: the suspend mode (mem, disk)
def suspendSupported(suspendmode):
    global powerfile

    fp = open(powerfile, 'r')
    ret = False
    modes = string.split(fp.read())
    for mode in modes:
        if(mode == suspendmode):
            ret = True
    fp.close()
    if(ret == False):
        print("ERROR: %s mode not supported") % suspendmode
        print("Available modes are: %s") % modes
    else:
        print("Using %s mode for suspend") % suspendmode
    return ret

# Function: executeSuspend
# Description:
#     Execute system suspend through the sysfs interface
# Arguments:
#     suspendmode: the suspend mode (mem, disk)
#     dmesgfile: dmesg output file to capture
#     ftracefile: ftrace output file to capture
def executeSuspend(suspendmode, dmesgfile, ftracefile):
    global powerfile, tpath, useftrace, teststamp

    pf = open(powerfile, 'w')
    # clear the kernel ring buffer just as we start
    os.system("dmesg -C")
    # start ftrace
    if(useftrace):
        print("START TRACING")
        os.system("echo 1 > "+tpath+"tracing_on")
        os.system("echo SUSPEND START > "+tpath+"trace_marker")
    # initiate suspend
    print("SUSPEND START")
    pf.write(suspendmode)
    # execution will pause here
    pf.close() 
    # return from suspend
    print("RESUME COMPLETE")
    # stop ftrace
    if(useftrace):
        os.system("echo RESUME COMPLETE > "+tpath+"trace_marker")
        os.system("echo 0 > "+tpath+"tracing_on")
        print("CAPTURING FTRACE")
        os.system("echo \""+teststamp+"\" > "+ftracefile)
        os.system("cat "+tpath+"trace >> "+ftracefile)
    # grab a copy of the dmesg output
    print("CAPTURING DMESG")
    os.system("echo \""+teststamp+"\" > "+dmesgfile)
    os.system("dmesg >> "+dmesgfile)

    return True

def createTestDir():
    global testdir
    testdir = os.popen("date \"+suspend-%m%d%y-%H%M%S\"").read().strip()
    os.mkdir(testdir)

def printHelp():
    global powerfile, prefix, suspendmode
    modes = ""
    if(os.path.exists(powerfile)):
        fp = open(powerfile, 'r')
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
    print("    ./%s/%s_%s*.txt/html") % (exampledir, prefix, suspendmode)
    print("")
    print("Options:")
    print("    -h                     Print this help text")
    print("  (Execute suspend/resume)")
    print("    -m mode                Mode to initiate for suspend (default: %s)") % suspendmode
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

analyze_dmesg = ""
analyze_ftrace = ""
analyze_outfile = ""
filterfile = ""

hostname = platform.node()
if(hostname != ""):
    prefix = hostname

# loop through the command line arguments
args = iter(sys.argv[1:])
for arg in args:
    if(arg == "-m"):
        try:
            val = args.next()
        except:
            doError("No mode supplied", True)
        suspendmode = val
    elif(arg == "-f"):
        try:
            val = args.next()
        except:
            doError("No filter file supplied", True)
        filterfile = val
    elif(arg == "-dmesg"):
        try:
            val = args.next()
        except:
            doError("No dmesg file supplied", True)
        analyze_dmesg = val
        if(analyze_outfile == ""):
            m = re.match(r"(?P<name>.*)_dmesg\.txt$", analyze_dmesg)
            if(m):
                analyze_outfile = m.group("name")+".html"
    elif(arg == "-ftrace"):
        try:
            val = args.next()
        except:
            doError("No ftrace file supplied", True)
        analyze_ftrace = val
        if(analyze_outfile == ""):
            m = re.match(r"(?P<name>.*)_ftrace\.txt$", analyze_ftrace)
            if(m):
                analyze_outfile = m.group("name")+".html"
    elif(arg == "-h"):
        printHelp()
        sys.exit()
    else:
        doError("Invalid argument: "+arg, True)

# we can re-analyze in user mode
if((analyze_dmesg != "") or (analyze_ftrace != "")):
    if(analyze_outfile == ""):
        analyze_outfile = "test.html"
    if(analyze_dmesg != ""):
        analyzeKernelLog(analyze_dmesg)
    if(analyze_ftrace != ""):
        analyzeTraceLog(analyze_ftrace)
    createHTML(analyze_outfile)
    sys.exit()

# everything past this point requires root access
if(os.environ['USER'] != "root"):
    doError("This script must be run as root", False)

if(os.path.exists(powerfile) == False):
    doError(powerfile+" doesn't exist", False)

if(suspendSupported(suspendmode) == False):
    sys.exit()

# initialization
if(filterfile != ""):
    if(verifyFtrace()):
        initFtrace(filterfile)
    else:
        sys.exit()

createTestDir()
teststamp = "# "+testdir+" "+prefix+" "+suspendmode
dmesgfile = testdir+"/"+prefix+"_"+suspendmode+"_dmesg.txt"
ftracefile = testdir+"/"+prefix+"_"+suspendmode+"_ftrace.txt"
htmlfile = testdir+"/"+prefix+"_"+suspendmode+".html"

# execution
executeSuspend(suspendmode, dmesgfile, ftracefile)
analyzeKernelLog(dmesgfile)
if(useftrace):
    analyzeTraceLog(ftracefile)
createHTML(htmlfile)
