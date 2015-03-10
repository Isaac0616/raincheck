var system = require('system');
var args = system.args;
var page = require('webpage').create();

count = 0;

page.onLoadFinished = function(status) {
    count++;
    console.log('>>> request ' + count + ', time spend: ' + time_diff + 's');
    console.log(page.plainText);
    console.log('>>>\n');

    if(page.plainText.search("Time") != -1 || page.plainText.search("Invalid") != -1) {
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

page.open(args[1]);
