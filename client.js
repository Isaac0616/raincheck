var system = require('system');
var args = system.args;
var page = require('webpage').create();

log = [];
count = 0;

page.onLoadFinished = function(status) {
    count++;
    log.push({"request": count, "timeSpend": timeDiff, "content": page.plainText});

    if(page.plainText.search("Time") != -1 || page.plainText.search("Invalid") != -1) {
        timeEndPage = new Date()
        console.log(JSON.stringify({
            "totalRequests": count,
            "timeStart": timeStartPage.getTime()/1000,
            "timeEnd": timeEndPage.getTime()/1000,
            "timeSpend": (timeEndPage - timeStartPage)/1000,
            "log": log
        }));
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
