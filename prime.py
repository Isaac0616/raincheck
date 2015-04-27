from flask import Flask, request, session, redirect, url_for
app = Flask(__name__)

from time import time
from sympy import factorint
from multiprocessing import Process, Queue

from raincheck import RainCheck
rc = RainCheck(queue_size=3, time_pause=1, time_interval=10, concurrency=1, key='this is secret key')
rc_login = RainCheck(queue_size=3, time_pause=1, time_interval=10, identification='username', concurrency=3, key='this is secret key')


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

@app.route('/login_prime')
@rc_login.raincheck()
def login_prime():
    if 'username' not in session:
        return redirect(url_for('login'))
    return prime_body()

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        session['username'] = request.form['username']
        return 'Hi, you are logged in as ' + session['username'] + '.'
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
