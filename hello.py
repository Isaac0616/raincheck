from flask import Flask, request
app = Flask(__name__)

from time import time
import random
from sympy import factorint

from raincheck import RainCheck
rc = RainCheck(name='all', queue_size=3, time_pause=1, time_interval=10, threads=1, key='this is secret key')

@app.route('/rc_prime')
@rc.raincheck()
def index():
    prime = int(request.args.get('p', ''))
    ts = time()
    factors = factorint(prime)
    time_spend = time() - ts

    return 'Time spend: ' + str(time_spend) + '<br>Ans: ' + ' + '.join([str(f) + '^' + str(e) for f, e in factors.iteritems()])

@app.route('/prime')
def hello():
    prime = int(request.args.get('p', ''))
    ts = time()
    factors = factorint(prime)
    time_spend = time() - ts

    return 'Time spend: ' + str(time_spend) + '<br>Ans: ' + ' + '.join([str(f) + '^' + str(e) for f, e in factors.iteritems()])

if __name__ == '__main__':
    app.run(host='0.0.0.0', threaded=True)
