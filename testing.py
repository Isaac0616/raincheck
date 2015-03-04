from subprocess import Popen, PIPE
from socket import inet_ntoa
from random import sample
from struct import pack
from glob import glob
from os import unlink
from os.path import abspath
import re
import jinja2
import webbrowser
import argparse

parser = argparse.ArgumentParser()
parser.add_argument('-a', '--action')
parser.add_argument('-t', '--target', default='localhost')
parser.add_argument('-p', '--port', default='5000')
args = parser.parse_args()

def randips(n):
    return [inet_ntoa(pack('!I', i)) for i in sample(xrange(2**32), n)]

CLIENTS = 10

if args.action != 'render':
    processes = []
    ips = randips(CLIENTS)

    for file_name in glob('log/*'):
        unlink(file_name)

    for ip in ips:
        processes.append(Popen(['phantomjs', 'client.js', args.target, args.port, ip], stdout=open('log/' + ip, 'w')))

    for p in processes:
        p.wait()

ip_dict = {}
for file_name in glob('log/*'):
    with open(file_name) as f:
        s = f.read()
    ip_dict[file_name[4:]] = re.findall(r'>>> (.*?)\n(.*?)>>>', s, re.DOTALL)


templateLoader = jinja2.FileSystemLoader(searchpath="./")
templateEnv = jinja2.Environment(loader=templateLoader)
template = templateEnv.get_template('log_template.html')

with open('log.html', 'w') as log:
    log.write(template.render(ip_dict=ip_dict))
webbrowser.open('file://' + abspath('log.html'))
