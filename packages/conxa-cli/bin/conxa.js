#!/usr/bin/env node
"use strict";
// Thin shim — all logic lives in lib/cli.js. The same cli.js is also installed
// into ~/.conxa/runtime/ by `conxa init` so the in-runtime server.js can shell
// to it directly without needing the npm bin on $PATH.
const { runCli } = require("../lib/cli.js");
runCli(process.argv.slice(2));
