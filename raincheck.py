from blist import sortedlist
from functools import wraps
from multiprocessing import Process, Lock, Condition, Event, cpu_count
from multiprocessing.managers import BaseManager
from flask import copy_current_request_context, abort, make_response, request, render_template, render_template_string
from base64 import b64encode
import dill
import hmac, hashlib
import time
import threading
import os
import struct
import socket
import sys

INF = 2147483647

class Job():
    def __init__(self, priority, target, *args, **keywords):
        self.priority = priority
        self.target = target
        self.args = args
        self.keywords = keywords
        self.result = None
        self.state = 'initial'
        self.exception = None
        self.finish = Event()

    def get_result(self):
        self.finish.wait()
        return (self.result, self.state, self.exception)

    def execute(self):
        try:
            self.state = 'executing'
            self.result = dill.loads(self.target)(*self.args, **self.keywords)
        except:
            self.state = 'error'
            self.exception = sys.exc_info()[1]
        else:
            self.state = 'done'
        finally:
            self.finish.set()

    def cancel(self):
        self.state = 'cancel'
        self.finish.set()

    def get_priority(self):
        return self.priority


class JobManager(BaseManager):
    pass

JobManager.register('Job', Job)


class JobQueue():
    def __init__(self, max_size):
        self.queue = sortedlist(key=lambda x: x.get_priority())
        self.max_size = max_size
        self.mutex = Lock()
        self.not_empty = Condition(self.mutex)
        self.manager = JobManager()
        self.manager.start()

    def enqueue(self, priority, target, *args, **keywords):
        with self.mutex:
            job = self.manager.Job(priority, target, *args, **keywords)
            self.queue.add(job)
            if len(self.queue) > self.max_size:
                unfinish_job = self.queue.pop(-1)
                unfinish_job.cancel()
            self.not_empty.notify()
        return job.get_result()

    def get_job(self):
        with self.not_empty:
            if len(self.queue) == 0:
                self.not_empty.wait()
            return self.queue.pop(0)

    def __contains__(self, item):
        return item in self.queue


class JobQueueManager(BaseManager):
    pass

JobQueueManager.register('JobQueue', JobQueue)


def _work(queue):
    while True:
        job = queue.get_job()
        job.execute()


class ExpireSet():
    def __init__(self, expire_time):
        self.set = set()
        self.expire_time = expire_time
        self.mutex = Lock()

    def remove(self, value):
        with self.mutex:
            self.set.remove(value)

    def add(self, value, expire_time=None):
        if not expire_time:
            expire_time = self.expire_time
        with self.mutex:
            self.set.add(value)
        if expire_time > 0:
            t = threading.Timer(expire_time, self.remove, args=(value, ))
            t.start()

    def __contains__(self, value):
        with self.mutex:
            return value in self.set

    def __str__(self):
        return str(self.set)


class FMSketch():
    def __init__(self, time_interval):
        self.time_interval = time_interval
        self._sketch_size = 32
        self.array = [{'priority': 0, 'modify_time': 0} for i in range(self._sketch_size)]
        self.mutex = Lock()

    def add(self, client_id, priority):
        current_time = time.time()
        with self.mutex:
            bucket = self.array[self._trailing_zeros(client_id)]
            if bucket['modify_time'] < current_time - self.time_interval or bucket['priority'] > priority:
                bucket['priority'] = priority
                bucket['modify_time'] = current_time

    def rank(self, priority):
        current_time = time.time()
        with self.mutex:
            for i in range(self._sketch_size):
                if self.array[i]['modify_time'] < current_time - self.time_interval or \
                   self.array[i]['priority'] >= priority:
                       return (2**i)*1.2928

    def _trailing_zeros(self, client_id):
        binary = bin(self._ip2int(client_id))
        return len(binary) - binary.rfind('1') - 1

    def _ip2int(self, ip):
        return struct.unpack("!I", socket.inet_aton(ip))[0]

    def __str__(self):
        return str(self.array)


registered = {}

class RainCheck():
    def __init__(self, name, queue_size, time_pause, time_interval, workers=cpu_count(), key=os.urandom(16)):
        self.name = name
        self.queue_size = queue_size
        self.time_pause = time_pause
        self.time_interval = time_interval
        self.max_age = self.time_pause + self.time_interval
        self.workers = workers
        self.key = key

        self.manager = JobQueueManager()
        self.manager.start()
        self.queue = self.manager.JobQueue(self.queue_size)
        self.accepted = ExpireSet(self.max_age)
        self.buffered = ExpireSet(-1)
        self.fms = FMSketch(self.max_age)

        self.worker_pool = [Process(target=_work, args=(self.queue, )) for i in range(self.workers)]
        for worker in self.worker_pool:
            worker.start()

    def enqueue(self, client_id, priority, target, *args, **keywords):
        self.fms.add(client_id, priority)
        #need try except
        self.buffered.add(client_id)
        result = self.queue.enqueue(priority, target, *args, **keywords)
        self.buffered.remove(client_id)
        if result[1] == 'done':
            self.accepted.add(client_id)
        return result

    def validate(self, client_id, timestamp, time_start, time_end, mac):
        if not hmac.compare_digest(b64encode(hmac.new(self.key, '#'.join([client_id, timestamp, time_start, time_end]), hashlib.sha256).digest()), str(mac)):
            return 'MAC verification fail'
        if request.remote_addr != client_id:
            return 'Client ID mismatch'
        current_time = time.time()
        if current_time < float(time_start) or current_time > float(time_end):
            return 'Not in the lifetime'
        if client_id in self.buffered:
            return 'Request is in Buffered'
        if client_id in self.accepted:
            return 'Request is in Accepted'

    def issue(self, timestamp=None):
        current_time = time.time()
        time_start = current_time + self.time_pause
        time_end = time_start + self.time_interval
        if timestamp == None:
            message = '#'.join([request.remote_addr, str(current_time), str(time_start), str(time_end)])
        else:
            message = '#'.join([request.remote_addr, timestamp, str(time_start), str(time_end)])
        return message + '#' + b64encode(hmac.new(self.key, message, hashlib.sha256).digest())

    def rank(self, priority):
        return self.fms.rank(priority)


def register(name, queue_size, time_pause, time_interval, workers, key):
    registered[name] = RainCheck(name, queue_size, time_pause, time_interval, workers, key)

default_template = '''
<html>
  <head>
    <script>
      document.addEventListener("DOMContentLoaded", function(event) {{
        document.getElementById('cookies').innerHTML += document.cookie;
      }});
    </script>
  </head>
  <body>
    <h1>{status}</h1>
    <p id='cookies'><b>cookies:</b><br></p>
    <p><b>rank:</b><br>{rank}</p>
    <p><b>details:</b><br>{detail}</p>
  </body>
</html>
'''

def raincheck(name, template=None):
    def decorator(func):
        @wraps(func)
        def decorated_func(*args, **keywords):
            rc = registered[name]

            # TODO adjust refresh time by time_apuse, time_interval
            if request.cookies.get('raincheck#' + request.path) == None:
                resp = make_response(default_template.format(status='First time request', detail='Get the raincheck', rank=rc.rank(INF)))
                resp.headers['Refresh'] = 2
                resp.set_cookie('raincheck#' + request.path, rc.issue(), max_age=rc.max_age)
                return resp

            # may need to clear cookie
            try:
                client_id, timestamp, time_start, time_end, mac = request.cookies.get('raincheck#' + request.path).split('#')
            except:
                resp = make_response(default_template.format(status='Invalid raincheck', detail='raincheck format error', rank=None))
                return resp
                #abort(403)
            error = rc.validate(client_id, timestamp, time_start, time_end, mac)
            if error:
                resp = make_response(default_template.format(status='Invalid raincheck', detail=error, rank=None))
                return resp
                #abort(403)

            result = rc.enqueue(client_id, timestamp, dill.dumps(copy_current_request_context(func)), *args, **keywords)

            if result[1] == 'error':
                resp = make_response(default_template.format(status='Execute original function error', detail=result[2].__class__.__name__ + ': ' + str(result[2]), rank=None))
                return resp
            elif result[1] == 'cancel':
                resp = make_response(default_template.format(status='Retrying', detail='The queue is full and your priority is not high enough', rank=rc.rank(int(timestamp))))
                resp.headers['Refresh'] = 5
                resp.set_cookie('raincheck#' + request.path, rc.issue(timestamp), max_age=rc.max_age)
                return resp
            else:
                return result[0]
        return decorated_func
    return decorator
