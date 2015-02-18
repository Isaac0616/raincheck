from blist import sortedlist
from functools import wraps
from multiprocessing import Process, Lock, Condition, Event, Semaphore
from multiprocessing.managers import BaseManager
from flask import abort, make_response, request, render_template
from base64 import b64encode
import hmac, hashlib
import time
import threading
import os
import struct
import socket
import sys

INF = 2147483647

class ShouldNotBeHereError(Exception):
    def __init__(self, msg):
        self.msg = msg
    def __str__(self):
        return repr(self.msg)

class Ticket():
    def __init__(self, priority):
        self.priority = priority
        self.state = 'initial'
        self.dequeue = Event()

    def cancel(self):
        self.state = 'cancel'
        self.dequeue.set()

    def ready(self):
        self.state = 'ready'
        self.dequeue.set()

    def get_priority(self):
        return self.priority

    def get_state(self):
        self.dequeue.wait()
        return self.state

class TicketManager(BaseManager):
    pass

TicketManager.register('Ticket', Ticket)


class TicketQueue():
    def __init__(self, max_size):
        self.queue = sortedlist(key=lambda x: x.get_priority())
        self.max_size = max_size
        self.mutex = Lock()
        self.not_empty = Condition(self.mutex)
        self.manager = TicketManager()
        self.manager.start()

    def wait(self, priority):
        with self.mutex:
            ticket = self.manager.Ticket(priority)
            self.queue.add(ticket)
            if len(self.queue) > self.max_size:
                self.queue.pop(-1).cancel()
            self.not_empty.notify()
        return ticket.get_state()

    def serve_next(self):
        with self.not_empty:
            if len(self.queue) == 0:
                self.not_empty.wait()
            self.queue.pop(0).ready()

    def __contains__(self, item):
        return item in self.queue

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


class RainCheck():
    def __init__(self, name, queue_size, time_pause, time_interval, threads=1, key=os.urandom(16)):
        self.name = name
        self.queue_size = queue_size
        self.time_pause = time_pause
        self.time_interval = time_interval
        self.max_age = self.time_pause + self.time_interval # may need longer
        self.threads = threads
        self.key = key

        self.accepted = ExpireSet(self.max_age)
        self.buffered = ExpireSet(-1)
        self.fms = FMSketch(self.max_age)

        self.pool_sema = Semaphore(threads)
        self.manager = TicketQueueManager()
        self.manager.start()
        self.queue = self.manager.TicketQueue(self.queue_size)

        self.worker = Process(target=self._work)
        self.worker.start()

    def _work(self):
        while True:
            self.pool_sema.acquire()
            self.queue.serve_next()

    def enqueue(self, client_id, priority, target, *args, **keywords):
        self.fms.add(client_id, priority)
        self.buffered.add(client_id)
        state = self.queue.wait(priority)

        if state == 'ready':
            try:
                resp = target(*args, **keywords)
            finally:
                self.pool_sema.release()
                self.accepted.add(client_id)
                self.buffered.remove(client_id)
            return resp
        elif state == 'cancel':
            self.buffered.remove(client_id)
        else:
            raise ShouldNotBeHereError('State can only be ready or cancel')

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

    def raincheck(self, template='raincheck.html'):
        def decorator(func):
            @wraps(func)
            def decorated_func(*args, **keywords):
                # TODO adjust refresh time by time_apuse, time_interval
                if request.cookies.get('raincheck#' + request.path) == None:
                    resp = make_response(render_template(template, status='First time request', detail='Get the raincheck', rank=self.rank(INF)))
                    resp.headers['Refresh'] = 2
                    resp.set_cookie('raincheck#' + request.path, self.issue(), max_age=self.max_age)
                    return resp

                # may need to clear cookie
                try:
                    client_id, timestamp, time_start, time_end, mac = request.cookies.get('raincheck#' + request.path).split('#')
                except:
                    resp = make_response(render_template(template, status='Invalid raincheck', detail='raincheck format error', rank=None))
                    return resp
                error = self.validate(client_id, timestamp, time_start, time_end, mac)
                if error:
                    resp = make_response(render_template(template, status='Invalid raincheck', detail=error, rank=None))
                    return resp

                resp = self.enqueue(client_id, float(timestamp), func, *args, **keywords)
                if not resp:
                    resp = make_response(render_template(template, status='Retrying', detail='The queue is full and your priority is not high enough', rank=self.rank(priotiry)))
                    resp.headers['Refresh'] = 5
                    resp.set_cookie('raincheck#' + request.path, self.issue(priority), max_age=self.max_age)
                return resp
            return decorated_func
        return decorator
