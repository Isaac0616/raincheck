# RainCheck Filters
**Caution:** This project is still in early development. APIs and architecture may change frequently.

This project implement Raincheck Filters described in **_"RainCheck Filters: A Practical System for Guaranteed Access in the Presence of DDoS Attacks and Flash Crowds"_** base on [Flask (A Python Microframework)](http://flask.pocoo.org/).
For more information, please refer the paper.

## Requirement
### Python
Require `Python >= 2.7.7`.  
If you have problem with Python version, please try [pyenv](https://github.com/yyuu/pyenv) or [virtualenv](http://docs.python-guide.org/en/latest/dev/virtualenvs/).

### For raincheck module
Require `blist`, `Flask`.

```
pip install blist Flask
```

### For sample server
Require extra `SymPy`.

```
pip install sympy
```

### For testing
Require `PhantomJS`.  
Please refer <http://phantomjs.org> to install PhantomJS.
If you are using OS X, you can use [Homebrew](http://brew.sh/) to install it.

```
brew install phantomjs
```

## Usage

### raincheck module

This is a simple web server from Flask homepage.

```python
from flask import Flask
app = Flask(__name__)

@app.route("/")
def hello():
    return "Hello World!"

if __name__ == "__main__":
    app.run()
```

Now assume there are some computing intensive jobs in ```hello``` and need to protect by RainCheck.
First, import ```RainCheck``` class from ```raincheck``` module and create an instance with appropriate configuration.

```python
from raincheck import RainCheck
rc = RainCheck(queue_size=3, time_pause=1, time_interval=10, concurrency=1, key='this is secret key')
```

Arguments:
- ```queue_size```: Size of priority queue. (require)
- ```time_pause```: Least amount of time client have to wait for another request. (require)
- ```time_interval```: Life time of a raincheck. (require)
- ```concurrency```: Limit of simultaneously processing clients. (optional, default: ```1```)
- ```key```: Key for HMAC. (optional, default: ```os.urandom(16)```)

Next, apply the ```raincheck``` decorator to target function.

```python
@app.route("/")
@rc.raincheck()
def hello():
    result = computing() # write your own function
    return "Hello " + result
```

There is an optional ```template``` argument for ```raincheck``` decorator which should be the name of a [Jinja2](http://jinja.pocoo.org) template to customize intermediate response page for RainCheck.
Please refer default template ```templates/raincheck.html``` to see the simple example.

Putting all together.

```python
from flask import Flask
app = Flask(__name__)

from raincheck import RainCheck
rc = RainCheck(queue_size=3, time_pause=1, time_interval=10, concurrency=1, key='this is secret key')

@app.route("/")
@rc.raincheck()
def hello():
    result = computing() # write your own function
    return "Hello " + result

if __name__ == "__main__":
    app.run()
```

Finally, run the server by:

```
python hello.py
```

### sample server
```prime.py``` in the repository is a sample web server to show the usage of RainCheck.
Run it as normal:

```
python prime.py
```

It contains two path ```rc_prime``` and ```prime``` which do exactly same job that take a ```p``` argument of GET and return the factorization with 30 seconds timeout.
The only diffrent is that ```rc_prime``` is protected by Raincheck.
Try it by opening <http://localhost:5000/prime?p=33839528068037464891> in the browser, it should show something like

```
Time spend: 5.42507886887
Ans: 5035126909^1 + 6720690199^1
```

in several seconds.
Then, try <http://localhost:5000/rc_prime?p=33839528068037464891> to see the interaction between browser and RainCheck filter.



### testing
Currently just support a simple scenario as following:

```
python testing.py --url "http://localhost:5000/rc_prime" --args "p=33839528068037464891" --clients 10
```

It will spawn N clients to simultaneously access given url with given GET arguments and save the result in ```log.html```.
It will also automatically open ```log.html``` in browser after all clients are finished.

Arguments:
- ```--url```, ```-u```: Url to be accessed. Remember to add ```http://``` prefix. (default: ```http://localhost:5000/rc_prime```)
- ```--args```, ```-a```: GET arguments. For multiple arguments, write them in the same string seperate by ```&```. For example, ```--args "a=1&b=2"```. (default: ```p=33839528068037464891```)
- ```--clients```, ```-n```: Number of clients. (default: ```10```)

## File Organization
```
raincheck
├── README.md
├── raincheck.py
├── templates
│   └── raincheck.html
├── prime.py
├── client.js
├── testing.py
├── log.html
└── log_template.html
```

- ```README.md```: This file.
- ```raincheck.py```: Main module.
- ```templates/raincheck.html```: Default template for raincheck intermediate response.
- ```prime.py```: Sample server.
- ```client.js```: PhantomJS script represents a single client.
- ```testing.py```: Control ```client.js``` to perform testing.
- ```log.html```: Output of ```testing.py``` which records access logs of every clients. (Not include in repository)
- ```log_template.html```: Jinja2 template to generate ```log.html```

## Architecture
TODO.

## Implementation Details
TODO.

## Future work
TODO.

## License
TODO.
