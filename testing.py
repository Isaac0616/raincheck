from subprocess import Popen, PIPE
from socket import inet_ntoa
from random import sample
from struct import pack
from os.path import abspath
from time import sleep
from datetime import datetime
from collections import defaultdict
import jinja2
import webbrowser
import argparse
import json

parser = argparse.ArgumentParser()
parser.add_argument('-u', '--url', default='http://localhost:5000/rc_prime')
parser.add_argument('-a', '--args', default='p=33839528068037464891')
parser.add_argument('-o', '--output', default='log.html')
parser.add_argument('-n', '--clients', default=5, type=int)
parser.add_argument('-r', '--repeat', default=10, type=int)
parser.add_argument('-p', '--period', default=1, type=float)
parser.add_argument('-d', '--detail-log', action='store_true')
parser.add_argument('--open', action='store_true')
args = parser.parse_args()

def randips(n):
    return [inet_ntoa(pack('!I', i)) for i in sample(xrange(2**32), n)]

ip_dict = {}
chart_data = {}
chart_data['Served Time'] = []
chart_data['Average Time Spend'] = []
chart_data['x1'] = []
chart_data['x2'] = []
time_spend = []
processes = []

ips = randips(args.clients*args.repeat)

additional_args = []
if args.detail_log:
    additional_args.append('--detail-log')

for i in range(args.repeat):
    for ip in ips[i*args.clients:(i+1)*args.clients]:
        processes.append(Popen(['phantomjs', 'client.js', args.url + '?' + args.args + '&ip=' + ip] + additional_args, stdout=PIPE))

    sleep(args.period)

for p, ip in zip(processes, ips):
    output = json.loads(p.communicate()[0])
    chart_data['Served Time'].append(output['timeEnd'])
    chart_data['x1'].append(output['timeStart'])
    time_spend.append(output['timeSpend'])

    output['timeEnd'] = datetime.fromtimestamp(output['timeEnd']).strftime("%H:%M:%S.%f")[:-3]
    output['timeStart'] = datetime.fromtimestamp(output['timeStart']).strftime("%H:%M:%S.%f")[:-3]
    ip_dict[ip] = output

test_begin = min(chart_data['x1'])
chart_data['Served Time'] = [round(t - test_begin, 3) for t in chart_data['Served Time']]
chart_data['x1'] = [round(t - test_begin, 3) for t in chart_data['x1']]

tmp_dict = defaultdict(list)
for x, t in zip(chart_data['x1'], time_spend):
    tmp_dict[round(x)].append(t)

for k, l in tmp_dict.iteritems():
    chart_data['x2'].append(k)
    chart_data['Average Time Spend'].append(sum(l)/float(len(l)))

templateLoader = jinja2.FileSystemLoader(searchpath="./")
templateEnv = jinja2.Environment(loader=templateLoader)
if args.detail_log:
    template = templateEnv.get_template('log_template.html')
else:
    template = templateEnv.get_template('statistic_template.html')

with open(args.output, 'w') as log:
    log.write(template.render(ip_dict=ip_dict, chart_data=chart_data))

if args.open:
    webbrowser.open('file://' + abspath(args.output))
