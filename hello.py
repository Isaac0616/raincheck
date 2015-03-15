from flask import Flask, request
app = Flask(__name__)

from time import time
from sympy import factorint
from multiprocessing import Process, Queue

from raincheck import RainCheck
rc = RainCheck(queue_size=3, time_pause=1, time_interval=10, concurrency=1, key='this is secret key')


def factor(q, prime):
    q.put(factorint(prime))

@app.route('/rc_prime')
@rc.raincheck()
def index():
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

@app.route('/prime')
def hello():
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

if __name__ == '__main__':
    app.run(host='0.0.0.0', threaded=True)
