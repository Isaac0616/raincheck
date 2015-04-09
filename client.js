var system = require('system');
var args = system.args;
var page = require('webpage').create();

log = [];
count = 0;

page.settings.resourceTimeout = 45000;
page.onResourceTimeout = function(e) {
    console.error(e.errorCode, ': ', e.errorString);
    phantom.exit(1);
};

page.onLoadFinished = function(status) {
    count++;
    if(args[2] == '--detail-log') {
        log.push({"request": count, "timeSpend": timeDiff, "content": page.plainText});
    }

    if(page.plainText.search("Time") != -1 || page.plainText.search("Invalid") != -1) {
        timeEndPage = new Date();
        output = {
            "totalRequests": count,
            "timeStart": timeStartPage.getTime()/1000,
            "timeEnd": timeEndPage.getTime()/1000,
            "timeSpend": (timeEndPage - timeStartPage)/1000
        };
        if(args[2] == '--detail-log') {
            output.log = log;
        }
        console.log(JSON.stringify(output));
        phantom.exit();
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
