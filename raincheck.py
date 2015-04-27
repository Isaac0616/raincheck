from blist import sortedlist
from functools import wraps
from multiprocessing import Process, Lock, Condition, Event, Semaphore
from multiprocessing.managers import BaseManager
from flask import abort, make_response, request, render_template, g
from base64 import b64encode
from random import uniform
import hmac, hashlib
import time
import threading
import os
import struct
import socket

class Ticket():
    def __init__(self, priority, id):
        self.priority = priority
        self.id = id

class TicketQueue():
    def __init__(self, queue_size, ready_size, expire_time):
        self.queue_size = queue_size
        self.ready_size = ready_size
        self.expire_time = expire_time
        self.queue = sortedlist(key=lambda x: x.priority)
        self.id_state = {}
        self.timers = {}
        self.num_ready = 0

        self.mutex = Lock()
        self.queue_not_empty = Condition(self.mutex)
        self.ready_not_full = Condition(self.mutex)

    def add(self, id, priority):
        with self.mutex:
            self.queue.add(Ticket(priority, id))
            self.id_state[id] = 'queue'

            if len(self.queue) > self.queue_size:
                self.id_state.pop(self.queue.pop(-1).id)

            self.queue_not_empty.notify()

    def expire(self, id):
        with self.mutex:
            if self.id_state[id] == 'ready':
                self.id_state.pop(id)
                self.timers.pop(id)
                self.num_ready -= 1
            elif self.id_state[id] == 'accepted':
                self.id_state.pop(id)


    def set_ready(self):
        with self.ready_not_full:
            if self.num_ready >= self.ready_size:
                self.ready_not_full.wait()

        with self.queue_not_empty:
            if len(self.queue) == 0:
                self.queue_not_empty.wait()

            id = self.queue.pop(0).id
            self.id_state[id] = 'ready'
            self.num_ready += 1

            t = threading.Timer(self.expire_time, self.expire, args=(id, ))
            self.timers[id] = t
            t.start()

    def set_executing(self, id):
        with self.mutex:
            if self.id_state[id] == 'ready':
                self.timers[id].cancel()
                self.timers.pop(id)
                self.id_state[id] = 'executing'
                return True
            else:
                return False

    def set_accepted(self, id):
        with self.mutex:
            self.id_state[id] = 'accepted'
            self.num_ready -= 1
            self.ready_not_full.notify()
            threading.Timer(self.expire_time, self.expire, args=(id, )).start()

    def get_state(self, id):
        with self.mutex:
            return self.id_state.get(id, 'nonexistent')

class TicketQueueManager(BaseManager):
    pass

TicketQueueManager.register('TicketQueue', TicketQueue)


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

    def lowest_rank(self):
        current_time = time.time()
        with self.mutex:
            for i in range(self._sketch_size):
                if self.array[i]['modify_time'] < current_time - self.time_interval:
                       return (2**i)*1.2928

    def _trailing_zeros(self, client_id):
        binary = bin(self._ip2int(client_id))
        return len(binary) - binary.rfind('1') - 1

    def _ip2int(self, ip):
        return struct.unpack("!I", socket.inet_aton(ip))[0]


class RainCheck():
    def __init__(self, queue_size, time_pause, time_interval, concurrency=1, key=os.urandom(16)):
        """Initialize the RainCheck class"""
        self.queue_size = queue_size
        self.time_pause = time_pause
        self.time_interval = time_interval
        self.max_age = self.time_pause + self.time_interval
        self.concurrency = concurrency
        self.key = key

        self._tq_manager = TicketQueueManager()
        self._tq_manager.start()
        self._queue = self._tq_manager.TicketQueue(self.queue_size, self.concurrency, self.max_age)
        self._fms = FMSketch(self.max_age)

        self._worker = Process(target=self._work)
        self._worker.start()

    def _work(self):
        """
        Method executing by the background worker process.
        It will continuously try to set one request in ready state.
        """
        try:
            while True:
                self._queue.set_ready()
        except:
            pass

    def _enqueue(self, client_id, priority):
        """Add the request to priority queue."""
        self._fms.add(client_id, priority)
        self._queue.add(client_id, priority)

    def _validate(self, client_id, timestamp, time_start, time_end, mac):
        """Validate the raincheck.

        Args:
            Fileds parse from raincheck.

        Returns:
            None if validation successes.
            Error message if validation fails.
        """
        if not hmac.compare_digest(
            b64encode(
                hmac.new(
                    self.key,
                    '#'.join([client_id, str(timestamp), str(time_start), str(time_end)]),
                    hashlib.sha256
                ).digest()
            ),
            str(mac)
        ):
            return 'MAC verification fail'
        if g.ip != client_id:
            return 'Client ID mismatch'
        current_time = time.time()
        if current_time < time_start or current_time > time_end:
            return 'Not in the lifetime'

    def _issue(self, timestamp=None):
        """Issue the raincheck.

        Args:
            timestamp: Timestamp argument in raincheck. If not provided (new raincheck
            for first time request), use current time as timestamp.

        Returns:
            Raincheck string.
        """
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
                        rank=self._fms.lowest_rank()))
                    resp.headers['Refresh'] = self.time_pause
                    resp.set_cookie('raincheck#' + request.path, self._issue(), max_age=self.max_age)
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
                error = self._validate(client_id, timestamp, time_start, time_end, mac)
                if error:
                    resp = make_response(render_template(template,
                        status='Invalid raincheck',
                        detail=error,
                        rank=None))
                    return resp

                # Following code checks the status of client's request and
                # gives the corresponding respond.

                state = self._queue.get_state(client_id)

                # In queue: retry later
                if state == 'queue':
                    resp = make_response(render_template(template,
                        status='Retrying',
                        detail='In buffer',
                        rank=self._fms.rank(timestamp)))
                    resp.headers['Refresh'] = uniform(self.time_pause, self.max_age - 1)
                    resp.set_cookie('raincheck#' + request.path, self._issue(timestamp), max_age=self.max_age)
                # Ready: execute the original server function
                elif state == 'ready':
                    # set_executing may still fail due to concurrent request
                    if self._queue.set_executing(client_id):
                        resp = func(*args, **keywords)
                        self._queue.set_accepted(client_id)
                    else:
                        resp = make_response(render_template(template,
                            status='Invalid raincheck',
                            detail='Request is proccessing',
                            rank=None))
                # Executing: reject to simultaneously execute another request
                #     from the same client
                elif state == 'executing':
                    resp = make_response(render_template(template,
                        status='Invalid raincheck',
                        detail='Request is proccessing',
                        rank=None))
                # accepted: reject to execute another request from the same
                #     client in a short period
                elif state == 'accepted':
                    resp = make_response(render_template(template,
                        status='Invalid raincheck',
                        detail='Request is in Accepted',
                        rank=None))
                # Request is not in queue.
                # Enqueue the request and let client retry later.
                elif state == 'nonexistent':
                    self._enqueue(client_id, timestamp)

                    resp = make_response(render_template(template,
                        status='Retrying',
                        detail='Try to enqueue',
                        rank=self._fms.rank(timestamp)))
                    resp.headers['Refresh'] = uniform(self.time_pause, self.max_age - 1)
                    resp.set_cookie('raincheck#' + request.path, self._issue(timestamp), max_age=self.max_age)

                return resp
            return decorated_func
        return decorator
