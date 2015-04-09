var system = require('system');
var args = system.args;
var page = require('webpage').create();

log = [];
count = 0;

page.settings.resourceTimeout = 45000;
page.onResourceTimeout = function(e) {
    system.stderr.writeLine('Resource Timeout: ' + e.errorString + ' (' + e.errorCode + ')');
};

page.onResourceError = function(e) {
    system.stderr.writeLine('Resource Error: ' + e.errorString + ' (' + e.errorCode + ')');
};

page.onLoadFinished = function(status) {
    if(status != 'success') {
        phantom.exit(1);
    }
    else {
        count++;
        if(args[2] == '--detail-log') {
            log.push({'request': count, 'timeSpend': timeDiff, 'content': page.plainText});
        }

        if(page.plainText.search('Time') != -1 || page.plainText.search('Invalid') != -1) {
            timeEndPage = new Date();
            timeSpend = (timeEndPage - timeStartPage)/1000;

            output = {
                'totalRequests': count,
                'timeStart': timeStartPage/1000,
                'timeEnd': timeEndPage/1000,
                'timeSpend': timeSpend
            };
            if(args[2] == '--detail-log') {
                output.log = log;
            }

            console.log(JSON.stringify(output));
            system.stderr.writeLine(args[1].match(/ip=(\d+\.){3}\d+/g)[0].slice(3) + ': ' + timeSpend + 's');

            phantom.exit();
        }
    }
};

page.onResourceRequested = function(requestData, networkRequest) {
    timeStartRequest = requestData['time'];
};

page.onResourceReceived = function(response) {
    if(response.stage == 'end') {
        timeDiff = (response['time'] - timeStartRequest)/1000;
    }
};

timeStartPage = new Date();
page.open(args[1]);
