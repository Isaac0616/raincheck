var system = require('system');
var args = system.args;
var page = require('webpage').create();

count = 0;

page.onLoadFinished = function(status) {
    count++;
    console.log('>>> request ' + count + ', time spend: ' + time_diff + 's');
    console.log(page.plainText);
    console.log('>>>\n');

    if(page.plainText.search("Index Page") != -1 || page.plainText.search("Invalid") != -1) {
        phantom.exit()
    }
};

page.onResourceRequested = function(requestData, networkRequest) {
    time_start = requestData['time'];
};

page.onResourceReceived = function(response) {
    if(response.stage == 'end') {
        time_diff = (response['time'] - time_start)/1000;
    }
};

page.open('http://' + args[1] + ':' + args[2] + '/?a=1&b=2&ip=' + args[3]);
