from flask import Flask, request
app = Flask(__name__)

from time import sleep
import random

from raincheck import register, raincheck
register(name='all', queue_size=3, time_pause=1, time_interval=10, workers=1, key='this is secret key')

@app.route('/')
@raincheck('all')
def index():
    sleep(5)
    a = int(request.args.get('a', ''))
    b = int(request.args.get('b', ''))

    return 'Index Page ' + str(a + b)

@app.route('/hello')
def hello():
    return 'Hello Page'

@app.route('/user/<username>')
def show_user_profile(username):
    # show the user profile for that user
    return 'User %s' % username

@app.route('/post/<int:post_id>')
def show_post(post_id):
    # show the post with the given id, the id is an integer
    return 'Post %d' % post_id

if __name__ == '__main__':
    app.run(debug=True, threaded=True)
