// A DAP proxy in front of gdb's DAP server that adds Python line breakpoints
// and steps through Python lines.
// usage: node dap-proxy.js <gdb> [gdb args...]
//
// gdb cannot bind a breakpoint in a .py file. The proxy answers those
// setBreakpoints requests itself and writes the lines to a JSON file. The
// launch request passes the file to the process in CPPJIT_PY_BREAKPOINTS;
// cppjit.debugger then calls a native function at each of these lines, and the
// cppjit gdb extension stops there.
//
// At a stop on a Python line, Step Over, Step Into and Step Out become
// "cppjit py-step" and a continue; Step Into also goes into the C++ code
// that the line calls. A native step that ends in internal code (the gdb
// extension marks its frame "[internal]"), for example at the return from
// JIT code, goes on to the Python line that called it.
//
// The gdb extension gives the variables of Python frames. In a Python frame,
// the proxy answers hover, watch and console expressions that are a Python
// name, such as "self.items[0]", from these variables.
"use strict";

const childProcess = require("child_process");
const fs = require("fs");
const os = require("os");
const path = require("path");

const ENV = "CPPJIT_PY_BREAKPOINTS";
// Out of the range of gdb's own breakpoint numbers and of the client's sequence numbers.
const FIRST_ID = 1000000;
const FIRST_OWN_SEQ = 1000000000;
const STEPS = { next: "over", stepIn: "into", stepOut: "out" };
const PYTHON_FRAME = "[py] ";
const INTERNAL_FRAME = "[internal] ";
// The gdb type of the values of Python variables; not useful to the user.
const PYTHON_VALUE_TYPE = "volatile unsigned long";
const PYTHON_NAME = /^[A-Za-z_]\w*(\.[A-Za-z_]\w*|\[\d+\])*$/;

// Parses Content-Length framed DAP messages from a stream.
function reader(stream, onMessage) {
    let buffer = Buffer.alloc(0);
    stream.on("data", (chunk) => {
        buffer = Buffer.concat([buffer, chunk]);
        for (;;) {
            const end = buffer.indexOf("\r\n\r\n");
            if (end < 0) {
                return;
            }
            const match = /Content-Length:\s*(\d+)/i.exec(buffer.subarray(0, end).toString());
            const length = match ? Number(match[1]) : 0;
            if (buffer.length < end + 4 + length) {
                return;
            }
            const body = buffer.subarray(end + 4, end + 4 + length).toString();
            buffer = buffer.subarray(end + 4 + length);
            onMessage(JSON.parse(body));
        }
    });
}

function write(stream, message) {
    const data = Buffer.from(JSON.stringify(message));
    stream.write(`Content-Length: ${data.length}\r\n\r\n`);
    stream.write(data);
}

function isPython(source) {
    return Boolean(source && source.path && source.path.endsWith(".py"));
}

function main(argv) {
    const gdb = childProcess.spawn(argv[0], argv.slice(1), { stdio: ["pipe", "pipe", "inherit"] });
    const file = path.join(os.tmpdir(), `cppjit-py-breakpoints-${process.pid}.json`);
    const lines = {};
    // The name of the top frame of each thread at its last stop.
    const topFrame = new Map();
    // The name of each frame id in the stack traces of the current stop.
    const frameNames = new Map();
    // Threads whose next stop ends a Python step.
    const stepping = new Set();
    // Callbacks for the responses to the proxy's own requests.
    const pending = new Map();
    let seq = 0;
    let ownSeq = FIRST_OWN_SEQ;
    let nextId = FIRST_ID;
    let attached = false;

    const toClient = (message) => write(process.stdout, { ...message, seq: ++seq });
    const respond = (request, body) =>
        toClient({ type: "response", request_seq: request.seq, command: request.command, success: true, body });
    const ask = (command, args) =>
        new Promise((resolve) => {
            const message = { seq: ++ownSeq, type: "request", command, arguments: args };
            pending.set(message.seq, resolve);
            write(gdb.stdin, message);
        });
    const save = () => {
        fs.writeFileSync(file + ".tmp", JSON.stringify(lines));
        fs.renameSync(file + ".tmp", file);
    };
    save();

    const pythonStep = async (threadId, mode) => {
        stepping.add(threadId);
        await ask("evaluate", { expression: `cppjit py-step --arm ${mode}`, context: "repl" });
        await ask("continue", { threadId });
    };

    const child = async (variablesReference, name) => {
        const answer = await ask("variables", { variablesReference });
        return ((answer.success && answer.body.variables) || []).find((v) => v.name === name);
    };

    const pythonVariable = async (frameId, expression) => {
        const parts = expression.match(/[A-Za-z_]\w*|\d+/g);
        const answer = await ask("scopes", { frameId });
        let found;
        for (const scope of (answer.success && answer.body.scopes) || []) {
            if (scope.name !== "Registers" && scope.variablesReference) {
                found = await child(scope.variablesReference, parts[0]);
                if (found) {
                    break;
                }
            }
        }
        for (const part of parts.slice(1)) {
            if (!found || !found.variablesReference) {
                return undefined;
            }
            found = await child(found.variablesReference, part);
        }
        return found;
    };

    const evaluate = async (request) => {
        const args = request.arguments;
        const found = await pythonVariable(args.frameId, args.expression.trim());
        if (!found) {
            write(gdb.stdin, request);
            return;
        }
        const { value, type, ...rest } = found;
        respond(request, { ...rest, result: value });
    };

    const onStopped = async (event) => {
        const threadId = event.body.threadId;
        frameNames.clear();
        const answer = await ask("stackTrace", { threadId, startFrame: 0, levels: 1 });
        const frames = (answer.success && answer.body.stackFrames) || [];
        const top = frames.length ? frames[0].name : "";
        if (event.body.reason === "step" && top.startsWith(INTERNAL_FRAME)) {
            // The step left the user's C++ code: go on to the Python caller.
            await pythonStep(threadId, "return");
            return;
        }
        topFrame.set(threadId, top);
        // gdb's internal breakpoint for Python lines has a negative number.
        const hits = event.body.hitBreakpointIds || [];
        const own = hits.filter((id) => id > 0);
        const body = { ...event.body, hitBreakpointIds: own };
        if (stepping.delete(threadId)) {
            body.reason = "step";
        } else if (own.length < hits.length) {
            body.reason = "breakpoint";
        }
        toClient({ ...event, body });
    };

    reader(process.stdin, (message) => {
        const args = message.arguments || {};
        if (message.type === "request" && message.command === "launch") {
            const env = { ...(args.env || {}), [ENV]: file, PYTHONUNBUFFERED: "1" };
            message = { ...message, arguments: { ...args, env } };
        } else if (message.type === "request" && message.command === "attach") {
            attached = true;
        } else if (message.type === "request" && message.command === "setBreakpoints" && isPython(args.source)) {
            const wanted = args.breakpoints || [];
            lines[path.resolve(args.source.path)] = wanted.map((b) => b.line);
            save();
            respond(message, {
                breakpoints: wanted.map((b) => attached
                    ? { verified: false, line: b.line, source: args.source,
                        message: "Python breakpoints need a launch with CPPJIT_DEBUGGER_SUPPORT=1" }
                    : { id: nextId++, verified: true, line: b.line, source: args.source }),
            });
            return;
        } else if (message.type === "request" && message.command === "evaluate" &&
                   (frameNames.get(args.frameId) || "").startsWith(PYTHON_FRAME) &&
                   PYTHON_NAME.test((args.expression || "").trim())) {
            evaluate(message);
            return;
        } else if (message.type === "request" && message.command in STEPS &&
                   (topFrame.get(args.threadId) || "").startsWith(PYTHON_FRAME)) {
            respond(message, {});
            pythonStep(args.threadId, STEPS[message.command]);
            return;
        }
        write(gdb.stdin, message);
    });

    reader(gdb.stdout, (message) => {
        if (message.type === "response" && message.success && message.command === "stackTrace") {
            for (const frame of message.body.stackFrames || []) {
                frameNames.set(frame.id, frame.name);
            }
        } else if (message.type === "response" && message.success && message.command === "variables") {
            for (const variable of message.body.variables || []) {
                if (variable.type === PYTHON_VALUE_TYPE) {
                    delete variable.type;
                }
            }
        }
        if (message.type === "response" && pending.has(message.request_seq)) {
            const resolve = pending.get(message.request_seq);
            pending.delete(message.request_seq);
            resolve(message);
        } else if (message.type === "event" && message.event === "stopped" && message.body.threadId !== undefined) {
            onStopped(message);
        } else if (message.type === "event" && message.event === "breakpoint" && message.body.breakpoint.id < 0) {
            // Internal to the gdb extension: not a breakpoint of the user.
        } else {
            toClient(message);
        }
    });

    const cleanUp = () => fs.rmSync(file, { force: true });
    gdb.on("exit", (code) => {
        cleanUp();
        process.exit(code === null ? 1 : code);
    });
    process.stdin.on("end", () => gdb.stdin.end());
    for (const signal of ["SIGINT", "SIGTERM"]) {
        process.on(signal, () => gdb.kill(signal));
    }
}

main(process.argv.slice(2));
