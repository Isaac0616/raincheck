from subprocess import Popen, PIPE
from socket import inet_ntoa
from random import sample
from struct import pack
from glob import glob
from os import unlink
from os.path import abspath
from time import sleep
import re
import jinja2
import webbrowser
import argparse
import json

parser = argparse.ArgumentParser()
parser.add_argument('-u', '--url', default='http://localhost:5000/rc_prime')
parser.add_argument('-a', '--args', default='p=33839528068037464891')
parser.add_argument('-n', '--clients', default=5, type=int)
parser.add_argument('-r', '--repeat', default=10, type=int)
parser.add_argument('-p', '--period', default=1, type=int)
args = parser.parse_args()

def randips(n):
    return [inet_ntoa(pack('!I', i)) for i in sample(xrange(2**32), n)]

ip_dict = {}
processes = []

ips = randips(args.clients*args.repeat)

for i in range(args.repeat):
    for ip in ips[i*args.clients:(i+1)*args.clients]:
        processes.append(Popen(['phantomjs', 'client.js', args.url + '?' + args.args + '&ip=' + ip], stdout=PIPE))

    sleep(args.period)

for p, ip in zip(processes, ips):
    ip_dict[ip] = json.loads(p.communicate()[0])


templateLoader = jinja2.FileSystemLoader(searchpath="./")
templateEnv = jinja2.Environment(loader=templateLoader)
template = templateEnv.get_template('log_template.html')

with open('log.html', 'w') as log:
    log.write(template.render(ip_dict=ip_dict))
webbrowser.open('file://' + abspath('log.html'))
