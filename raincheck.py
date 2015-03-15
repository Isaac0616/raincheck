from blist import sortedlist
from functools import wraps
from multiprocessing import Process, Lock, Condition, Event, Semaphore
from multiprocessing.managers import BaseManager
from flask import abort, make_response, request, render_template, g
from base64 import b64encode
import hmac, hashlib
import time
import threading
import os
import struct
import socket

INF = 2147483647

class Ticket():
    def __init__(self, priority, id):
        self.priority = priority
        self.id = id

    def get_priority(self):
        return self.priority

    def get_id(self):
        return self.id

class TicketQueue():
    def __init__(self, max_size):
        self.max_size = max_size
        self.queue = sortedlist(key=lambda x: x.get_priority())
        self.id_set = set()

        self.mutex = Lock()
        self.not_empty = Condition(self.mutex)

    def add(self, priority, id):
        with self.mutex:
            ticket = Ticket(priority, id)
            self.queue.add(ticket)
            self.id_set.add(id)

            if len(self.queue) > self.max_size:
                ticket = self.queue.pop(-1)
                self.id_set.remove(ticket.get_id())

            self.not_empty.notify()

    def get(self):
        with self.not_empty:
            if len(self.queue) == 0:
                self.not_empty.wait()
            ticket = self.queue[0]
            return ticket

    def pop(self):
        with self.not_empty:
            if len(self.queue) == 0:
                self.not_empty.wait()
            self.id_set.remove(self.queue.pop(0).get_id())

    def contain(self, id):
        with self.mutex:
            return id in self.id_set

class TicketQueueManager(BaseManager):
    pass

TicketQueueManager.register('TicketQueue', TicketQueue)


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

class ReadyBuffer():
    def __init__(self, expire_time, max_size):
        self.buffer = {}
        self.expire_time = expire_time
        self.max_size = max_size
        self.mutex = Lock()
        self.not_full = Condition(self.mutex)

    def expire(self, value):
        with self.mutex:
            if self.buffer[value]['state'] != 'executing':
                self.buffer.pop(value)
                self.not_full.notify()

    def remove(self, value):
        with self.mutex:
            self.buffer.pop(value)
            self.not_full.notify()

    def add(self, value, expire_time=None):
        if not expire_time:
            expire_time = self.expire_time

        with self.not_full:
            if len(self.buffer) > self.max_size:
                self.not_full.wait()

            t = threading.Timer(expire_time, self.expire, args=(value, ))
            self.buffer[value] = {'timer': t, 'state': 'READY'}
            t.start()

    # TODO: Need a better method name
    def set_executing(self, value):
        with self.mutex:
            if not self.buffer.has_key(value):
                return 'NOT_READY'
            elif self.buffer[value]['state'] == 'EXECUTING':
                return 'EXECUTING'
            else:
                self.buffer[value]['timer'].cancel()
                self.buffer[value]['state'] = 'EXECUTING'
                return 'READY'

class ReadyBufferManager(BaseManager):
    pass

ReadyBufferManager.register('ReadyBuffer', ReadyBuffer)


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


class RainCheck():
    def __init__(self, name, queue_size, time_pause, time_interval, concurrency=1, key=os.urandom(16)):
        self.name = name
        self.queue_size = queue_size
        self.time_pause = time_pause
        self.time_interval = time_interval
        self.time_refresh = (self.time_pause + self.time_interval)/2
        self.max_age = self.time_pause + self.time_interval # may need longer
        self.concurrency = concurrency
        self.key = key

        self.rb_manager = ReadyBufferManager()
        self.rb_manager.start()
        self.ready = self.rb_manager.ReadyBuffer(self.max_age, self.concurrency)
        self.accepted = ExpireSet(self.max_age)
        self.fms = FMSketch(self.max_age)

        self.tq_manager = TicketQueueManager()
        self.tq_manager.start()
        self.queue = self.tq_manager.TicketQueue(self.queue_size)

        self.worker = Process(target=self._work)
        self.worker.start()

    def _work(self):
        try:
            while True:
                id = self.queue.get().get_id()
                self.ready.add(id)
                self.queue.pop()
        except:
            pass

    def enqueue(self, client_id, priority):
        self.fms.add(client_id, priority)
        self.queue.add(priority, client_id)

    def validate(self, client_id, timestamp, time_start, time_end, mac):
        if not hmac.compare_digest(b64encode(hmac.new(self.key, '#'.join([client_id, str(timestamp), str(time_start), str(time_end)]), hashlib.sha256).digest()), str(mac)):
            return 'MAC verification fail'
        if g.ip != client_id:
            return 'Client ID mismatch'
        current_time = time.time()
        if current_time < time_start or current_time > time_end:
            return 'Not in the lifetime'

    def issue(self, timestamp=None):
        current_time = time.time()
        time_start = current_time + self.time_pause
        time_end = time_start + self.time_interval
        if timestamp == None:
            message = '#'.join([g.ip, str(current_time), str(time_start), str(time_end)])
        else:
            message = '#'.join([g.ip, str(timestamp), str(time_start), str(time_end)])
        return message + '#' + b64encode(hmac.new(self.key, message, hashlib.sha256).digest())

    def raincheck(self, template='raincheck.html'):
        """Decorator for apply rain check to a function

        Args:
            template: Html template for showing intermediate information
                to client. Following arguments are provided as jinja2 variables:
                status, detail and rank.
        """
        def decorator(func):
            @wraps(func)
            def decorated_func(*args, **keywords):
                # Client can provide testing IP by 'ip' argument of GET.
                # If not provided, use real IP.
                g.ip = request.args.get('ip', request.remote_addr)

                # No raincheck. Client request for the first time.
                if request.cookies.get('raincheck#' + request.path) == None:
                    resp = make_response(render_template(template,
                        status='First time request',
                        detail='Get the raincheck',
                        rank=self.fms.rank(INF)))
                    resp.headers['Refresh'] = self.time_pause
                    resp.set_cookie('raincheck#' + request.path, self.issue(), max_age=self.max_age)
                    return resp

                # parse raincheck
                raincheck_list = request.cookies.get('raincheck#' + request.path).split('#')
                if len(raincheck_list) != 5:
                    resp = make_response(render_template(template,
                        status='Invalid raincheck',
                        detail='raincheck format error',
                        rank=None))
                    return resp
                client_id = raincheck_list[0]
                timestamp = float(raincheck_list[1])
                time_start = float(raincheck_list[2])
                time_end = float(raincheck_list[3])
                mac = raincheck_list[4]

                # validate raincheck
                error = self.validate(client_id, timestamp, time_start, time_end, mac)
                if error:
                    resp = make_response(render_template(template,
                        status='Invalid raincheck',
                        detail=error,
                        rank=None))
                    return resp

                # Following code checks the status of client's request and
                # gives the corresponding respond.

                # In queue: retry later
                if self.queue.contain(client_id):
                    resp = make_response(render_template(template,
                        status='Retrying',
                        detail='In buffer',
                        rank=self.fms.rank(timestamp)))
                    resp.headers['Refresh'] = self.time_refresh
                    resp.set_cookie('raincheck#' + request.path, self.issue(timestamp), max_age=self.max_age)
                    return resp

                # Ready: execute the original server function
                # Executing: reject to simultaneously execute another request
                #     from the same client
                state = self.ready.set_executing(client_id)
                if state == 'READY':
                    resp = func(*args, **keywords)
                    self.accepted.add(client_id)
                    self.ready.remove(client_id)
                    return resp
                elif state == 'EXECUTING':
                    resp = make_response(render_template(template,
                        status='Invalid raincheck',
                        detail='Request is proccessing',
                        rank=None))
                    return resp

                # accepted: reject to execute another request from the same
                #     client in a short period
                if client_id in self.accepted:
                    resp = make_response(render_template(template,
                        status='Invalid raincheck',
                        detail='Request is in Accepted',
                        rank=None))
                    return resp

                # Request is in neither queue, ready buffer nor accepted buffer.
                # Enqueue the request and retry later.
                self.enqueue(client_id, timestamp)

                resp = make_response(render_template(template,
                    status='Retrying',
                    detail='Try to enqueue',
                    rank=self.fms.rank(timestamp)))
                resp.headers['Refresh'] = self.time_refresh
                resp.set_cookie('raincheck#' + request.path, self.issue(timestamp), max_age=self.max_age)
                return resp

            return decorated_func
        return decorator
