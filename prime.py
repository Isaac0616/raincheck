from flask import Flask, request, session, redirect, url_for, make_response
app = Flask(__name__)

from time import time
from sympy import factorint
from multiprocessing import Process, Queue, BoundedSemaphore
from functools import wraps
from random import uniform

BUFFER_SIZE = 3
TPAUSE=1
TINTERVAL=10

from raincheck import RainCheck
rc = RainCheck(queue_size=BUFFER_SIZE, time_pause=TPAUSE, time_interval=TINTERVAL, concurrency=1, key='this is secret key')
rc_login = RainCheck(queue_size=BUFFER_SIZE, time_pause=TPAUSE, time_interval=TINTERVAL, identification='username', concurrency=1, key='this is secret key')

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'username' not in session:
            return redirect(url_for('login', p=request.args.get('p', '')))
        return f(*args, **kwargs)
    return decorated_function

def rate_limited(f):
    sema = BoundedSemaphore(BUFFER_SIZE)
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not sema.acquire(False):
            resp = make_response('full')
            resp.headers['Refresh'] = uniform(TPAUSE, TINTERVAL - 1)
            return resp
        resp = f(*args, **kwargs)
        sema.release()
        return resp
    return decorated_function

def factor(q, prime):
    q.put(factorint(prime))

def prime_body():
    prime = int(request.args.get('p', ''))

    ts = time()

    q = Queue()
    p = Process(target=factor, args=(q, prime))
    p.start()
    try:
        factors = q.get(timeout=30)
    except:
        p.terminate()
        return 'Time out'

    time_spend = time() - ts

    return 'Time spend: ' + str(time_spend) + '<br>Ans: ' + ' + '.join([str(f) + '^' + str(e) for f, e in factors.iteritems()])

@app.route('/rc_prime')
@rc.raincheck()
def rc_prime():
    return prime_body()

@app.route('/prime')
def prime():
    return prime_body()

@app.route('/limit_prime')
@rate_limited
def limit_prime():
    return prime_body()

@app.route('/login_prime')
@login_required
@rc_login.raincheck()
def login_prime():
    return prime_body()

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        session['username'] = request.form['username']
        return redirect(url_for('login_prime', p=request.args.get('p', '')))
    return '''
        <form action="" method="post">
            <p><input type=text name=username>
            <p><input type=submit value=Login>
        </form>
    '''

@app.route('/logout')
def logout():
    session.pop('username', None)
    return redirect(url_for('login'))

if __name__ == '__main__':
    app.secret_key = 'this is secret key'
    app.run(host='0.0.0.0', threaded=True)
